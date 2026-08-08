"""Tests for `syzygy.astrology.kerykeion_backend.KerykeionAstrologyEngine`.

Per AGENTS.md, non-deterministic/real-astronomy output isn't asserted
exact-value here except where cross-checked against an independently
computed reference (the DST-boundary test below uses Python's own
`zoneinfo`, not Kerykeion, to compute the expected UTC offset). Everything
else tests structural invariants: determinism, schema completeness, and
the "no current-location astrology" boundary (DESIGN.md 3.2, 25.2).
"""

from __future__ import annotations

import importlib.metadata
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from kerykeion import AstrologicalSubjectFactory

from syzygy.astrology import kerykeion_backend
from syzygy.astrology.kerykeion_backend import KerykeionAstrologyEngine
from syzygy.domain.astrology import TRANSIT_BODIES, BirthData

ENGINE = KerykeionAstrologyEngine()

WASHINGTON_DC_BIRTH = BirthData(
    local_date="1990-08-07",
    local_time="14:22:00",
    place_label="Washington, DC, USA",
    latitude=38.8048,
    longitude=-77.0469,
    timezone="America/New_York",
)

TOKYO_BIRTH = BirthData(
    local_date="1985-11-23",
    local_time="09:15:00",
    place_label="Tokyo, Japan",
    latitude=35.6762,
    longitude=139.6503,
    timezone="Asia/Tokyo",
)


def test_calculate_natal_is_pure_function_of_birth_data():
    first = ENGINE.calculate_natal(WASHINGTON_DC_BIRTH)
    second = ENGINE.calculate_natal(WASHINGTON_DC_BIRTH)
    assert first == second


def test_natal_placements_cover_all_ten_transit_bodies_with_houses():
    natal = ENGINE.calculate_natal(WASHINGTON_DC_BIRTH)
    bodies = {p.body for p in natal.placements}
    assert bodies == set(TRANSIT_BODIES)
    for placement in natal.placements:
        assert placement.house is not None
        assert 1 <= placement.house <= 12
        assert 0 <= placement.longitude < 360


def test_natal_chart_metadata():
    natal = ENGINE.calculate_natal(WASHINGTON_DC_BIRTH)
    assert natal.astrology_engine == "kerykeion"
    assert natal.astrology_engine_version == importlib.metadata.version("kerykeion")
    assert natal.chart_schema_version == "chart-v1"
    assert natal.zodiac_type == "tropical"
    assert 0 <= natal.ascendant_longitude < 360
    assert 0 <= natal.midheaven_longitude < 360


def test_non_us_birthplace_computes_without_error():
    natal = ENGINE.calculate_natal(TOKYO_BIRTH)
    assert len(natal.placements) == 10
    assert 0 <= natal.ascendant_longitude < 360


def test_dst_boundary_birth_uses_correct_utc_offset():
    # 2020-03-08 is the US spring-forward DST transition (2:00am -> 3:00am
    # America/New_York). A birth at 14:00 local on this date is EDT
    # (UTC-4), not EST (UTC-5) - if `kerykeion_backend` mishandled
    # `tz_str` (e.g. resolved a fixed offset instead of consulting the
    # IANA database for this specific date), the natal Sun position would
    # be off by roughly one hour of solar motion (~0.04 degrees).
    birth = BirthData(
        local_date="2020-03-08",
        local_time="14:00:00",
        place_label="New York, NY, USA",
        latitude=40.7128,
        longitude=-74.0060,
        timezone="America/New_York",
    )
    natal = ENGINE.calculate_natal(birth)
    sun = next(p for p in natal.placements if p.body == "Sun")

    local_dt = datetime(2020, 3, 8, 14, 0, 0, tzinfo=ZoneInfo("America/New_York"))
    offset = local_dt.utcoffset()
    assert offset is not None
    assert offset.total_seconds() == -4 * 3600  # sanity: EDT, not EST
    utc_dt = local_dt.astimezone(ZoneInfo("UTC"))

    # Independently-derived reference: ask Kerykeion for the Sun's position
    # directly at that UTC instant, bypassing `tz_str` resolution entirely.
    reference = AstrologicalSubjectFactory.from_iso_utc_time(
        name="reference",
        iso_utc_time=utc_dt.isoformat(),
        lat=birth.latitude,
        lng=birth.longitude,
        tz_str="UTC",
        online=False,
        active_points=["Sun"],
    )
    assert reference.sun is not None
    assert sun.longitude == pytest.approx(reference.sun.abs_pos, abs=1e-6)


def test_calculate_transits_returns_ten_transiting_positions_with_no_houses():
    natal = ENGINE.calculate_natal(WASHINGTON_DC_BIRTH)
    snapshot = ENGINE.calculate_transits(natal, datetime(2026, 8, 7, 12, 0, tzinfo=UTC))
    assert {p.body for p in snapshot.transiting_positions} == set(TRANSIT_BODIES)
    assert all(p.house is None for p in snapshot.transiting_positions)


def test_raw_aspects_never_use_an_axis_as_the_transiting_source():
    natal = ENGINE.calculate_natal(WASHINGTON_DC_BIRTH)
    snapshot = ENGINE.calculate_transits(natal, datetime(2026, 8, 7, 12, 0, tzinfo=UTC))
    assert all(a.transiting_body in TRANSIT_BODIES for a in snapshot.raw_aspects)


def test_raw_aspects_use_midheaven_not_medium_coeli_for_the_mc_target():
    natal = ENGINE.calculate_natal(WASHINGTON_DC_BIRTH)
    snapshot = ENGINE.calculate_transits(natal, datetime(2026, 8, 7, 12, 0, tzinfo=UTC))
    targets = {a.natal_target for a in snapshot.raw_aspects}
    assert "Medium_Coeli" not in targets
    # (Not asserting "Midheaven" is present - whether any aspect happens to
    # land on it this particular instant is not guaranteed.)


def test_raw_aspects_movement_values_are_lowercase():
    natal = ENGINE.calculate_natal(WASHINGTON_DC_BIRTH)
    snapshot = ENGINE.calculate_transits(natal, datetime(2026, 8, 7, 12, 0, tzinfo=UTC))
    assert all(a.movement in ("applying", "separating", "static") for a in snapshot.raw_aspects)


def test_snapshot_records_instant_and_policy_version():
    natal = ENGINE.calculate_natal(WASHINGTON_DC_BIRTH)
    instant = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    snapshot = ENGINE.calculate_transits(natal, instant)
    assert snapshot.instant_utc == instant
    assert snapshot.astrology_policy_version == "transit-policy-v1"


def test_current_location_invariance(monkeypatch: pytest.MonkeyPatch):
    """DESIGN.md 25.2: transiting body longitudes must not depend on the
    engine's internal placeholder location for the transiting subject.
    """
    natal = ENGINE.calculate_natal(WASHINGTON_DC_BIRTH)
    instant = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)

    monkeypatch.setattr(kerykeion_backend, "_TRANSIT_PLACEHOLDER_LAT", 0.0)
    monkeypatch.setattr(kerykeion_backend, "_TRANSIT_PLACEHOLDER_LNG", 0.0)
    monkeypatch.setattr(kerykeion_backend, "_TRANSIT_PLACEHOLDER_TZ", "UTC")
    snapshot_a = ENGINE.calculate_transits(natal, instant)

    monkeypatch.setattr(kerykeion_backend, "_TRANSIT_PLACEHOLDER_LAT", 51.5074)
    monkeypatch.setattr(kerykeion_backend, "_TRANSIT_PLACEHOLDER_LNG", -0.1278)
    monkeypatch.setattr(kerykeion_backend, "_TRANSIT_PLACEHOLDER_TZ", "Europe/London")
    snapshot_b = ENGINE.calculate_transits(natal, instant)

    positions_a = {p.body: p.longitude for p in snapshot_a.transiting_positions}
    positions_b = {p.body: p.longitude for p in snapshot_b.transiting_positions}
    assert positions_a.keys() == positions_b.keys()
    for body, longitude in positions_a.items():
        assert longitude == pytest.approx(positions_b[body], abs=1e-9)
