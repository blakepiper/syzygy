"""The daily reading: the Syzygy alignment of Self + Cosmos + Chance, and
its lifecycle.

Core invariant (DESIGN.md section 7.4, ARCHITECTURE_HANDOFF.md section 23):
**the card is persisted immediately after the draw and before any model
call.** A failed or retried interpretation must never cause a redraw. The
`ReadingStatus` state machine exists to make that invariant checkable in
code and tests rather than only true "by convention".

One canonical reading exists per `(profile_id, consultation_local_date)`.
That uniqueness is enforced by the database (see
`syzygy.storage.migrations`), not merely by this model or by UI flow.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from syzygy.domain.astrology import TransitSnapshot
from syzygy.domain.interpretation import InterpretationContext, InterpretationResult
from syzygy.domain.tarot import TarotDraw


class ReadingStatus(StrEnum):
    """Allowed transitions:

    ::

        PREPARED -> DRAWN -> CONTEXT_READY -> INTERPRETING -> COMPLETE
                                                            -> INTERPRETATION_FAILED

    `INTERPRETATION_FAILED` may transition back to `INTERPRETING` on a
    user-initiated retry. No state may transition back to `PREPARED` or
    `DRAWN` once a card exists - that would be a reroll, which is forbidden
    (DESIGN.md section 5.3, section 7.4).
    """

    PREPARED = "prepared"
    DRAWN = "drawn"
    CONTEXT_READY = "context_ready"
    INTERPRETING = "interpreting"
    COMPLETE = "complete"
    INTERPRETATION_FAILED = "interpretation_failed"


#: Transitions that are always legal to attempt. Storage/service code
#: should reject any transition not listed here rather than trusting
#: callers to only call it correctly.
ALLOWED_TRANSITIONS: dict[ReadingStatus, frozenset[ReadingStatus]] = {
    ReadingStatus.PREPARED: frozenset({ReadingStatus.DRAWN}),
    ReadingStatus.DRAWN: frozenset({ReadingStatus.CONTEXT_READY}),
    ReadingStatus.CONTEXT_READY: frozenset({ReadingStatus.INTERPRETING}),
    ReadingStatus.INTERPRETING: frozenset(
        {ReadingStatus.COMPLETE, ReadingStatus.INTERPRETATION_FAILED}
    ),
    ReadingStatus.INTERPRETATION_FAILED: frozenset({ReadingStatus.INTERPRETING}),
    ReadingStatus.COMPLETE: frozenset(),
}


class Reading(BaseModel):
    """One profile's canonical reading for one local calendar date.

    Fields are progressively filled in as the reading advances through
    `ReadingStatus`; everything after `card_draw` is `None` until the
    corresponding stage completes. `card_draw` itself is never `None` once
    status has passed `PREPARED` and is never replaced afterwards.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    profile_id: str
    status: ReadingStatus

    consultation_local_date: str
    consultation_local_timestamp: str
    consultation_utc_timestamp: datetime
    consultation_timezone: str

    card_draw: TarotDraw | None = None
    transit_snapshot: TransitSnapshot | None = None
    interpretation_context: InterpretationContext | None = None

    provider_id: str | None = None
    model_id: str | None = None
    interpretation: InterpretationResult | None = None

    created_at_utc: datetime
    updated_at_utc: datetime
