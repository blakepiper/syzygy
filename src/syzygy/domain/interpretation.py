"""The interpretation contract: what the model receives, and what it must
produce.

`InterpretationContext` is the entire input surface for a provider
(DESIGN.md section 12, ARCHITECTURE_HANDOFF.md section 19). Provider
adapters build a prompt from this object; they never reach back into the
database, the profile, or the astrology engine themselves.

`InterpretationResult` is the required structured output shape
(DESIGN.md section 13.4). Providers must produce exactly this - free-form
prose is never accepted as the internal representation.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from syzygy.domain.astrology import NatalPlacement, RankedTransit
from syzygy.domain.knowledge import KnowledgeChunk
from syzygy.domain.tarot import TarotCard

CONTEXT_SCHEMA_VERSION = "context-v2"


class InterpretationKind(StrEnum):
    DAILY_READING = "daily_reading"
    NATAL_SUMMARY = "natal_summary"
    COSMOS_SUMMARY = "cosmos_summary"


class InterpretationContext(BaseModel):
    """A fully-resolved, serializable snapshot handed to a provider.

    Deliberately excludes (DESIGN.md section 12.3): the full natal chart,
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
    significant_transits: list[RankedTransit]
    relevant_natal_placements: list[NatalPlacement]
    sun_placement: NatalPlacement
    moon_placement: NatalPlacement
    ascendant_sign: str
    knowledge_chunks: list[KnowledgeChunk]
    prompt_version: str

    @model_validator(mode="after")
    def validate_kind(self) -> InterpretationContext:
        if self.kind is InterpretationKind.DAILY_READING and self.card is None:
            raise ValueError("a daily reading context requires a fixed card")
        if self.kind is not InterpretationKind.DAILY_READING and self.card is not None:
            raise ValueError("summary contexts must not contain a card")
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
    (DESIGN.md section 13.4). Validated with Pydantic; a provider that
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


class SummaryResult(BaseModel):
    """Structured output for a natal or daily-cosmos summary."""

    model_config = ConfigDict(frozen=True)

    headline: str
    body: str
    provider_id: str
    model_id: str
    prompt_version: str
