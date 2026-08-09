"""A question-led I Ching consultation and its committed lifecycle."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from syzygy.domain.astrology import TransitSnapshot
from syzygy.domain.iching import IChingCast
from syzygy.domain.interpretation import InterpretationContext, OracleResult
from syzygy.domain.oracle import OracleQuestion


class IChingStatus(StrEnum):
    ASKED = "asked"
    CAST = "cast"
    CONTEXT_READY = "context_ready"
    INTERPRETING = "interpreting"
    COMPLETE = "complete"
    INTERPRETATION_FAILED = "interpretation_failed"


ALLOWED_TRANSITIONS: dict[IChingStatus, frozenset[IChingStatus]] = {
    IChingStatus.ASKED: frozenset({IChingStatus.CAST}),
    IChingStatus.CAST: frozenset({IChingStatus.CONTEXT_READY}),
    IChingStatus.CONTEXT_READY: frozenset({IChingStatus.INTERPRETING}),
    IChingStatus.INTERPRETING: frozenset(
        {IChingStatus.COMPLETE, IChingStatus.INTERPRETATION_FAILED}
    ),
    IChingStatus.INTERPRETATION_FAILED: frozenset({IChingStatus.INTERPRETING}),
    IChingStatus.COMPLETE: frozenset(),
}


class IChingConsultation(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    profile_id: str
    question: OracleQuestion
    status: IChingStatus
    consultation_local_timestamp: str
    consultation_timezone: str
    cast: IChingCast | None = None
    transit_snapshot: TransitSnapshot | None = None
    interpretation_context: InterpretationContext | None = None
    provider_id: str | None = None
    model_id: str | None = None
    prompt_version: str | None = None
    result: OracleResult | None = None
    created_at_utc: datetime
    updated_at_utc: datetime
