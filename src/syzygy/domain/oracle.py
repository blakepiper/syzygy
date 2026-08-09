"""A question-led Oracle consultation and its committed lifecycle."""

from __future__ import annotations

import unicodedata
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from syzygy.domain.astrology import TransitSnapshot
from syzygy.domain.interpretation import InterpretationContext, OracleResult
from syzygy.domain.knowledge import RetrievedCitation
from syzygy.domain.tarot import TarotDraw

MAX_QUESTION_LENGTH = 1000


def normalize_question(text: str) -> str:
    """Return prompt-safe plain text while preserving the stored original."""
    if len(text) > MAX_QUESTION_LENGTH:
        raise ValueError(f"question must be at most {MAX_QUESTION_LENGTH} characters")
    plain_chars: list[str] = []
    for char in text:
        if char.isspace():
            plain_chars.append(" ")
        elif not unicodedata.category(char).startswith("C"):
            plain_chars.append(char)
    plain = "".join(plain_chars)
    normalized = " ".join(plain.split())
    if not normalized:
        raise ValueError("question must not be empty")
    return normalized


class OracleQuestion(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str = Field(max_length=MAX_QUESTION_LENGTH)
    normalized_text: str
    asked_at_utc: datetime
    consultation_local_date: str

    @model_validator(mode="after")
    def validate_normalized_text(self) -> OracleQuestion:
        if self.normalized_text != normalize_question(self.text):
            raise ValueError("normalized_text must be derived from text")
        return self


class OracleStatus(StrEnum):
    ASKED = "asked"
    DRAWN = "drawn"
    CONTEXT_READY = "context_ready"
    INTERPRETING = "interpreting"
    COMPLETE = "complete"
    INTERPRETATION_FAILED = "interpretation_failed"


ALLOWED_TRANSITIONS: dict[OracleStatus, frozenset[OracleStatus]] = {
    OracleStatus.ASKED: frozenset({OracleStatus.DRAWN}),
    OracleStatus.DRAWN: frozenset({OracleStatus.CONTEXT_READY}),
    OracleStatus.CONTEXT_READY: frozenset({OracleStatus.INTERPRETING}),
    OracleStatus.INTERPRETING: frozenset(
        {OracleStatus.COMPLETE, OracleStatus.INTERPRETATION_FAILED}
    ),
    OracleStatus.INTERPRETATION_FAILED: frozenset({OracleStatus.INTERPRETING}),
    OracleStatus.COMPLETE: frozenset(),
}


class OracleConsultation(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    profile_id: str
    question: OracleQuestion
    status: OracleStatus
    consultation_local_timestamp: str
    consultation_timezone: str
    card_draw: TarotDraw | None = None
    transit_snapshot: TransitSnapshot | None = None
    interpretation_context: InterpretationContext | None = None
    retrieved_citations: list[RetrievedCitation] = Field(default_factory=list)
    provider_id: str | None = None
    model_id: str | None = None
    prompt_version: str | None = None
    result: OracleResult | None = None
    created_at_utc: datetime
    updated_at_utc: datetime
