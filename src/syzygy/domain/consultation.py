"""The Oracle rite: one question, two chance objects, one lifecycle.

ADR 0008. A consultation carries a Thoth card (the figure) and a six-line
I Ching cast (the ground) from a single turn of the wheel. The two are
committed together, so past `ASKED` neither is optional: a consultation
holding one object and not the other is not representable here and cannot
be stored (see `syzygy.storage.consultations`).

The status shape is the one every other rite in Syzygy uses, for the same
reason (`syzygy.domain.reading.ReadingStatus`): a failed or retried
interpretation moves only between `INTERPRETING` and
`INTERPRETATION_FAILED`, never back to `ASKED`, so no retry path can
redraw the card or recast the lines.

`syzygy.domain.oracle` and `syzygy.domain.iching_consultation` remain as
the read-only history of the two single-object rites this supersedes.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from syzygy.domain.iching import IChingCast
from syzygy.domain.interpretation import InterpretationContext, OracleResult
from syzygy.domain.knowledge import RetrievedCitation
from syzygy.domain.oracle import OracleQuestion
from syzygy.domain.tarot import TarotDraw


class ConsultationStatus(StrEnum):
    ASKED = "asked"
    DRAWN = "drawn"
    CONTEXT_READY = "context_ready"
    INTERPRETING = "interpreting"
    COMPLETE = "complete"
    INTERPRETATION_FAILED = "interpretation_failed"


ALLOWED_TRANSITIONS: dict[ConsultationStatus, frozenset[ConsultationStatus]] = {
    ConsultationStatus.ASKED: frozenset({ConsultationStatus.DRAWN}),
    ConsultationStatus.DRAWN: frozenset({ConsultationStatus.CONTEXT_READY}),
    ConsultationStatus.CONTEXT_READY: frozenset({ConsultationStatus.INTERPRETING}),
    ConsultationStatus.INTERPRETING: frozenset(
        {ConsultationStatus.COMPLETE, ConsultationStatus.INTERPRETATION_FAILED}
    ),
    ConsultationStatus.INTERPRETATION_FAILED: frozenset({ConsultationStatus.INTERPRETING}),
    ConsultationStatus.COMPLETE: frozenset(),
}

#: Every status in which both chance objects must already exist. `ASKED`
#: is the only state before the wheel turns, and it is the only state in
#: which either may be absent - in which case both must be.
_DRAWN_STATUSES = frozenset(ALLOWED_TRANSITIONS) - {ConsultationStatus.ASKED}


class Consultation(BaseModel):
    """One committed Oracle consultation: the figure and its ground."""

    model_config = ConfigDict(frozen=True)

    id: str
    profile_id: str
    question: OracleQuestion
    status: ConsultationStatus
    consultation_local_timestamp: str
    consultation_timezone: str
    card_draw: TarotDraw | None = None
    cast: IChingCast | None = None
    interpretation_context: InterpretationContext | None = None
    retrieved_citations: list[RetrievedCitation] = Field(default_factory=list)
    provider_id: str | None = None
    model_id: str | None = None
    prompt_version: str | None = None
    result: OracleResult | None = None
    created_at_utc: datetime
    updated_at_utc: datetime

    @model_validator(mode="after")
    def validate_both_chance_objects(self) -> Consultation:
        if self.status in _DRAWN_STATUSES:
            if self.card_draw is None or self.cast is None:
                raise ValueError(
                    "a consultation past 'asked' carries both a card and a cast"
                )
        elif self.card_draw is not None or self.cast is not None:
            raise ValueError("an unasked consultation carries neither chance object")
        return self
