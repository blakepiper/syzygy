"""The interpretation contract: what the model receives, and what it must
produce.

`InterpretationContext` is the entire input surface for a provider
(docs/old/DESIGN.md section 12, docs/old/ARCHITECTURE_HANDOFF.md section 19). Provider
adapters build a prompt from this object; they never reach back into the
database, the profile, or the astrology engine themselves.

`InterpretationResult` is the required structured output shape
(docs/old/DESIGN.md section 13.4). Providers must produce exactly this - free-form
prose is never accepted as the internal representation.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from syzygy.domain.astrology import NatalPlacement, RankedTransit
from syzygy.domain.iching import Hexagram, IChingCast
from syzygy.domain.knowledge import KnowledgeChunk
from syzygy.domain.tarot import TarotCard

CONTEXT_SCHEMA_VERSION = "context-v4"


class InterpretationKind(StrEnum):
    DAILY_READING = "daily_reading"
    ORACLE = "oracle"
    I_CHING = "i_ching"
    NATAL_SUMMARY = "natal_summary"
    COSMOS_SUMMARY = "cosmos_summary"


class InterpretationContext(BaseModel):
    """A fully-resolved, serializable snapshot handed to a provider.

    Deliberately excludes (docs/old/DESIGN.md section 12.3): the full natal chart,
    every transit, every minor body, the entire Book of Thoth, and any
    previous reading. Building a narrower context than "everything we
    have" is the context builder's job, not the provider's.
    """

    model_config = ConfigDict(frozen=True)

    context_schema_version: str = CONTEXT_SCHEMA_VERSION
    kind: InterpretationKind = InterpretationKind.DAILY_READING
    profile_display_name: str
    consultation_local_date: str
    consultation_local_timestamp: str
    card: TarotCard | None = None
    iching_cast: IChingCast | None = None
    primary_hexagram: Hexagram | None = None
    resulting_hexagram: Hexagram | None = None
    significant_transits: list[RankedTransit]
    relevant_natal_placements: list[NatalPlacement]
    sun_placement: NatalPlacement
    moon_placement: NatalPlacement
    ascendant_sign: str
    knowledge_chunks: list[KnowledgeChunk]
    prompt_version: str
    question: str | None = None

    @model_validator(mode="after")
    def validate_kind(self) -> InterpretationContext:
        if self.kind in (InterpretationKind.DAILY_READING, InterpretationKind.ORACLE):
            if self.card is None:
                raise ValueError("a reading context requires a fixed card")
            if self.iching_cast is not None:
                raise ValueError("a card consultation cannot carry an I Ching cast")
        elif self.kind is InterpretationKind.I_CHING:
            if self.card is not None:
                raise ValueError("an I Ching consultation cannot carry a card")
            if self.iching_cast is None or self.primary_hexagram is None:
                raise ValueError("an I Ching context requires its fixed cast and hexagram")
            if self.resulting_hexagram is None:
                raise ValueError("an I Ching context requires the resulting hexagram")
        elif any(
            value is not None
            for value in (
                self.card,
                self.iching_cast,
                self.primary_hexagram,
                self.resulting_hexagram,
            )
        ):
            raise ValueError("summary contexts must not contain a chance object")
        question_kinds = (InterpretationKind.ORACLE, InterpretationKind.I_CHING)
        if self.kind in question_kinds and self.question is None:
            raise ValueError("a question-led context requires a question")
        if self.kind not in question_kinds and self.question is not None:
            raise ValueError("only question-led contexts carry a question")
        return self


class EsotericReading(BaseModel):
    model_config = ConfigDict(frozen=True)

    summary: str
    body: str


class ConventionalReading(BaseModel):
    model_config = ConfigDict(frozen=True)

    summary: str
    body: str
    watch_for: list[str] = Field(default_factory=list)
    reflection: str


class InterpretationResult(BaseModel):
    """The required structured output of any `InterpretationProvider`
    (docs/old/DESIGN.md section 13.4). Validated with Pydantic; a provider that
    cannot produce this shape has failed interpretation, not produced a
    degraded reading - see `syzygy.domain.reading.ReadingStatus`.
    """

    model_config = ConfigDict(frozen=True)

    alignment_title: str
    esoteric: EsotericReading
    conventional: ConventionalReading
    source_chunk_ids: list[str] = Field(default_factory=list)
    provider_id: str
    model_id: str
    prompt_version: str


class OracleResult(InterpretationResult):
    """Structured Oracle output: two registers plus a direct reflection."""

    question_response: str


class SummaryResult(BaseModel):
    """Structured output for a natal or daily-cosmos summary."""

    model_config = ConfigDict(frozen=True)

    headline: str
    body: str
    provider_id: str
    model_id: str
    prompt_version: str
