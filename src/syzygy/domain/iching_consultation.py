"""Read-only history: the `iching-v1` cast-only consultation (M20).

The alternative-Oracle mode is gone; M22 casts a card and a hexagram in
one rite (`syzygy.domain.consultation`, ADR 0008). Stored rows are still
read and displayed, and nothing advances them - hence no transition table.
"""

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


class IChingConsultation(BaseModel):
    """A stored `iching-v1` consultation. Historical; never advanced."""

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
