"""Deterministic significance ranking for already-policy-filtered transit
aspects (DESIGN.md section 9.5).

Input here has already passed `syzygy.astrology.policy.TransitAspectPolicy`
- this module never re-applies orb limits, it only scores and truncates.
The LLM only ever sees the output of `TransitRanker.rank`, never the full
snapshot and never a request to judge importance itself (AGENTS.md).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from syzygy.astrology.policy import TransitAspectPolicy
from syzygy.domain.astrology import RankedTransit, TransitAspect

#: Bump whenever the weights or formula below change.
RANKING_VERSION = "transit-ranking-v1"

#: How many top-scoring aspects `rank` returns at most (DESIGN.md 9.5).
TOP_N = 6

#: Named weights - see IMPLEMENTATION_PLAN.md section 2.5. Adjust only
#: with a documented reason, updated here.
ASPECT_WEIGHT: dict[str, float] = {
    "conjunction": 1.0,
    "opposition": 1.0,
    "square": 1.0,
    "trine": 0.85,
    "sextile": 0.7,
}

TRANSITING_BODY_WEIGHT: dict[str, float] = {
    "Sun": 1.0,
    "Moon": 1.0,
    "Mercury": 0.9,
    "Venus": 0.9,
    "Mars": 0.9,
    "Jupiter": 0.85,
    "Saturn": 0.85,
    "Uranus": 0.8,
    "Neptune": 0.8,
    "Pluto": 0.8,
}

#: Personal planets, for the natal-target side of the formula.
_PERSONAL_PLANETS = frozenset({"Mercury", "Venus", "Mars"})

NATAL_TARGET_WEIGHT_SUN_MOON_ASCENDANT = 1.0
NATAL_TARGET_WEIGHT_PERSONAL = 0.9
NATAL_TARGET_WEIGHT_OTHER = 0.8

APPLYING_MODIFIER = 1.1
NOT_APPLYING_MODIFIER = 1.0

#: `orb_closeness`'s denominator is the *effective* cap for this specific
#: aspect - `TransitAspectPolicy.max_orb_degrees`, not a flat per-aspect-
#: type table. This is deliberate: that method already narrows the base
#: table for a transiting Moon (1.5 degrees) or a natal-angle target (2.0
#: degrees), so a Moon aspect at a given absolute orb reads as much
#: "looser" (relative to its own tight allowance) than a slower body's
#: aspect at that same absolute orb. That relative reading, not the body
#: weight table alone, is what makes a slow-planet-to-personal-point
#: aspect able to outrank a same-orb Moon aspect - see
#: DESIGN.md section 9.5 ("Moon contacts should not crowd out every
#: slower transit") and `tests/astrology/test_ranking.py`.
_POLICY = TransitAspectPolicy()


def _natal_target_weight(natal_target: str) -> float:
    if natal_target in ("Sun", "Moon", "Ascendant"):
        return NATAL_TARGET_WEIGHT_SUN_MOON_ASCENDANT
    if natal_target in _PERSONAL_PLANETS:
        return NATAL_TARGET_WEIGHT_PERSONAL
    return NATAL_TARGET_WEIGHT_OTHER


def _score(aspect: TransitAspect) -> float:
    max_orb = _POLICY.max_orb_degrees(aspect)
    assert max_orb is not None  # input has already passed policy.filter
    orb_closeness = 1 - (aspect.orb_degrees / max_orb)
    applying_modifier = (
        APPLYING_MODIFIER if aspect.movement == "applying" else NOT_APPLYING_MODIFIER
    )
    return (
        ASPECT_WEIGHT[aspect.aspect]
        * orb_closeness
        * TRANSITING_BODY_WEIGHT[aspect.transiting_body]
        * _natal_target_weight(aspect.natal_target)
        * applying_modifier
    )


class TransitRanker(BaseModel):
    """Stateless aside from its version; constructed fresh per use."""

    model_config = ConfigDict(frozen=True)

    version: str = RANKING_VERSION

    def rank(self, aspects: list[TransitAspect]) -> list[RankedTransit]:
        """Score, sort, and truncate to the top `TOP_N`.

        Tie-break: tighter orb wins; if still tied, input order (a stable
        sort on the negative score alone already preserves input order
        for exact ties, but the explicit orb key documents the intent
        rather than leaving it to that incidental stability).
        """
        indexed = list(enumerate(aspects))
        indexed.sort(key=lambda pair: (-_score(pair[1]), pair[1].orb_degrees, pair[0]))
        top = indexed[:TOP_N]
        return [
            RankedTransit(aspect=aspect, score=_score(aspect), rank=rank)
            for rank, (_, aspect) in enumerate(top, start=1)
        ]
