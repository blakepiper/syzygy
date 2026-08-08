"""The dev-only reroll (M11.6).

These tests care most about the two things that make this safe to have at
all: it is unreachable without `SYZYGY_DEV`, and it does not weaken the
one-reading-per-day invariant it appears to contradict.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime

import pytest

from syzygy.clock import FixedClock
from syzygy.dev import DEV_MODE_ENV_VAR, dev_mode_enabled, discard_todays_reading
from syzygy.domain.astrology import BirthData, NatalChart, NatalPlacement
from syzygy.domain.profile import Profile
from syzygy.sortes.entropy import EntropyCollector
from syzygy.storage import readings as readings_store
from syzygy.storage.database import connect
from syzygy.storage.migrations import apply_all
from syzygy.storage.profiles import insert_profile
from syzygy.storage.reading_service import draw_todays_reading

FIXED_NOW = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)

BIRTH = BirthData(
    local_date="1990-08-07",
    local_time="14:22:00",
    place_label="Alexandria, Virginia, USA",
    latitude=38.8048,
    longitude=-77.0469,
    timezone="America/New_York",
)

CHART = NatalChart(
    birth_data=BIRTH,
    # All ten transit bodies: the context builder resolves every one of
    # them, so a two-planet chart fails before it reaches anything this
    # module is testing.
    placements=[
        NatalPlacement(body="Sun", sign="Leo", longitude=135.0, house=10),
        NatalPlacement(body="Moon", sign="Pisces", longitude=338.0, house=4),
        NatalPlacement(body="Mercury", sign="Leo", longitude=142.1, house=9),
        NatalPlacement(body="Venus", sign="Libra", longitude=190.55, house=11),
        NatalPlacement(body="Mars", sign="Cancer", longitude=100.02, house=8),
        NatalPlacement(body="Jupiter", sign="Cancer", longitude=110.44, house=8),
        NatalPlacement(body="Saturn", sign="Capricorn", longitude=280.61, house=2),
        NatalPlacement(body="Uranus", sign="Capricorn", longitude=277.9, house=2),
        NatalPlacement(body="Neptune", sign="Capricorn", longitude=283.12, house=2),
        NatalPlacement(body="Pluto", sign="Scorpio", longitude=225.73, house=12),
    ],
    aspects=[],
    ascendant_longitude=210.0,
    midheaven_longitude=120.0,
    astrology_engine="fixture",
    astrology_engine_version="0",
    chart_schema_version="natal-v1",
)


class _Engine:
    def calculate_natal(self, birth):
        return CHART.model_copy(update={"birth_data": birth})

    def calculate_transits(self, natal, instant):
        from syzygy.astrology.policy import POLICY_VERSION
        from syzygy.domain.astrology import TransitSnapshot

        return TransitSnapshot(
            instant_utc=instant,
            transiting_positions=[],
            raw_aspects=[],
            astrology_policy_version=POLICY_VERSION,
        )


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "dev.db")
    apply_all(connection)
    yield connection
    connection.close()


@pytest.fixture
def profile(conn) -> Profile:
    saved = Profile(
        id=str(uuid.uuid4()),
        display_name="Blake",
        birth_data=BIRTH,
        natal_chart=CHART,
        created_at_utc=FIXED_NOW,
        updated_at_utc=FIXED_NOW,
    )
    insert_profile(conn, saved)
    return saved


@pytest.fixture
def dev_mode(monkeypatch):
    monkeypatch.setenv(DEV_MODE_ENV_VAR, "1")


def _draw(conn, profile, seed: int):
    def os_random(n: int) -> bytes:
        return bytes([seed]) * n

    return draw_todays_reading(
        conn,
        profile,
        FixedClock(FIXED_NOW),
        _Engine(),
        EntropyCollector(session_nonce=bytes([seed]), os_random=os_random),
    )


def _local_date() -> str:
    return FixedClock(FIXED_NOW).now_utc().astimezone().date().isoformat()


# -- the switch ----------------------------------------------------------


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " 1 "])
def test_dev_mode_recognises_affirmative_values(monkeypatch, value):
    monkeypatch.setenv(DEV_MODE_ENV_VAR, value)
    assert dev_mode_enabled()


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "maybe"])
def test_dev_mode_is_off_for_anything_else(monkeypatch, value):
    monkeypatch.setenv(DEV_MODE_ENV_VAR, value)
    assert not dev_mode_enabled()


def test_dev_mode_is_off_when_unset(monkeypatch):
    monkeypatch.delenv(DEV_MODE_ENV_VAR, raising=False)
    assert not dev_mode_enabled()


def test_discard_refuses_without_the_switch(conn, profile, monkeypatch):
    """Belt and braces: the TUI never binds the key and the CLI refuses
    first, but the function itself must not be callable either."""
    monkeypatch.delenv(DEV_MODE_ENV_VAR, raising=False)
    _draw(conn, profile, 7)

    with pytest.raises(RuntimeError, match=DEV_MODE_ENV_VAR):
        discard_todays_reading(conn, profile.id, _local_date())

    assert readings_store.get_today(conn, profile.id, _local_date()) is not None


# -- what it actually does -----------------------------------------------


def test_discard_removes_todays_reading(conn, profile, dev_mode):
    _draw(conn, profile, 7)
    assert discard_todays_reading(conn, profile.id, _local_date()) is True
    assert readings_store.get_today(conn, profile.id, _local_date()) is None


def test_discard_reports_when_there_was_nothing_to_discard(conn, profile, dev_mode):
    assert discard_todays_reading(conn, profile.id, _local_date()) is False


def test_reroll_draws_a_genuinely_new_reading_through_the_normal_path(conn, profile, dev_mode):
    """The card is not mutated and no second row is written: the day's
    reading is deleted, and the ordinary draw path runs from the start."""
    first = _draw(conn, profile, 7)
    assert first.card_draw is not None

    discard_todays_reading(conn, profile.id, _local_date())
    second = _draw(conn, profile, 200)

    assert second.id != first.id
    assert second.card_draw is not None
    # A fresh trip through `syzygy.sortes`, not a copied draw. The card id
    # itself is not asserted: two draws may legitimately land on the same
    # card, and pinning one would be pinning the RNG.
    assert second.card_draw.entropy_digest != first.card_draw.entropy_digest


def test_repeated_rerolls_do_produce_different_cards(conn, profile, dev_mode):
    """The point of the affordance: seeing new cards without waiting a
    day. Distinct entropy could in principle still keep landing on one
    card, so assert the outcome the user actually cares about."""
    drawn = set()
    for seed in range(1, 12):
        discard_todays_reading(conn, profile.id, _local_date())
        reading = _draw(conn, profile, seed)
        assert reading.card_draw is not None
        drawn.add(reading.card_draw.card_id)
    assert len(drawn) > 1


def test_exactly_one_reading_per_day_survives_a_reroll(conn, profile, dev_mode):
    for seed in (7, 40, 90, 200):
        discard_todays_reading(conn, profile.id, _local_date())
        _draw(conn, profile, seed)

    rows = conn.execute(
        "SELECT COUNT(*) AS total FROM readings WHERE profile_id = ? "
        "AND consultation_local_date = ?",
        (profile.id, _local_date()),
    ).fetchone()
    assert rows["total"] == 1


def test_the_unique_constraint_is_still_the_thing_enforcing_it(conn, profile, dev_mode):
    """M11.6d: reroll must not have loosened the database's own guarantee."""
    reading = _draw(conn, profile, 7)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO readings (
                id, profile_id, consultation_local_date, consultation_local_timestamp,
                consultation_utc_timestamp, consultation_timezone, status,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'PREPARED', ?, ?)
            """,
            (
                "a-second-row",
                profile.id,
                reading.consultation_local_date,
                FIXED_NOW.isoformat(),
                FIXED_NOW.isoformat(),
                "UTC",
                FIXED_NOW.isoformat(),
                FIXED_NOW.isoformat(),
            ),
        )


def test_discard_leaves_other_days_and_profiles_alone(conn, profile, dev_mode):
    _draw(conn, profile, 7)
    conn.execute(
        """
        INSERT INTO readings (
            id, profile_id, consultation_local_date, consultation_local_timestamp,
            consultation_utc_timestamp, consultation_timezone, status,
            created_at, updated_at
        ) VALUES ('yesterday', ?, '2026-08-06', ?, ?, 'UTC', 'PREPARED', ?, ?)
        """,
        (profile.id, FIXED_NOW.isoformat(), FIXED_NOW.isoformat(), FIXED_NOW.isoformat(),
         FIXED_NOW.isoformat()),
    )

    discard_todays_reading(conn, profile.id, _local_date())

    remaining = conn.execute("SELECT id FROM readings").fetchall()
    assert [row["id"] for row in remaining] == ["yesterday"]
