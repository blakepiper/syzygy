"""Kerykeion-backed implementation of `AstrologyEngine`.

Everything Kerykeion-shaped (its subject models, its point/house naming,
its `AspectModel`) is converted into `syzygy.domain.astrology` types
before it leaves this module. Nothing outside `syzygy.astrology` may
import `kerykeion` (AGENTS.md).

Verified against Kerykeion 5.12.9 - see docs/old/IMPLEMENTATION_PLAN.md section
2.2 for the interactive inspection this module is built from, and the
"Deviation" note below for one place this module's behavior differs from
that section's literal description.
"""

from __future__ import annotations

import importlib.metadata
from datetime import UTC, date, datetime, time
from typing import cast

from kerykeion import AspectsFactory, AstrologicalSubjectFactory
from kerykeion.schemas.kr_literals import AspectName, AstrologicalPoint, HousesSystemIdentifier
from kerykeion.schemas.kr_models import ActiveAspect, AstrologicalSubjectModel

from syzygy.astrology.policy import POLICY_VERSION
from syzygy.domain.astrology import (
    MAJOR_ASPECTS,
    TRANSIT_BODIES,
    BirthData,
    NatalAspect,
    NatalChart,
    NatalPlacement,
    TransitAspect,
    TransitSnapshot,
)

CHART_SCHEMA_VERSION = "chart-v1"

#: Points requested on the natal subject: the ten transit bodies plus the
#: two natal angles (docs/old/IMPLEMENTATION_PLAN.md section 2.2). Deliberately
#: excludes lunar nodes, Chiron, and Mean Lilith - docs/old/DESIGN.md section 9.3.
NATAL_ACTIVE_POINTS: tuple[AstrologicalPoint, ...] = (
    *(cast(AstrologicalPoint, body) for body in TRANSIT_BODIES),
    "Ascendant",
    "Medium_Coeli",
)

#: House system identifier map. v0.1 only ever uses Placidus (docs/old/DESIGN.md
#: section 9.2) - this is intentionally not a general abstraction.
_HOUSE_SYSTEM_IDENTIFIERS: dict[str, HousesSystemIdentifier] = {"placidus": "P"}

#: Kerykeion reports signs as 3-letter abbreviations and houses as
#: `"First_House"`..`"Twelfth_House"` strings; `thoth_deck.yaml` and the
#: rest of Syzygy's domain use full sign names and 1-12 ints. These maps
#: are Syzygy's, not Kerykeion's - keeping them here, not in `domain`,
#: keeps the conversion co-located with the only code that needs it.
_FULL_SIGN_NAMES: tuple[str, ...] = (
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
)

_HOUSE_NUMBERS: dict[str, int] = {
    "First_House": 1, "Second_House": 2, "Third_House": 3, "Fourth_House": 4,
    "Fifth_House": 5, "Sixth_House": 6, "Seventh_House": 7, "Eighth_House": 8,
    "Ninth_House": 9, "Tenth_House": 10, "Eleventh_House": 11, "Twelfth_House": 12,
}

#: Kerykeion's point name for the natal Midheaven; Syzygy's domain (and
#: `syzygy.astrology.policy.NATAL_ANGLE_TARGETS`) calls it "Midheaven".
_MEDIUM_COELI = "Medium_Coeli"
_MIDHEAVEN = "Midheaven"

#: Orb requested from Kerykeion itself, for both natal and transit aspect
#: calculation. Deliberately wider than every cap in
#: `syzygy.astrology.policy` (max 3.0, angle 2.0, Moon 1.5 degrees) so the
#: "raw" snapshot this engine returns is not pre-filtered before the
#: policy gets to see it - see docs/old/DESIGN.md section 9.5 ("always retain the
#: complete transit snapshot"). `ActiveAspect.orb` is Kerykeion's own
#: `int`-typed field, hence an int here rather than a float.
_ENGINE_ASPECT_ORB_DEGREES = 8

#: A placeholder, non-geocentric-relevant location for the transiting
#: subject. Geocentric planetary longitude does not depend on observer
#: location, only house/angle placements do - and the transiting subject
#: requests no houses. See the "Deviation" note on `calculate_transits`
#: for why Ascendant/Medium_Coeli are nonetheless requested on this
#: subject internally.
_TRANSIT_PLACEHOLDER_LAT = 0.0
_TRANSIT_PLACEHOLDER_LNG = 0.0
_TRANSIT_PLACEHOLDER_TZ = "UTC"

_ACTIVE_ASPECTS = [
    ActiveAspect(name=cast(AspectName, a), orb=_ENGINE_ASPECT_ORB_DEGREES) for a in MAJOR_ASPECTS
]


def _engine_version() -> str:
    return importlib.metadata.version("kerykeion")


def _to_placement(point: object, *, include_house: bool) -> NatalPlacement:
    return NatalPlacement(
        body=point.name,  # type: ignore[attr-defined]
        sign=_FULL_SIGN_NAMES[point.sign_num],  # type: ignore[attr-defined]
        longitude=point.abs_pos,  # type: ignore[attr-defined]
        house=_HOUSE_NUMBERS[point.house] if include_house else None,  # type: ignore[attr-defined]
        retrograde=bool(point.retrograde),  # type: ignore[attr-defined]
    )


def _build_natal_subject(birth: BirthData) -> AstrologicalSubjectModel:
    local_date = date.fromisoformat(birth.local_date)
    local_time = time.fromisoformat(birth.local_time)
    house_system = _HOUSE_SYSTEM_IDENTIFIERS[birth.house_system]
    return AstrologicalSubjectFactory.from_birth_data(
        name="natal",
        year=local_date.year,
        month=local_date.month,
        day=local_date.day,
        hour=local_time.hour,
        minute=local_time.minute,
        lat=birth.latitude,
        lng=birth.longitude,
        tz_str=birth.timezone,
        online=False,
        zodiac_type="Tropical",
        houses_system_identifier=house_system,
        active_points=list(NATAL_ACTIVE_POINTS),
    )


class KerykeionAstrologyEngine:
    """Production `AstrologyEngine` implementation, backed by Kerykeion."""

    def calculate_natal(self, birth: BirthData) -> NatalChart:
        subject = _build_natal_subject(birth)

        placements = [
            _to_placement(getattr(subject, body.lower()), include_house=True)
            for body in TRANSIT_BODIES
        ]

        single = AspectsFactory.single_chart_aspects(
            subject,
            active_points=list(NATAL_ACTIVE_POINTS),
            active_aspects=_ACTIVE_ASPECTS,
        )
        aspects = [
            NatalAspect(
                body_a=a.p1_name,
                body_b=a.p2_name,
                aspect=a.aspect,
                orb_degrees=a.orbit,
            )
            for a in single.aspects
        ]

        assert subject.ascendant is not None
        assert subject.medium_coeli is not None
        return NatalChart(
            birth_data=birth,
            placements=placements,
            aspects=aspects,
            ascendant_longitude=subject.ascendant.abs_pos,
            midheaven_longitude=subject.medium_coeli.abs_pos,
            zodiac_type="tropical",
            astrology_engine="kerykeion",
            astrology_engine_version=_engine_version(),
            chart_schema_version=CHART_SCHEMA_VERSION,
        )

    def calculate_transits(self, natal: NatalChart, instant: datetime) -> TransitSnapshot:
        natal_subject = _build_natal_subject(natal.birth_data)

        # Deviation from docs/old/IMPLEMENTATION_PLAN.md section 2.4's literal
        # description: Kerykeion 5.12.9's `AspectsFactory.dual_chart_aspects`
        # resolves its effective `active_points` as the intersection of the
        # requested list with *both* subjects' own `active_points`
        # (verified interactively - see kerykeion/aspects/aspects_factory.py
        # `find_common_active_points`). If the transiting subject is built
        # without Ascendant/Medium_Coeli in its own active_points (as the
        # plan originally suggested), natal Ascendant/Midheaven can never
        # survive that intersection as a target - `dual_chart_aspects`
        # silently returns zero axis aspects, confirmed empirically.
        #
        # So the transiting subject is built *with* Ascendant/Medium_Coeli
        # requested, using the placeholder lat/lng above. This computes a
        # meaningless "current Ascendant" for that placeholder location -
        # but that value is never converted into a domain object: any
        # `AspectModel` where the *transiting* side (`p1_name`) is an axis
        # is discarded below, before conversion. Only the ten real
        # transiting bodies ever appear as `TransitAspect.transiting_body`,
        # preserving the "no current-location astrology" invariant
        # (docs/old/DESIGN.md section 3.2) - enforced here by a filter immediately
        # after the library call, not by omission at construction time.
        transiting_active_points: list[AstrologicalPoint] = [
            *(cast(AstrologicalPoint, body) for body in TRANSIT_BODIES),
            "Ascendant",
            "Medium_Coeli",
        ]
        transiting_subject = AstrologicalSubjectFactory.from_iso_utc_time(
            name="transit",
            iso_utc_time=instant.astimezone(UTC).isoformat(),
            lat=_TRANSIT_PLACEHOLDER_LAT,
            lng=_TRANSIT_PLACEHOLDER_LNG,
            tz_str=_TRANSIT_PLACEHOLDER_TZ,
            online=False,
            zodiac_type="Tropical",
            active_points=transiting_active_points,
        )

        dual = AspectsFactory.dual_chart_aspects(
            transiting_subject,
            natal_subject,
            active_points=transiting_active_points,
            active_aspects=_ACTIVE_ASPECTS,
        )

        raw_aspects = [
            TransitAspect(
                transiting_body=a.p1_name,
                natal_target=_MIDHEAVEN if a.p2_name == _MEDIUM_COELI else a.p2_name,
                aspect=a.aspect,
                orb_degrees=a.orbit,
                movement=a.aspect_movement.lower(),
            )
            for a in dual.aspects
            if a.p1_name not in ("Ascendant", _MEDIUM_COELI)
        ]

        transiting_positions = [
            _to_placement(getattr(transiting_subject, body.lower()), include_house=False)
            for body in TRANSIT_BODIES
        ]

        return TransitSnapshot(
            instant_utc=instant,
            transiting_positions=transiting_positions,
            raw_aspects=raw_aspects,
            astrology_policy_version=POLICY_VERSION,
        )
