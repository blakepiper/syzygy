import sqlite3
from datetime import UTC, datetime

import pytest

from syzygy.domain.astrology import BirthData, NatalAspect, NatalChart, NatalPlacement
from syzygy.domain.profile import Profile
from syzygy.storage.database import connect
from syzygy.storage.migrations import apply_all
from syzygy.storage.profiles import (
    count_readings,
    delete_profile,
    get_profile,
    insert_profile,
    list_profiles,
)


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "test.db")
    apply_all(connection)
    yield connection
    connection.close()


def _profile(profile_id: str = "p1", display_name: str = "Blake") -> Profile:
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
    now = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    return Profile(
        id=profile_id,
        display_name=display_name,
        birth_data=birth_data,
        natal_chart=natal_chart,
        created_at_utc=now,
        updated_at_utc=now,
    )


def test_insert_and_get_profile_round_trips(conn):
    profile = _profile()
    insert_profile(conn, profile)
    fetched = get_profile(conn, profile.id)
    assert fetched == profile


def test_get_profile_returns_none_when_missing(conn):
    assert get_profile(conn, "no-such-profile") is None


def test_list_profiles_returns_all_in_creation_order(conn):
    insert_profile(conn, _profile("p1", "Blake"))
    insert_profile(conn, _profile("p2", "Alex"))
    listed = list_profiles(conn)
    assert [p.id for p in listed] == ["p1", "p2"]


def test_natal_chart_round_trips_exactly(conn):
    profile = _profile()
    insert_profile(conn, profile)
    fetched = get_profile(conn, profile.id)
    assert fetched.natal_chart == profile.natal_chart


# -- M11.2: deletion -----------------------------------------------------


def _insert_reading(conn, profile_id: str, local_date: str, reading_id: str) -> None:
    """A minimal `readings` row - this module tests deletion, not the
    reading state machine, so it writes the columns the schema requires
    and nothing more."""
    now = "2026-08-07T12:00:00+00:00"
    conn.execute(
        """
        INSERT INTO readings (
            id, profile_id, consultation_local_date, consultation_local_timestamp,
            consultation_utc_timestamp, consultation_timezone, status,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'PREPARED', ?, ?)
        """,
        (reading_id, profile_id, local_date, now, now, "America/New_York", now, now),
    )


def test_delete_profile_removes_it(conn):
    insert_profile(conn, _profile("p1", "Blake"))
    insert_profile(conn, _profile("p2", "Alex"))

    assert delete_profile(conn, "p1") == 0

    assert get_profile(conn, "p1") is None
    assert [p.id for p in list_profiles(conn)] == ["p2"]


def test_delete_profile_cascades_to_its_readings(conn):
    insert_profile(conn, _profile("p1", "Blake"))
    insert_profile(conn, _profile("p2", "Alex"))
    _insert_reading(conn, "p1", "2026-08-06", "r1")
    _insert_reading(conn, "p1", "2026-08-07", "r2")
    _insert_reading(conn, "p2", "2026-08-07", "r3")

    assert delete_profile(conn, "p1") == 2

    assert get_profile(conn, "p1") is None
    remaining = conn.execute("SELECT id, profile_id FROM readings").fetchall()
    assert [(row["id"], row["profile_id"]) for row in remaining] == [("r3", "p2")]


def test_delete_profile_leaves_other_profiles_readings_alone(conn):
    insert_profile(conn, _profile("p1", "Blake"))
    insert_profile(conn, _profile("p2", "Alex"))
    _insert_reading(conn, "p2", "2026-08-07", "r1")

    delete_profile(conn, "p1")

    assert count_readings(conn, "p2") == 1


def test_delete_missing_profile_is_not_an_error(conn):
    assert delete_profile(conn, "no-such-profile") == 0


def test_count_readings(conn):
    insert_profile(conn, _profile("p1", "Blake"))
    assert count_readings(conn, "p1") == 0
    _insert_reading(conn, "p1", "2026-08-06", "r1")
    _insert_reading(conn, "p1", "2026-08-07", "r2")
    assert count_readings(conn, "p1") == 2


class _FailOnProfileDelete:
    """A connection proxy that lets everything through except the profile
    delete itself. `sqlite3.Connection.execute` is read-only and cannot be
    monkeypatched, so the failure is injected by wrapping instead."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, *args):
        if sql.startswith("DELETE FROM profiles"):
            raise sqlite3.OperationalError("simulated failure")
        return self._conn.execute(sql, *args)


def test_delete_is_atomic_when_the_profile_delete_fails(conn):
    """The readings go first (a plain `REFERENCES` with foreign keys on
    means they have to), so a failure on the second statement must not
    leave a profile whose readings have already been destroyed."""
    insert_profile(conn, _profile("p1", "Blake"))
    _insert_reading(conn, "p1", "2026-08-07", "r1")

    with pytest.raises(sqlite3.OperationalError):
        delete_profile(_FailOnProfileDelete(conn), "p1")

    assert get_profile(conn, "p1") is not None
    assert count_readings(conn, "p1") == 1
