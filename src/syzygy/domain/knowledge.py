"""Book of Thoth knowledge-base domain models.

See docs/THOTH_INGESTION_MAP.md for how these are populated from the PDF,
and DESIGN.md section 11 for the two-tier (structural, then lexical)
retrieval policy these support.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class KnowledgeSource(BaseModel):
    """One ingested source document (v0.1: the Book of Thoth PDF)."""

    model_config = ConfigDict(frozen=True)

    id: str
    source_type: str  # "book_of_thoth"
    title: str
    file_hash: str
    ingestion_version: str
    created_at_utc: datetime


class KnowledgeChunk(BaseModel):
    """A single retrievable, provenance-bearing unit of source text.

    Never crosses a card/section boundary (DESIGN.md section 11.3 step 5).
    """

    model_config = ConfigDict(frozen=True)

    id: str
    source_id: str
    section_id: str
    section_type: str  # "card" | "card_appendix" | "court_theory" | ...
    card_id: str | None
    title: str
    page_start: int
    page_end: int
    chunk_index: int
    text: str
    text_hash: str


class KnowledgeHit(BaseModel):
    """A chunk returned by a retrieval query, with the method that found it."""

    model_config = ConfigDict(frozen=True)

    chunk: KnowledgeChunk
    retrieval_method: str  # "structural" | "fts" | "semantic"
    score: float | None = None
