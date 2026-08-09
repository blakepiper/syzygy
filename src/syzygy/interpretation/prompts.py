"""The versioned prompt contract shared by every real provider.

Everything a model is told - the rules from DESIGN.md section 13.5, the
rendering of an `InterpretationContext` into text, the required output
shape, and the repair instruction used for the single retry of
DESIGN.md section 13.4 - lives in this module and nowhere else. Provider
adapters (`syzygy.interpretation.providers`) are transport only: they take
these strings, send them over their SDK or HTTP endpoint, and validate the
response into `InterpretationResult`. A provider that builds prompt text
of its own has broken the boundary (AGENTS.md).

`PROMPT_VERSION` is recorded on every `Reading` (and shown in the TUI's
INPUTS view) so a stored reading can always be traced back to the exact
instructions that produced it. Bump it whenever `SYSTEM_PROMPT`, the
rendering below, or the output contract changes in a way that would make
two readings incomparable - never edit them silently in place.
"""

from __future__ import annotations

from typing import Any, Final

from syzygy.domain.astrology import NatalPlacement, RankedTransit
from syzygy.domain.interpretation import (
    InterpretationContext,
    InterpretationKind,
    InterpretationResult,
    SummaryResult,
)
from syzygy.domain.knowledge import KnowledgeChunk
from syzygy.domain.tarot import TarotCard

PROMPT_VERSION: Final = "daily-v1"
NATAL_SUMMARY_PROMPT_VERSION: Final = "natal-summary-v1"
COSMOS_SUMMARY_PROMPT_VERSION: Final = "cosmos-summary-v1"

#: Fields of `InterpretationResult` that Syzygy fills in itself. The model
#: is never asked for them - it cannot know which provider is running it,
#: and letting it claim otherwise would corrupt a reading's provenance.
PROVENANCE_FIELDS: Final = ("provider_id", "model_id", "prompt_version")

SYSTEM_PROMPT: Final = """\
You are the interpretive voice of Syzygy, a daily divination instrument. A \
reading has already happened: a natal chart was calculated, today's transits \
were ranked, and one upright Crowley-Harris Thoth card was drawn at random. \
All of it is fixed. Your only task is to interpret what you are given.

FACTS AND INVENTION
- Interpret only the astrological facts supplied in the reading below.
- Never invent, adjust, or "correct" a placement, aspect, orb, house, sign, \
or card correspondence. If a fact is not listed, it is not available to you: \
say less rather than filling the gap.
- The card was drawn by the instrument, not chosen by you or by the querent. \
Do not suggest a different card would fit better, and do not imply the draw \
was steered.
- You may name symbolic resonance between the card and the sky. You may not \
reshape the inputs to produce a better resonance.

SOURCE MATERIAL
- Crowley's Book of Thoth is the principal reference for the card. Where \
source passages are supplied, treat them as authoritative over your own \
recollection of Thoth symbolism, and prefer them to other tarot traditions.
- Paraphrase. Do not reproduce long passages of the source text; a short \
quoted phrase is acceptable, a quoted paragraph is not.
- If no source passages are supplied, interpret from the card's canonical \
correspondences below and say nothing that implies you consulted a text.
- List in source_chunk_ids only the ids of passages you actually drew on, \
and only ids that appear in the reading below.

STANCE
- Distinguish observation from interpretation. A transit's existence is an \
observation; what it means today is interpretation, and should read as such.
- This is divination, not prediction. Do not present anything as a certain \
future event, and do not date-stamp outcomes.
- Make no medical, legal, financial, or safety-critical claims or \
predictions, and do not advise on them obliquely either.
- Syzygy borrows the image of turning a wheel; you hold no Buddhist \
doctrinal authority and must not speak as though you do. The same restraint \
applies to Thelemic and Hermetic material: present it as tradition, not as \
revealed fact about the querent.
- Avoid generic positivity. If the alignment reads as friction, delay, \
uncertainty, intensity, or restraint, say so plainly. Do not convert every \
card into encouragement, and do not soften a hard card into a lesson.
- Address the querent by their display name at most once, and never invent \
biographical detail about them.

THE TWO REGISTERS
- esoteric: for an interested reader who already knows the vocabulary. \
Thoth symbolism, the card's astrological correspondence, its relation to \
today's ranked transits and to the natal placements supplied. Do not \
explain basic occult terms from first principles.
- conventional: the same alignment in ordinary language, with no occult \
vocabulary and no astrological jargon - a reader who does not know what a \
square is must still get the whole meaning.
- The two registers must describe the same day. They may differ in \
vocabulary and emphasis; they may not reach different conclusions.

LENGTH
This is a daily ritual, not an essay.
- alignment_title: at most 8 words, no punctuation at the end.
- esoteric.summary and conventional.summary: one or two sentences each.
- esoteric.body: 2-4 short paragraphs.
- conventional.body: 2-4 short paragraphs.
- conventional.watch_for: 2-4 concrete, specific items, one line each.
- conventional.reflection: exactly one question the querent could sit with.

OUTPUT
Reply with a single JSON object and nothing else - no preamble, no markdown \
fence, no commentary after it. Use exactly this shape:

{
  "alignment_title": "string",
  "esoteric": {"summary": "string", "body": "string"},
  "conventional": {
    "summary": "string",
    "body": "string",
    "watch_for": ["string"],
    "reflection": "string"
  },
  "source_chunk_ids": ["string"]
}
"""

REPAIR_INSTRUCTION: Final = """\
Your previous reply could not be parsed into the required JSON object.

Reply again with the corrected reading as a single JSON object and nothing \
else: no preamble, no markdown fence, no commentary. Keep the same \
interpretation - fix only the structure. Do not add fields that are not in \
the required shape.\
"""


def _response_json_schema() -> dict[str, Any]:
    """The model-facing JSON schema, derived from `InterpretationResult`.

    Derived rather than hand-written so the schema a provider constrains
    its model with cannot drift from the schema that validates the reply.
    The provenance fields are stripped (see `PROVENANCE_FIELDS`), and
    `source_chunk_ids` is promoted to required - it defaults to empty on
    the domain model, but a model that silently omits it leaves us unable
    to tell "cited nothing" from "forgot the field".
    """
    schema = InterpretationResult.model_json_schema()
    for field in PROVENANCE_FIELDS:
        schema["properties"].pop(field, None)
    required = [name for name in schema.get("required", []) if name not in PROVENANCE_FIELDS]
    if "source_chunk_ids" not in required:
        required.append("source_chunk_ids")
    schema["required"] = required
    schema["title"] = "SyzygyDailyReading"
    schema["additionalProperties"] = False
    return schema


#: For providers whose API can constrain output to a schema (JSON schema
#: mode, tool calling, a llama.cpp grammar). Providers that need a stricter
#: dialect - OpenAI's `strict` mode, say - may tighten a copy of this;
#: they must not loosen the field set.
RESPONSE_JSON_SCHEMA: Final[dict[str, Any]] = _response_json_schema()


def _summary_response_json_schema() -> dict[str, Any]:
    schema = SummaryResult.model_json_schema()
    for field in PROVENANCE_FIELDS:
        schema["properties"].pop(field, None)
    schema["required"] = [
        name for name in schema.get("required", []) if name not in PROVENANCE_FIELDS
    ]
    schema["title"] = "SyzygySummary"
    schema["additionalProperties"] = False
    return schema


SUMMARY_RESPONSE_JSON_SCHEMA: Final[dict[str, Any]] = _summary_response_json_schema()

SUMMARY_SYSTEM_PROMPT: Final = """\
You are the interpretive voice of Syzygy. The astrological facts supplied by
the instrument are fixed and already calculated. Summarize only those facts;
never calculate, add, correct, rank, or omit an aspect to improve the story.
Use astrology as reflective language, not certain prediction. Make no medical,
legal, financial, or safety-critical claims. Do not invent biography. Write
plain, precise prose that acknowledges friction and uncertainty where present.

Reply with one JSON object and nothing else, exactly:
{"headline": "at most 8 words", "body": "2-4 short paragraphs"}
"""


def _format_degrees(longitude: float) -> str:
    """Position within its sign, as degrees and arcminutes: `14°22'`."""
    within_sign = longitude % 30
    degrees = int(within_sign)
    minutes = int(round((within_sign - degrees) * 60))
    if minutes == 60:  # rounding carried into the next degree
        degrees, minutes = degrees + 1, 0
    return f"{degrees}°{minutes:02d}'"


def _format_placement(placement: NatalPlacement) -> str:
    parts = [f"{placement.body}: {_format_degrees(placement.longitude)} {placement.sign}"]
    if placement.house is not None:
        parts.append(f"house {placement.house}")
    if placement.retrograde:
        parts.append("retrograde")
    return ", ".join(parts)


def _format_transit(ranked: RankedTransit) -> str:
    aspect = ranked.aspect
    return (
        f"#{ranked.rank} transiting {aspect.transiting_body} {aspect.aspect} "
        f"natal {aspect.natal_target}, orb {aspect.orb_degrees:.2f}°, {aspect.movement}"
    )


def _format_correspondence(card: TarotCard) -> str:
    """The card's astrological attribution, in words.

    Returns the Princesses' explicit lack of attribution rather than an
    empty string: the model must be told the absence is canonical, not a
    gap in the context it should fill from memory.
    """
    astrology = card.astrology
    if astrology is None:
        return "no zodiacal attribution (canonical for this card - do not supply one)"
    if astrology.type == "element":
        return f"element {card.element}"
    if astrology.type == "planet":
        return f"planet {astrology.planet}"
    if astrology.type == "sign":
        return f"sign {astrology.sign}"
    if astrology.type == "decan" and astrology.decan is not None:
        decan = astrology.decan
        return (
            f"{astrology.planet} in {astrology.sign} "
            f"(decan {decan.index}: {decan.start_degree}°-{decan.end_degree}° {decan.sign})"
        )
    if astrology.type == "court_decan_span" and astrology.court_span is not None:
        span = astrology.court_span
        return (
            f"{span.start_degree}° {span.start_sign} - "
            f"{span.end_degree}° {span.end_sign}"
        )
    return astrology.type


def _card_lines(card: TarotCard) -> list[str]:
    lines = [
        f"  {card.full_name} [{card.id}]",
        f"  arcana: {card.arcana}",
        f"  correspondence: {_format_correspondence(card)}",
    ]
    if card.suit is not None:
        suit = f"  suit: {card.suit}"
        if card.rank is not None:
            suit += f", rank {card.rank}"
        if card.court is not None:
            suit += f", court rank {card.court}"
        lines.append(suit)
    if card.element is not None:
        element = f"  element: {card.element}"
        if card.sub_element is not None:
            element += f" of {card.sub_element}"
        lines.append(element)
    if card.hebrew_letter is not None:
        letter = f"  Hebrew letter: {card.hebrew_letter}"
        if card.hebrew_letter_type is not None:
            letter += f" ({card.hebrew_letter_type})"
        lines.append(letter)
    if card.tetragrammaton_letter is not None:
        lines.append(f"  Tetragrammaton letter: {card.tetragrammaton_letter}")
    if card.qabalah.sephira is not None:
        lines.append(f"  Qabalah: {card.qabalah.sephira}")
    if card.qabalah.path_number is not None:
        lines.append(f"  Qabalah: path {card.qabalah.path_number}")
    return lines


def _chunk_lines(chunk: KnowledgeChunk) -> list[str]:
    return [
        f"  [{chunk.id}] {chunk.title} (pages {chunk.page_start}-{chunk.page_end})",
        *(f"    {line}" for line in chunk.text.splitlines()),
    ]


def build_user_prompt(context: InterpretationContext) -> str:
    """Render an `InterpretationContext` as the model-facing reading.

    Deterministic: the same context renders to the same string, so a
    stored reading can be reproduced exactly. Everything rendered here
    comes off the context - this function must never read the database,
    the profile, or the astrology engine to enrich what it was handed.
    """
    if context.kind is not InterpretationKind.DAILY_READING or context.card is None:
        raise ValueError("build_user_prompt requires a daily-reading context with a card")
    lines: list[str] = [
        "CONSULTATION",
        f"  querent: {context.profile_display_name}",
        f"  local date: {context.consultation_local_date}",
        f"  local timestamp: {context.consultation_local_timestamp}",
        "",
        "CARD DRAWN (fixed by the instrument, upright)",
        *_card_lines(context.card),
        "",
        "NATAL ANCHORS",
        f"  {_format_placement(context.sun_placement)}",
        f"  {_format_placement(context.moon_placement)}",
        f"  Ascendant sign: {context.ascendant_sign}",
        "",
        "FURTHER NATAL PLACEMENTS RELEVANT TO THIS READING",
    ]
    # The luminaries are always in `relevant_natal_placements` too; they are
    # rendered once, as anchors, rather than repeated verbatim here.
    further = [
        placement
        for placement in context.relevant_natal_placements
        if placement.body not in ("Sun", "Moon")
    ]
    if further:
        lines.extend(f"  {_format_placement(placement)}" for placement in further)
    else:
        lines.append("  none beyond the anchors above")

    lines.extend(["", "SIGNIFICANT TRANSITS TODAY (already filtered and ranked by Syzygy)"])
    if context.significant_transits:
        lines.extend(f"  {_format_transit(t)}" for t in context.significant_transits)
    else:
        # Said explicitly, so the model reads it as a quiet sky rather than
        # as missing data it should reconstruct.
        lines.append("  none within orb today - the sky is quiet against this chart")

    lines.extend(["", "SOURCE PASSAGES"])
    if context.knowledge_chunks:
        for chunk in context.knowledge_chunks:
            lines.extend(_chunk_lines(chunk))
    else:
        lines.append("  none supplied - do not imply you consulted a source text")

    lines.extend(
        [
            "",
            "Interpret this alignment for today, following the rules you were given. "
            "Reply with the JSON object only.",
        ]
    )
    return "\n".join(lines)


def build_summary_prompt(context: InterpretationContext) -> str:
    """Render either summary kind using only the shared context surface."""
    if context.kind is InterpretationKind.DAILY_READING:
        raise ValueError("daily reading contexts use build_user_prompt")
    subject = "NATAL CHART" if context.kind is InterpretationKind.NATAL_SUMMARY else "TODAY'S SKY"
    lines = [
        subject,
        f"  person: {context.profile_display_name}",
        f"  local date: {context.consultation_local_date}",
        "",
        "NATAL PLACEMENTS SUPPLIED",
        *(f"  {_format_placement(p)}" for p in context.relevant_natal_placements),
        f"  Ascendant sign: {context.ascendant_sign}",
    ]
    if context.kind is InterpretationKind.COSMOS_SUMMARY:
        lines.extend(["", "SIGNIFICANT TRANSITS (already filtered and ranked by Syzygy)"])
        if context.significant_transits:
            lines.extend(f"  {_format_transit(t)}" for t in context.significant_transits)
        else:
            lines.append("  none within orb today - describe a quiet sky, not missing data")
        lines.extend(
            [
                "",
                "Summarize the tone of this already-ranked sky against the supplied natal points.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "Summarize the chart's durable themes and tensions. This is not a forecast.",
            ]
        )
    return "\n".join(lines)


def build_summary_repair_prompt(raw_output: str, error: str) -> str:
    return (
        "Your previous reply was invalid JSON for the required summary shape. "
        "Reply with only {\"headline\": \"string\", \"body\": \"string\"}. "
        f"Validation error: {error}\nPrevious reply:\n{raw_output}"
    )


def build_repair_prompt(raw_output: str, error: str) -> str:
    """The single repair turn of DESIGN.md section 13.4.

    A provider sends this after its first reply failed validation; if the
    second reply fails too, the provider raises and the reading is marked
    `INTERPRETATION_FAILED` with its card and snapshot untouched.
    """
    return (
        f"{REPAIR_INSTRUCTION}\n\n"
        f"Validation error:\n{error}\n\n"
        f"Your previous reply:\n{raw_output}"
    )
