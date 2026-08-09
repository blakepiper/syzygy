"""Fixed evaluation inputs (M16.3b).

Every case is committed, deterministic, and free of copyrighted text. The
"source passages" below are **invented for evaluation** - they are not
from the Book of Thoth or either companion, and they are deliberately
written to contain a checkable proper noun so a scorer can tell whether
the model used the passage it was given or something it remembered. Real
book text is never committed (`AGENTS.md`, ADR 0003).

The seven cases exist because they fail differently:

    reading_with_sources     the normal daily reading, grounded
    reading_without_sources  the same reading with no passages at all -
                             the citations-only install, and the case where
                             a model is most tempted to invent grounding
    reading_court_card       a court card, whose decan spans are the
                             Thoth-specific trap in `AGENTS.md`
    natal_summary            a different schema and a different voice
    cosmos_summary           the third schema
    register_separation      a reading whose transits pull in opposite
                             directions, so a model that writes the same
                             paragraph twice is visible
    repair_provocation       a long, awkward context that historically
                             produces a first reply needing the repair turn
"""

from __future__ import annotations

from dataclasses import dataclass

from syzygy.domain.astrology import NatalPlacement, RankedTransit, TransitAspect
from syzygy.domain.interpretation import InterpretationContext, InterpretationKind
from syzygy.domain.knowledge import KnowledgeChunk
from syzygy.interpretation.prompts import (
    COSMOS_SUMMARY_PROMPT_VERSION,
    NATAL_SUMMARY_PROMPT_VERSION,
    PROMPT_VERSION,
)
from syzygy.sortes.deck import load_deck


@dataclass(frozen=True)
class EvaluationCase:
    """One fixture, plus what a correct answer must contain."""

    id: str
    context: InterpretationContext
    #: Facts Syzygy supplied that a faithful answer must not contradict.
    #: Checked case-insensitively as substrings; a missing one is a
    #: fidelity failure, not a style preference.
    required_mentions: tuple[str, ...]
    #: Strings whose presence is a failure: a card that was not drawn, a
    #: template control token, a chain-of-thought marker.
    forbidden: tuple[str, ...] = (
        "<think>",
        "</think>",
        "<|im_start|>",
        "<|im_end|>",
        "as an ai",
    )
    notes: str = ""


def _card(card_id: str):
    for card in load_deck():
        if card.id == card_id:
            return card
    raise LookupError(card_id)


_SUN = NatalPlacement(body="Sun", sign="Virgo", longitude=164.37, house=10)
_MOON = NatalPlacement(body="Moon", sign="Pisces", longitude=338.18, house=4)
_SATURN = NatalPlacement(body="Saturn", sign="Capricorn", longitude=280.61, house=2)
_VENUS = NatalPlacement(body="Venus", sign="Libra", longitude=190.55, house=11)


def _transit(
    body: str, target: str, aspect: str, orb: float, movement: str, rank: int, score: float
):
    return RankedTransit(
        aspect=TransitAspect(
            transiting_body=body,
            natal_target=target,
            aspect=aspect,
            orb_degrees=orb,
            movement=movement,
        ),
        score=score,
        rank=rank,
    )


#: Invented passages. The proper nouns ("Ashgrove", "the Ninth Gate") do
#: not appear in any real source, so a model that repeats them demonstrably
#: used what it was given rather than what it memorised.
_SYNTHETIC_CHUNKS = [
    KnowledgeChunk(
        id="eval-chunk-1",
        source_id="evaluation-fixture",
        section_id="eval-section",
        section_type="card",
        card_id="the_fool",
        title="Evaluation fixture, not a real source",
        chunk_index=0,
        text=(
            "In the Ashgrove commentary the Fool is read as the moment before "
            "commitment, when the shape of a thing is still negotiable. Its "
            "danger is not recklessness but deferral."
        ),
        page_start=1,
        page_end=1,
        text_hash="eval1",
    ),
    KnowledgeChunk(
        id="eval-chunk-2",
        source_id="evaluation-fixture",
        section_id="eval-section",
        section_type="card",
        card_id="the_fool",
        title="Evaluation fixture, not a real source",
        chunk_index=1,
        text=(
            "The Ninth Gate reading of this card places it against Saturn: what "
            "is begun freely must later be maintained deliberately."
        ),
        page_start=2,
        page_end=2,
        text_hash="eval2",
    ),
]


def _context(
    *,
    kind: InterpretationKind,
    prompt_version: str,
    card=None,
    transits=None,
    chunks=None,
    name: str = "Evaluation",
) -> InterpretationContext:
    return InterpretationContext(
        kind=kind,
        card=card,
        prompt_version=prompt_version,
        profile_display_name=name,
        consultation_local_date="2026-03-14",
        consultation_local_timestamp="2026-03-14T08:15:00",
        significant_transits=list(transits or []),
        relevant_natal_placements=[_SUN, _MOON, _SATURN, _VENUS],
        sun_placement=_SUN,
        moon_placement=_MOON,
        ascendant_sign="Scorpio",
        knowledge_chunks=list(chunks or []),
    )


def evaluation_cases() -> tuple[EvaluationCase, ...]:
    saturn_venus = _transit("Saturn", "Venus", "square", 0.8, "applying", 1, 9.5)
    mars_sun = _transit("Mars", "Sun", "trine", 1.2, "separating", 2, 6.0)
    jupiter_moon = _transit("Jupiter", "Moon", "opposition", 2.1, "applying", 3, 5.2)

    return (
        EvaluationCase(
            id="reading_with_sources",
            context=_context(
                kind=InterpretationKind.DAILY_READING,
                prompt_version=PROMPT_VERSION,
                card=_card("the_fool"),
                transits=[saturn_venus, mars_sun],
                chunks=_SYNTHETIC_CHUNKS,
            ),
            required_mentions=("fool", "saturn", "venus"),
            notes="Grounded reading. Scorer checks whether the supplied passages were used.",
        ),
        EvaluationCase(
            id="reading_without_sources",
            context=_context(
                kind=InterpretationKind.DAILY_READING,
                prompt_version=PROMPT_VERSION,
                card=_card("the_fool"),
                transits=[saturn_venus, mars_sun],
            ),
            required_mentions=("fool", "saturn"),
            forbidden=(
                "<think>",
                "</think>",
                "<|im_start|>",
                "<|im_end|>",
                "as an ai",
                # With no passages supplied, any claim of textual authority
                # is fabrication - this is the M16.3c "does not invent
                # grounding" gate.
                "crowley writes",
                "the book of thoth says",
                "according to the text",
            ),
            notes="Empty retrieval. The install everyone gets ships citations only.",
        ),
        EvaluationCase(
            id="reading_court_card",
            context=_context(
                kind=InterpretationKind.DAILY_READING,
                prompt_version=PROMPT_VERSION,
                card=_card("knight_of_swords"),
                transits=[mars_sun, jupiter_moon],
            ),
            required_mentions=("knight", "swords"),
            notes="Court card: the decan-span trap in AGENTS.md.",
        ),
        EvaluationCase(
            id="natal_summary",
            context=_context(
                kind=InterpretationKind.NATAL_SUMMARY,
                prompt_version=NATAL_SUMMARY_PROMPT_VERSION,
            ),
            required_mentions=("virgo", "pisces"),
        ),
        EvaluationCase(
            id="cosmos_summary",
            context=_context(
                kind=InterpretationKind.COSMOS_SUMMARY,
                prompt_version=COSMOS_SUMMARY_PROMPT_VERSION,
                transits=[saturn_venus, mars_sun, jupiter_moon],
            ),
            required_mentions=("saturn",),
        ),
        EvaluationCase(
            id="register_separation",
            context=_context(
                kind=InterpretationKind.DAILY_READING,
                prompt_version=PROMPT_VERSION,
                card=_card("the_tower"),
                transits=[saturn_venus, jupiter_moon],
                chunks=_SYNTHETIC_CHUNKS[:1],
            ),
            required_mentions=("tower",),
            notes=(
                "Contradictory transits. Scored on whether the esoteric and "
                "conventional registers say genuinely different things."
            ),
        ),
        EvaluationCase(
            id="repair_provocation",
            context=_context(
                kind=InterpretationKind.DAILY_READING,
                prompt_version=PROMPT_VERSION,
                card=_card("the_hermit"),
                transits=[saturn_venus, mars_sun, jupiter_moon],
                chunks=_SYNTHETIC_CHUNKS * 3,
                name="A Name With Punctuation: \"Quoted\", and a {brace}",
            ),
            required_mentions=("hermit",),
            notes="Long, awkward context. Exercises the repair turn.",
        ),
    )
