"""Build the narrow, fully-resolved input surface for interpretation."""

from __future__ import annotations

from syzygy.domain.astrology import NatalPlacement, RankedTransit, sign_for_longitude
from syzygy.domain.iching import IChingCast
from syzygy.domain.interpretation import InterpretationContext, InterpretationKind
from syzygy.domain.knowledge import KnowledgeChunk
from syzygy.domain.profile import Profile
from syzygy.domain.tarot import TarotCard

#: Natal angles are targets a transit can hit, but they are not bodies and
#: a `NatalChart` carries no `NatalPlacement` for either of them - the
#: astrology engine stores them as `ascendant_longitude`/
#: `midheaven_longitude` instead. The Ascendant still reaches the model, as
#: `InterpretationContext.ascendant_sign`; a transit to either angle
#: reaches it by naming the angle in the transit line.
_NATAL_ANGLES = ("Ascendant", "Midheaven")


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
        if body in included_bodies or body in _NATAL_ANGLES:
            return
        relevant.append(_find_placement(natal_placements, body))
        included_bodies.add(body)

    # The core context always gives the provider the luminaries (the natal
    # Ascendant travels as `ascendant_sign`), then adds any natal body
    # directly touched by the already-ranked transit list.
    for body in ("Sun", "Moon"):
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
        kind=InterpretationKind.DAILY_READING,
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


def build_oracle_context(
    profile: Profile,
    card: TarotCard,
    ranked_transits: list[RankedTransit],
    knowledge_chunks: list[KnowledgeChunk],
    consultation_local_timestamp: str,
    consultation_local_date: str,
    prompt_version: str,
    question: str,
) -> InterpretationContext:
    """Build the Oracle through the same narrow card-context surface."""
    daily = build_context(
        profile,
        card,
        ranked_transits,
        knowledge_chunks,
        consultation_local_timestamp,
        consultation_local_date,
        prompt_version,
    )
    payload = daily.model_dump()
    payload.update(kind=InterpretationKind.ORACLE, question=question)
    return InterpretationContext.model_validate(payload)


def build_iching_context(
    profile: Profile,
    cast: IChingCast,
    ranked_transits: list[RankedTransit],
    consultation_local_timestamp: str,
    consultation_local_date: str,
    prompt_version: str,
    question: str,
) -> InterpretationContext:
    """Build an I Ching context from a committed cast and ranked sky."""
    from syzygy.iching.book import get_hexagram

    placements = profile.natal_chart.placements
    relevant_bodies = {"Sun", "Moon"}
    relevant_bodies.update(
        transit.aspect.natal_target
        for transit in ranked_transits
        if transit.aspect.natal_target not in _NATAL_ANGLES
    )
    return InterpretationContext(
        kind=InterpretationKind.I_CHING,
        profile_display_name=profile.display_name,
        consultation_local_date=consultation_local_date,
        consultation_local_timestamp=consultation_local_timestamp,
        iching_cast=cast,
        primary_hexagram=get_hexagram(cast.primary_hexagram_number),
        resulting_hexagram=get_hexagram(cast.resulting_hexagram_number),
        significant_transits=ranked_transits,
        relevant_natal_placements=[p for p in placements if p.body in relevant_bodies],
        sun_placement=_find_placement(placements, "Sun"),
        moon_placement=_find_placement(placements, "Moon"),
        ascendant_sign=sign_for_longitude(profile.natal_chart.ascendant_longitude),
        knowledge_chunks=[],
        prompt_version=prompt_version,
        question=question,
    )


def build_natal_summary_context(
    profile: Profile,
    consultation_local_timestamp: str,
    consultation_local_date: str,
    prompt_version: str,
) -> InterpretationContext:
    """Build the immutable, provider-ready natal chart summary input."""
    placements = profile.natal_chart.placements
    return InterpretationContext(
        kind=InterpretationKind.NATAL_SUMMARY,
        profile_display_name=profile.display_name,
        consultation_local_date=consultation_local_date,
        consultation_local_timestamp=consultation_local_timestamp,
        significant_transits=[],
        relevant_natal_placements=list(placements),
        sun_placement=_find_placement(placements, "Sun"),
        moon_placement=_find_placement(placements, "Moon"),
        ascendant_sign=sign_for_longitude(profile.natal_chart.ascendant_longitude),
        knowledge_chunks=[],
        prompt_version=prompt_version,
    )


def build_cosmos_summary_context(
    profile: Profile,
    ranked_transits: list[RankedTransit],
    consultation_local_timestamp: str,
    consultation_local_date: str,
    prompt_version: str,
) -> InterpretationContext:
    """Build today's already-ranked sky summary input without a card."""
    placements = profile.natal_chart.placements
    relevant_bodies = {"Sun", "Moon"}
    relevant_bodies.update(
        transit.aspect.natal_target
        for transit in ranked_transits
        if transit.aspect.natal_target not in _NATAL_ANGLES
    )
    relevant = [p for p in placements if p.body in relevant_bodies]
    return InterpretationContext(
        kind=InterpretationKind.COSMOS_SUMMARY,
        profile_display_name=profile.display_name,
        consultation_local_date=consultation_local_date,
        consultation_local_timestamp=consultation_local_timestamp,
        significant_transits=ranked_transits,
        relevant_natal_placements=relevant,
        sun_placement=_find_placement(placements, "Sun"),
        moon_placement=_find_placement(placements, "Moon"),
        ascendant_sign=sign_for_longitude(profile.natal_chart.ascendant_longitude),
        knowledge_chunks=[],
        prompt_version=prompt_version,
    )
