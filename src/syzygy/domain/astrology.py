"""Astrology domain models: Self (natal) and Cosmos (transits).

These are Syzygy-owned shapes. Nothing here may be a Kerykeion type -
`syzygy.astrology.kerykeion_backend` is responsible for converting
Kerykeion's own models into these before anything else in the app sees
them (ARCHITECTURE_HANDOFF.md section 12).

v0.1 scope reminders encoded by what is (and isn't) here:
- geocentric, tropical, Placidus by default (DESIGN.md section 9.2);
- no relocated houses, no current Ascendant/MC, no current-location data
  anywhere in `TransitSnapshot` (DESIGN.md section 3.2) - there is no
  latitude/longitude field on anything in this module except `BirthData`.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# The ten bodies used for transit analysis (DESIGN.md section 9.3). Natal
# charts may additionally carry Ascendant/Midheaven placements.
TRANSIT_BODIES: tuple[str, ...] = (
    "Sun", "Moon", "Mercury", "Venus", "Mars",
    "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto",
)

MAJOR_ASPECTS: tuple[str, ...] = (
    "conjunction", "opposition", "square", "trine", "sextile",
)

#: The twelve tropical zodiac signs, in order, each spanning 30 degrees of
#: absolute ecliptic longitude starting at 0 (Aries).
ZODIAC_SIGNS: tuple[str, ...] = (
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
)


def sign_for_longitude(longitude: float) -> str:
    """The tropical sign containing an absolute ecliptic longitude.

    Pure degree arithmetic, independent of any astrology engine - safe to
    use on `NatalChart.ascendant_longitude`/`midheaven_longitude`, which
    (unlike `NatalPlacement`) store longitude without an accompanying
    `sign` field.
    """
    return ZODIAC_SIGNS[int(longitude // 30) % 12]


class BirthData(BaseModel):
    """Exact birth facts required to calculate a natal chart.

    Saved on the profile permanently (DESIGN.md section 3.1) so a chart
    is never silently recalculated from different inputs later.
    """

    model_config = ConfigDict(frozen=True)

    local_date: str  # ISO date, e.g. "1990-08-07"
    local_time: str  # ISO time, e.g. "14:22:00"
    place_label: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timezone: str  # IANA zone, e.g. "America/New_York"
    house_system: str = "placidus"


class NatalPlacement(BaseModel):
    model_config = ConfigDict(frozen=True)

    body: str
    sign: str
    longitude: float = Field(ge=0, lt=360)
    house: int | None = Field(default=None, ge=1, le=12)
    retrograde: bool = False


class NatalAspect(BaseModel):
    model_config = ConfigDict(frozen=True)

    body_a: str
    body_b: str
    aspect: str
    orb_degrees: float


class NatalChart(BaseModel):
    """A profile's saved, versioned natal chart. Calculated once."""

    model_config = ConfigDict(frozen=True)

    birth_data: BirthData
    placements: list[NatalPlacement]
    aspects: list[NatalAspect]
    ascendant_longitude: float = Field(ge=0, lt=360)
    midheaven_longitude: float = Field(ge=0, lt=360)
    zodiac_type: str = "tropical"
    astrology_engine: str
    astrology_engine_version: str
    chart_schema_version: str


class TransitAspect(BaseModel):
    """One raw transiting-body-to-natal-target aspect, already filtered by
    `syzygy.astrology.policy.TransitAspectPolicy` but not yet ranked.
    """

    model_config = ConfigDict(frozen=True)

    transiting_body: str
    natal_target: str  # a body name, or "Ascendant" / "Midheaven"
    aspect: str
    orb_degrees: float
    movement: str  # "applying" | "separating" | "static"


class RankedTransit(BaseModel):
    """A `TransitAspect` plus its deterministic significance score.

    Produced by `syzygy.astrology.ranking.TransitRanker`. The top few of
    these (not the raw snapshot) are what the interpretation context
    builder is allowed to use as "significant transits".
    """

    model_config = ConfigDict(frozen=True)

    aspect: TransitAspect
    score: float
    rank: int = Field(ge=1)


class TransitSnapshot(BaseModel):
    """The complete geocentric transit picture at one instant, evaluated
    against one natal chart. Always saved in full on the reading, even
    though only a ranked subset is sent to the LLM (DESIGN.md section 9.5).
    """

    model_config = ConfigDict(frozen=True)

    instant_utc: datetime
    transiting_positions: list[NatalPlacement]
    raw_aspects: list[TransitAspect]
    astrology_policy_version: str
