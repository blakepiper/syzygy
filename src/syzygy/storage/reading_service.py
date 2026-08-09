"""Daily reading orchestration (docs/old/DESIGN.md §5.1, docs/old/IMPLEMENTATION_PLAN.md §4.2).

`get_or_create_todays_reading` is where the ordering invariant from
docs/old/DESIGN.md section 5.1 actually lives in code: profile -> astrology ->
entropy ritual -> card draw -> lock reading inputs -> retrieve knowledge
-> LLM interpretation -> save interpretation. Each stage is committed to
storage (`syzygy.storage.readings`) before the next one runs, so a crash
at any point can be resumed by calling these functions again with fresh
collaborators - the reading's own `status` says exactly where to resume,
and no stage that has already been committed is ever redone (in
particular, the card is never redrawn).

If today's reading is already `COMPLETE`, this function returns it
immediately without touching astrology, entropy, or the provider at all -
reopening a finished reading is a pure read.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from syzygy.astrology.base import AstrologyEngine
from syzygy.astrology.policy import TransitAspectPolicy
from syzygy.astrology.ranking import TransitRanker
from syzygy.clock import Clock
from syzygy.domain.astrology import RankedTransit, TransitSnapshot
from syzygy.domain.interpretation import OracleResult
from syzygy.domain.knowledge import KnowledgeChunk, KnowledgeHit, RetrievedCitation
from syzygy.domain.profile import Profile
from syzygy.domain.reading import Reading, ReadingStatus
from syzygy.interpretation.base import InterpretationProvider
from syzygy.interpretation.context_builder import build_context
from syzygy.interpretation.prompts import PROMPT_VERSION
from syzygy.knowledge.retrieve import retrieve_for_card
from syzygy.sortes.deck import get_card
from syzygy.sortes.draw import draw_card
from syzygy.sortes.entropy import EntropyCollector
from syzygy.storage import readings

#: How many chunks of any one ingested source may reach the model. The
#: structural lookup returns a card's whole section, which for a Major
#: Arcana card can run to several thousand words per source - more than a
#: daily reading needs and more than a local model comfortably holds.
#: Capping per source (rather than overall) keeps docs/old/DESIGN.md section 12.2's
#: "include only the top few" without letting Tier 0's own length crowd the
#: Tier 1 companions out entirely; retrieval order is otherwise preserved,
#: so Tier 0 still comes first.
MAX_KNOWLEDGE_CHUNKS_PER_SOURCE = 3


def _select_knowledge_chunks(hits: list[KnowledgeHit]) -> list[KnowledgeChunk]:
    """The chunks that may reach the model, capped per source.

    Citation-only chunks are dropped (M13.3). The artifact bundled with
    every install carries where each card is discussed but not what those
    pages say, and a citation rendered under the prompt's "SOURCE
    PASSAGES" heading with nothing beneath it is worse than no source at
    all - it invites the model to invent the contents, which is exactly
    the failure `docs/old/DESIGN.md` section 23 forbids ("never imply Crowley
    grounding that was not actually retrieved"). An install with no
    ingested PDFs therefore supplies no passages and the prompt says so
    plainly, exactly as it did before the artifact existed.
    """
    selected: list[KnowledgeChunk] = []
    per_source: dict[str, int] = {}
    for hit in hits:
        if not hit.chunk.has_text:
            continue
        taken = per_source.get(hit.chunk.source_id, 0)
        if taken >= MAX_KNOWLEDGE_CHUNKS_PER_SOURCE:
            continue
        per_source[hit.chunk.source_id] = taken + 1
        selected.append(hit.chunk)
    return selected


def rank_current_transits(
    profile: Profile, astrology: AstrologyEngine, instant: datetime
) -> tuple[TransitSnapshot, list[RankedTransit]]:
    """Calculate the sky at `instant` and apply Syzygy's own significance
    policy + ranking to it.

    The composition "engine -> policy -> ranker" lives here rather than in
    any caller, so that the TUI's home-screen sky preview and the draw
    stage below cannot drift apart in what they consider significant
    (AGENTS.md: Syzygy owns transit significance).
    """
    snapshot = astrology.calculate_transits(profile.natal_chart, instant)
    filtered = TransitAspectPolicy().filter(snapshot.raw_aspects)
    return snapshot, TransitRanker().rank(filtered)


def draw_todays_reading(
    conn: sqlite3.Connection,
    profile: Profile,
    clock: Clock,
    astrology: AstrologyEngine,
    entropy: EntropyCollector,
) -> Reading:
    """The oracle half of the pipeline: open today's reading, draw and
    immediately commit the card if it has not been drawn, then calculate
    and commit the transit snapshot and interpretation context.

    Deliberately synchronous and provider-free: no model call may happen
    before this has returned (docs/old/DESIGN.md §5.1), and the caller (the TUI's
    reveal sequence) needs the committed card *before* interpretation
    starts. Returns a reading in `CONTEXT_READY` or later; a reading that
    is already past those stages is returned untouched.
    """
    local_now = clock.now_utc().astimezone()  # system local timezone (docs/old/DESIGN.md §10)
    local_date = local_now.date().isoformat()

    reading = readings.get_today(conn, profile.id, local_date)
    if reading is None:
        reading = readings.create_prepared(
            conn,
            profile_id=profile.id,
            consultation_local_date=local_date,
            consultation_local_timestamp=local_now.isoformat(),
            consultation_utc_timestamp=clock.now_utc(),
            consultation_timezone=local_now.tzname() or "UTC",
        )

    if reading.status == ReadingStatus.PREPARED:
        draw = draw_card(entropy, now=clock.now_utc())
        reading = readings.commit_draw(conn, reading.id, draw)

    if reading.status == ReadingStatus.DRAWN:
        assert reading.card_draw is not None
        card = get_card(reading.card_draw.card_id)
        snapshot, ranked = rank_current_transits(profile, astrology, clock.now_utc())
        # An empty knowledge base is not an error: the reading proceeds
        # without source passages, and the prompt says so explicitly rather
        # than implying Crowley grounding that was never retrieved
        # (docs/old/DESIGN.md section 23).
        #
        # Retrieval runs once and its result forks (M18.1a): the chunks
        # that carry passages go into the context and reach the provider,
        # while every hit - passages or citations alone - is recorded on
        # the reading so the `[I]` view can say where this card is
        # discussed even on an install that has ingested nothing.
        hits = retrieve_for_card(conn, card.id)
        chunks = _select_knowledge_chunks(hits)
        citations = [RetrievedCitation.from_hit(hit) for hit in hits]
        context = build_context(
            profile=profile,
            card=card,
            ranked_transits=ranked,
            knowledge_chunks=chunks,
            consultation_local_timestamp=reading.consultation_local_timestamp,
            consultation_local_date=reading.consultation_local_date,
            prompt_version=PROMPT_VERSION,
        )
        reading = readings.commit_context(
            conn,
            reading.id,
            snapshot=snapshot,
            selected=ranked,
            context=context,
            citations=citations,
            now=clock.now_utc(),
        )

    return reading


async def interpret_reading(
    conn: sqlite3.Connection,
    reading: Reading,
    clock: Clock,
    provider: InterpretationProvider,
) -> Reading:
    """The interpretation half of the pipeline, for an already-drawn
    reading. Safe to call repeatedly: a `COMPLETE` reading is returned
    untouched, and an `INTERPRETATION_FAILED` one is retried against the
    stored context - the same card, the same snapshot, every time.
    """
    if reading.status == ReadingStatus.COMPLETE:
        return reading
    if reading.status in (ReadingStatus.PREPARED, ReadingStatus.DRAWN):
        raise ValueError(f"reading {reading.id!r} has no context yet (status {reading.status})")

    if reading.status in (ReadingStatus.CONTEXT_READY, ReadingStatus.INTERPRETATION_FAILED):
        # From INTERPRETATION_FAILED this is a user-initiated retry
        # (ReadingStatus docstring) - the stored context from the original
        # DRAWN->CONTEXT_READY step is reused verbatim; there is no path
        # back to CONTEXT_READY to rebuild it.
        reading = readings.begin_interpreting(conn, reading.id, now=clock.now_utc())

    assert reading.interpretation_context is not None
    try:
        result = await provider.interpret(reading.interpretation_context)
    except Exception:
        # Provider failure is not an application error: preserve the
        # oracle state and let the caller show a recoverable error
        # (docs/old/DESIGN.md §13.4) - never propagate, never redraw.
        return readings.fail_interpretation(conn, reading.id, now=clock.now_utc())
    if isinstance(result, OracleResult):
        return readings.fail_interpretation(conn, reading.id, now=clock.now_utc())
    return readings.complete_interpretation(conn, reading.id, result, now=clock.now_utc())


async def get_or_create_todays_reading(
    conn: sqlite3.Connection,
    profile: Profile,
    clock: Clock,
    astrology: AstrologyEngine,
    entropy: EntropyCollector,
    provider: InterpretationProvider,
) -> Reading:
    """The whole pipeline end to end, for callers (the CLI, tests) that do
    not need to show anything between the draw and the interpretation.

    The TUI instead calls `draw_todays_reading` and `interpret_reading`
    separately, so the card reveal can happen while the model is still
    working - the ordering guarantee is identical either way, because it
    is these two functions that enforce it.
    """
    reading = draw_todays_reading(conn, profile, clock, astrology, entropy)
    return await interpret_reading(conn, reading, clock, provider)
