"""Build the narrow, fully-resolved input surface for interpretation."""

from __future__ import annotations

from syzygy.domain.astrology import NatalPlacement, RankedTransit, sign_for_longitude
from syzygy.domain.interpretation import InterpretationContext
from syzygy.domain.knowledge import KnowledgeChunk
from syzygy.domain.profile import Profile
from syzygy.domain.tarot import TarotCard


def _find_placement(placements: list[NatalPlacement], body: str) -> NatalPlacement:
    for placement in placements:
        if placement.body == body:
            return placement
    raise ValueError(f"natal chart has no placement for {body!r}")


def build_context(
    profile: Profile,
    card: TarotCard,
    ranked_transits: list[RankedTransit],
    knowledge_chunks: list[KnowledgeChunk],
    consultation_local_timestamp: str,
    consultation_local_date: str,
    prompt_version: str,
) -> InterpretationContext:
    """Build an interpretation context from already-resolved domain objects.

    The builder deliberately accepts only the ranked transit subset and the
    caller's resolved knowledge chunks. It does not calculate, retrieve, or
    otherwise broaden either input.
    """
    natal_placements = profile.natal_chart.placements
    sun = _find_placement(natal_placements, "Sun")
    moon = _find_placement(natal_placements, "Moon")

    relevant: list[NatalPlacement] = []
    included_bodies: set[str] = set()

    def include(body: str) -> None:
        if body in included_bodies:
            return
        relevant.append(_find_placement(natal_placements, body))
        included_bodies.add(body)

    # The core context always gives the provider the luminaries and natal
    # Ascendant, then adds any natal bodies or angles directly touched by the
    # already-ranked transit list.
    for body in ("Sun", "Moon", "Ascendant"):
        include(body)
    for ranked in ranked_transits:
        include(ranked.aspect.natal_target)

    astrology = card.astrology
    if astrology is not None:
        if astrology.type == "planet":
            if astrology.planet is None:
                raise ValueError(f"planet-attributed card {card.id!r} has no planet")
            include(astrology.planet)
        elif astrology.type == "sign":
            if astrology.sign is None:
                raise ValueError(f"sign-attributed card {card.id!r} has no sign")
            for placement in natal_placements:
                if placement.sign == astrology.sign:
                    include(placement.body)
        elif astrology.type == "decan":
            if astrology.planet is None or astrology.decan is None:
                raise ValueError(
                    f"decan-attributed card {card.id!r} has no planet/sign pairing"
                )
            # The card itself carries the fixed planet/sign pairing. Including
            # the decan's ruling planet placement mirrors the planet case and
            # gives that pairing a concrete natal anchor for interpretation.
            include(astrology.planet)

    return InterpretationContext(
        profile_display_name=profile.display_name,
        consultation_local_date=consultation_local_date,
        consultation_local_timestamp=consultation_local_timestamp,
        card=card,
        significant_transits=ranked_transits,
        relevant_natal_placements=relevant,
        sun_placement=sun,
        moon_placement=moon,
        ascendant_sign=sign_for_longitude(profile.natal_chart.ascendant_longitude),
        knowledge_chunks=knowledge_chunks,
        prompt_version=prompt_version,
    )
