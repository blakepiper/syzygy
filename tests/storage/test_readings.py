"""Same-day idempotency, retry-without-redraw, and crash-recovery for
`syzygy.storage.reading_service.get_or_create_todays_reading`
(IMPLEMENTATION_PLAN.md §4.3 - the literal ARCHITECTURE_HANDOFF.md §23
test: "kill the flow after DRAWN, restart, prove the same card
survives").
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from syzygy.astrology.policy import POLICY_VERSION
from syzygy.clock import FixedClock
from syzygy.domain.astrology import (
    BirthData,
    NatalAspect,
    NatalChart,
    NatalPlacement,
    TransitSnapshot,
)
from syzygy.domain.interpretation import InterpretationContext, InterpretationResult
from syzygy.domain.profile import Profile
from syzygy.domain.reading import ReadingStatus
from syzygy.interpretation.providers.fixture import FixtureProvider
from syzygy.sortes.draw import draw_card
from syzygy.sortes.entropy import EntropyCollector
from syzygy.storage import readings
from syzygy.storage.database import connect
from syzygy.storage.migrations import apply_all
from syzygy.storage.profiles import insert_profile
from syzygy.storage.reading_service import get_or_create_todays_reading

FIXED_NOW = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "test.db")
    apply_all(connection)
    yield connection
    connection.close()


def _fixed_os_random_factory(seed_byte: int):
    def _os_random(n: int) -> bytes:
        return bytes([seed_byte]) * n

    return _os_random


def _profile() -> Profile:
    birth_data = BirthData(
        local_date="1990-08-07",
        local_time="14:22:00",
        place_label="New York, NY",
        latitude=40.7128,
        longitude=-74.006,
        timezone="America/New_York",
    )
    natal_chart = NatalChart(
        birth_data=birth_data,
        placements=[
            NatalPlacement(body="Sun", sign="Leo", longitude=135.0, house=10),
            NatalPlacement(body="Moon", sign="Pisces", longitude=338.0, house=4),
        ],
        aspects=[NatalAspect(body_a="Sun", body_b="Moon", aspect="square", orb_degrees=1.5)],
        ascendant_longitude=210.0,
        midheaven_longitude=120.0,
        astrology_engine="kerykeion",
        astrology_engine_version="5.12.9",
        chart_schema_version="chart-v1",
    )
    now = FIXED_NOW
    return Profile(
        id="p1",
        display_name="Blake",
        birth_data=birth_data,
        natal_chart=natal_chart,
        created_at_utc=now,
        updated_at_utc=now,
    )


class _CountingAstrologyEngine:
    """Records how many times transits are (re)computed, so tests can
    prove a reopened/resumed reading never recalculates a stage that was
    already committed.
    """

    def __init__(self) -> None:
        self.calculate_transits_calls = 0

    def calculate_natal(self, birth: BirthData) -> NatalChart:
        raise AssertionError("calculate_natal should never be called by the reading service")

    def calculate_transits(self, natal: NatalChart, instant: datetime) -> TransitSnapshot:
        self.calculate_transits_calls += 1
        return TransitSnapshot(
            instant_utc=instant,
            transiting_positions=[],
            raw_aspects=[],
            astrology_policy_version=POLICY_VERSION,
        )


class _FailingProvider:
    provider_id = "failing"
    model_id = "failing-v1"

    async def interpret(self, context: InterpretationContext) -> InterpretationResult:
        raise RuntimeError("simulated provider failure")


def test_first_call_creates_a_complete_reading(conn):
    profile = _profile()
    insert_profile(conn, profile)

    reading = _run(conn, profile)

    assert reading.status == ReadingStatus.COMPLETE
    assert reading.card_draw is not None
    assert reading.interpretation is not None


def test_second_call_same_day_returns_same_reading_unchanged(conn):
    profile = _profile()
    insert_profile(conn, profile)

    first = _run(conn, profile)
    engine = _CountingAstrologyEngine()
    second = _run(conn, profile, engine=engine)

    assert second == first
    assert engine.calculate_transits_calls == 0  # reopening a COMPLETE reading is a pure read


def test_crash_after_drawn_recovers_the_same_card_without_redrawing(conn):
    profile = _profile()
    insert_profile(conn, profile)

    # Simulate the pipeline crashing right after the card is committed but
    # before astrology/context/interpretation ever ran.
    reading = readings.create_prepared(
        conn,
        profile_id=profile.id,
        consultation_local_date=FIXED_NOW.date().isoformat(),
        consultation_local_timestamp=FIXED_NOW.isoformat(),
        consultation_utc_timestamp=FIXED_NOW,
        consultation_timezone="UTC",
    )
    collector = EntropyCollector(session_nonce=b"x", os_random=_fixed_os_random_factory(7))
    draw = draw_card(collector, now=FIXED_NOW)
    reading = readings.commit_draw(conn, reading.id, draw)
    assert reading.status == ReadingStatus.DRAWN

    # "Restart": brand new collaborator instances, same conn/profile.
    recovered = _run(conn, profile)

    assert recovered.status == ReadingStatus.COMPLETE
    assert recovered.card_draw is not None
    assert recovered.card_draw.card_id == draw.card_id
    assert recovered.card_draw.entropy_digest == draw.entropy_digest


def test_interpretation_failure_can_be_retried_without_a_new_card_id(conn):
    profile = _profile()
    insert_profile(conn, profile)

    failed = _run(conn, profile, provider=_FailingProvider())
    assert failed.status == ReadingStatus.INTERPRETATION_FAILED
    assert failed.card_draw is not None

    retried = _run(conn, profile, provider=FixtureProvider())
    assert retried.status == ReadingStatus.COMPLETE
    assert retried.card_draw is not None
    assert retried.card_draw.card_id == failed.card_draw.card_id


def _run(conn, profile, *, engine=None, provider=None):
    engine = engine or _CountingAstrologyEngine()
    provider = provider or FixtureProvider()
    collector = EntropyCollector(session_nonce=b"x", os_random=_fixed_os_random_factory(7))
    clock = FixedClock(FIXED_NOW)
    return _await(
        get_or_create_todays_reading(conn, profile, clock, engine, collector, provider)
    )


def _await(coro):
    import asyncio

    return asyncio.run(coro)
