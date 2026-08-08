"""Syzygy-owned transit aspect policy: which raw aspects are even
candidates for interpretation.

This is deliberately narrower than what an astrology library will offer by
default. DESIGN.md section 9.4 states the point plainly: "the point is not
to claim a uniquely correct astrological doctrine. The point is to avoid
flooding the model with weak aspects." The LLM never sees this decision
being made - it only ever receives the already-filtered result.

This module filters. `syzygy.astrology.ranking` (Milestone 2, not yet
implemented) scores and selects the top few from what this module lets
through. Keep the two separate: a wide-orb trine and a hair-tight sextile
should both be able to pass the filter, and it's ranking's job - not this
module's - to decide which one matters more for a given day.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from syzygy.domain.astrology import MAJOR_ASPECTS, TransitAspect

#: Bump this whenever the orb table or filtering rules below change.
#: Stored on every `TransitSnapshot` (`astrology_policy_version`) so old
#: readings remain interpretable as historical artifacts even after the
#: policy evolves (DESIGN.md section 24, section 9.4).
POLICY_VERSION = "transit-policy-v1"

#: Maximum orb, in degrees, for each major aspect (DESIGN.md section 9.4).
#: No entry here means the aspect type is never a candidate at all -
#: v0.1 uses only the five major aspects; quintiles and other minor
#: aspects are excluded entirely, not merely orb-limited.
DEFAULT_MAX_ORB_DEGREES: dict[str, float] = {
    "conjunction": 3.0,
    "opposition": 3.0,
    "square": 3.0,
    "trine": 3.0,
    "sextile": 2.0,
}

#: Tighter cap applied when the natal target is the Ascendant or
#: Midheaven, regardless of aspect type (DESIGN.md section 9.4).
NATAL_ANGLE_MAX_ORB_DEGREES = 2.0
NATAL_ANGLE_TARGETS = frozenset({"Ascendant", "Midheaven"})

#: Tighter cap applied when the transiting body is the Moon, regardless
#: of aspect type or target (DESIGN.md section 9.4). The Moon moves fast
#: enough that a wide-orb lunar aspect is barely meaningful for a single
#: day's reading.
TRANSITING_MOON_MAX_ORB_DEGREES = 1.5


class AspectOrbRule(BaseModel):
    """One resolved orb limit, for inspection/debugging (e.g. `syzygy
    dev astrology`). Not used internally by `TransitAspectPolicy.filter` -
    that method applies the module-level constants directly so the rule
    precedence (angle cap and Moon cap both override the base table) stays
    in one place instead of being re-derived by every caller.
    """

    model_config = ConfigDict(frozen=True)

    aspect: str
    max_orb_degrees: float
    reason: str


class TransitAspectPolicy(BaseModel):
    """Syzygy's orb-filtering policy. Stateless aside from its version;
    constructed fresh per use rather than held as global mutable state.
    """

    model_config = ConfigDict(frozen=True)

    version: str = POLICY_VERSION

    def max_orb_degrees(self, aspect: TransitAspect) -> float | None:
        """Resolve the effective orb cap for one raw aspect, or `None` if
        the aspect type is not a candidate at all (e.g. a quintile).
        Precedence: natal-angle cap and transiting-Moon cap both narrow
        the base per-aspect-type table; if both apply, the tighter (Moon)
        cap wins.
        """
        if aspect.aspect not in MAJOR_ASPECTS:
            return None
        cap = DEFAULT_MAX_ORB_DEGREES[aspect.aspect]
        if aspect.natal_target in NATAL_ANGLE_TARGETS:
            cap = min(cap, NATAL_ANGLE_MAX_ORB_DEGREES)
        if aspect.transiting_body == "Moon":
            cap = min(cap, TRANSITING_MOON_MAX_ORB_DEGREES)
        return cap

    def passes(self, aspect: TransitAspect) -> bool:
        cap = self.max_orb_degrees(aspect)
        return cap is not None and aspect.orb_degrees <= cap

    def filter(self, aspects: list[TransitAspect]) -> list[TransitAspect]:
        """Return only the aspects that survive orb filtering. Order is
        preserved; this method never ranks or truncates - see
        `syzygy.astrology.ranking.TransitRanker` for that.
        """
        return [a for a in aspects if self.passes(a)]
