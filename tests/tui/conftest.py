"""Fixtures for the Textual interface tests.

The whole ritual is exercised against a canned `AstrologyEngine` and the
`FixtureProvider`: no ephemeris work, no network, no API key, no model
(IMPLEMENTATION_PLAN.md Milestone 5). The fixture engine lives here rather
than in `src/` deliberately - shipping a fake astrology backend inside the
application would be a way for fabricated positions to reach a real
reading.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from syzygy.astrology.policy import POLICY_VERSION
from syzygy.clock import FixedClock
from syzygy.domain.astrology import (
    BirthData,
    NatalAspect,
    NatalChart,
    NatalPlacement,
    TransitAspect,
    TransitSnapshot,
)
from syzygy.domain.profile import Profile
from syzygy.interpretation.providers.fixture import FixtureProvider
from syzygy.storage.database import connect
from syzygy.storage.migrations import apply_all
from syzygy.storage.profiles import insert_profile
from syzygy.tui.app import SyzygyApp, SyzygyServices

FIXED_NOW = datetime(2026, 8, 7, 15, 30, tzinfo=UTC)

BIRTH_DATA = BirthData(
    local_date="1990-08-07",
    local_time="14:22:00",
    place_label="Alexandria, Virginia, USA",
    latitude=38.8048,
    longitude=-77.0469,
    timezone="America/New_York",
)

_PLACEMENTS = [
    NatalPlacement(body="Sun", sign="Virgo", longitude=164.37, house=10),
    NatalPlacement(body="Moon", sign="Pisces", longitude=338.18, house=4),
    NatalPlacement(body="Mercury", sign="Leo", longitude=142.10, house=9),
    NatalPlacement(body="Venus", sign="Libra", longitude=190.55, house=11),
    NatalPlacement(body="Mars", sign="Cancer", longitude=100.02, house=8),
    NatalPlacement(body="Jupiter", sign="Cancer", longitude=110.44, house=8),
    NatalPlacement(body="Saturn", sign="Capricorn", longitude=280.61, house=2),
    NatalPlacement(body="Uranus", sign="Capricorn", longitude=277.90, house=2, retrograde=True),
    NatalPlacement(body="Neptune", sign="Capricorn", longitude=283.12, house=2, retrograde=True),
    NatalPlacement(body="Pluto", sign="Scorpio", longitude=225.73, house=12),
]
# Note the shape this mirrors: the Kerykeion adapter returns exactly the
# ten transit bodies as placements, and carries the two angles as
# `ascendant_longitude`/`midheaven_longitude` instead. A fixture that
# invented an "Ascendant" placement would let screens rely on a field the
# real engine never produces.

NATAL_CHART = NatalChart(
    birth_data=BIRTH_DATA,
    placements=_PLACEMENTS,
    aspects=[NatalAspect(body_a="Sun", body_b="Moon", aspect="opposition", orb_degrees=1.81)],
    ascendant_longitude=228.72,
    midheaven_longitude=150.11,
    astrology_engine="fixture",
    astrology_engine_version="0",
    chart_schema_version="natal-v1",
)

#: Two aspects that pass `TransitAspectPolicy` and one that cannot, so
#: tests see filtering actually happen rather than a hand-picked result.
_TRANSIT_ASPECTS = [
    TransitAspect(
        transiting_body="Saturn",
        natal_target="Venus",
        aspect="square",
        orb_degrees=0.80,
        movement="applying",
    ),
    TransitAspect(
        transiting_body="Mars",
        natal_target="Sun",
        aspect="trine",
        orb_degrees=1.20,
        movement="separating",
    ),
    TransitAspect(
        transiting_body="Moon",
        natal_target="Pluto",
        aspect="sextile",
        orb_degrees=1.90,  # beyond the transiting-Moon cap: must be filtered out
        movement="applying",
    ),
]


class FixtureAstrologyEngine:
    """Canned `AstrologyEngine`. Returns the same chart and sky always."""

    def calculate_natal(self, birth: BirthData) -> NatalChart:
        return NATAL_CHART.model_copy(update={"birth_data": birth})

    def calculate_transits(self, natal: NatalChart, instant: datetime) -> TransitSnapshot:
        return TransitSnapshot(
            instant_utc=instant,
            transiting_positions=[
                NatalPlacement(body="Saturn", sign="Aries", longitude=10.5),
                NatalPlacement(body="Mars", sign="Sagittarius", longitude=244.4),
            ],
            raw_aspects=list(_TRANSIT_ASPECTS),
            astrology_policy_version=POLICY_VERSION,
        )


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "syzygy.db", check_same_thread=False)
    apply_all(connection)
    yield connection
    connection.close()


@pytest.fixture
def services(conn) -> SyzygyServices:
    return SyzygyServices(
        conn=conn,
        clock=FixedClock(FIXED_NOW),
        astrology=FixtureAstrologyEngine(),
        provider=FixtureProvider(),
    )


@pytest.fixture
def profile(conn) -> Profile:
    saved = Profile(
        id=str(uuid.uuid4()),
        display_name="Blake",
        birth_data=BIRTH_DATA,
        natal_chart=NATAL_CHART,
        created_at_utc=FIXED_NOW,
        updated_at_utc=FIXED_NOW,
    )
    insert_profile(conn, saved)
    return saved


@pytest.fixture
def app(services) -> SyzygyApp:
    return SyzygyApp(services)
