from datetime import UTC, datetime

import pytest

from syzygy.domain.astrology import BirthData, NatalAspect, NatalChart, NatalPlacement
from syzygy.domain.profile import Profile
from syzygy.storage.database import connect
from syzygy.storage.migrations import apply_all
from syzygy.storage.profiles import get_profile, insert_profile, list_profiles


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
