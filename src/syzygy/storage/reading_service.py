"""Daily reading orchestration (DESIGN.md §5.1, IMPLEMENTATION_PLAN.md §4.2).

`get_or_create_todays_reading` is where the ordering invariant from
DESIGN.md section 5.1 actually lives in code: profile -> astrology ->
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
from syzygy.domain.astrology import (
    NatalPlacement,
    RankedTransit,
    TransitSnapshot,
    sign_for_longitude,
)
from syzygy.domain.interpretation import InterpretationContext
from syzygy.domain.profile import Profile
from syzygy.domain.reading import Reading, ReadingStatus
from syzygy.domain.tarot import TarotCard
from syzygy.interpretation.base import InterpretationProvider
from syzygy.sortes.deck import get_card
from syzygy.sortes.draw import draw_card
from syzygy.sortes.entropy import EntropyCollector
from syzygy.storage import readings

#: Placeholder pending `syzygy.interpretation.prompts.PROMPT_VERSION`
#: (Milestone 7, not yet implemented). This module builds a minimal
#: `InterpretationContext` itself for now rather than depending on
#: `interpretation.context_builder` (also Milestone 7); once that module
#: exists, `_build_context` below should be replaced by a call to it.
_INTERIM_PROMPT_VERSION = "reading-service-interim-v1"


def _find_placement(placements: list[NatalPlacement], body: str) -> NatalPlacement:
    for placement in placements:
        if placement.body == body:
            return placement
    raise ValueError(f"natal chart has no placement for {body!r}")


def _build_context(
    profile: Profile,
    card: TarotCard,
    ranked_transits: list[RankedTransit],
    *,
    consultation_local_date: str,
    consultation_local_timestamp: str,
) -> InterpretationContext:
    natal = profile.natal_chart
    sun = _find_placement(natal.placements, "Sun")
    moon = _find_placement(natal.placements, "Moon")
    return InterpretationContext(
        profile_display_name=profile.display_name,
        consultation_local_date=consultation_local_date,
        consultation_local_timestamp=consultation_local_timestamp,
        card=card,
        significant_transits=ranked_transits,
        relevant_natal_placements=[sun, moon],
        sun_placement=sun,
        moon_placement=moon,
        ascendant_sign=sign_for_longitude(natal.ascendant_longitude),
        knowledge_chunks=[],  # Book of Thoth retrieval is Milestone 6, not yet implemented
        prompt_version=_INTERIM_PROMPT_VERSION,
    )


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
    before this has returned (DESIGN.md §5.1), and the caller (the TUI's
    reveal sequence) needs the committed card *before* interpretation
    starts. Returns a reading in `CONTEXT_READY` or later; a reading that
    is already past those stages is returned untouched.
    """
    local_now = clock.now_utc().astimezone()  # system local timezone (DESIGN.md §10)
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
        snapshot, ranked = rank_current_transits(profile, astrology, clock.now_utc())
        context = _build_context(
            profile,
            get_card(reading.card_draw.card_id),
            ranked,
            consultation_local_date=reading.consultation_local_date,
            consultation_local_timestamp=reading.consultation_local_timestamp,
        )
        reading = readings.commit_context(
            conn,
            reading.id,
            snapshot=snapshot,
            selected=ranked,
            context=context,
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
        # (DESIGN.md §13.4) - never propagate, never redraw.
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
