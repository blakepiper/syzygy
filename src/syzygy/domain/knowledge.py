"""Book of Thoth knowledge-base domain models.

See docs/THOTH_INGESTION_MAP.md for how these are populated from the PDF,
and docs/old/DESIGN.md section 11 for the two-tier (structural, then lexical)
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

    Never crosses a card/section boundary (docs/old/DESIGN.md section 11.3 step 5).

    `text` may be empty. Installs that have not ingested the source PDFs
    still carry every chunk's *citation*, from the artifact bundled with
    the package (`syzygy.knowledge.artifact`) - the passage is what is
    missing, not the record of where it is. Use `has_text` to tell the two
    apart; anything that puts a chunk in front of a model must check it,
    because a citation with no text is an invitation to invent the
    contents.
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

    @property
    def has_text(self) -> bool:
        """Whether this chunk carries the passage itself, or only a
        citation to it."""
        return bool(self.text.strip())

    @property
    def citation(self) -> str:
        """Where the passage is, in a form a person can go and read."""
        return f"{self.title} (pages {self.page_start}-{self.page_end})"


class KnowledgeHit(BaseModel):
    """A chunk returned by a retrieval query, with the method that found it."""

    model_config = ConfigDict(frozen=True)

    chunk: KnowledgeChunk
    retrieval_method: str  # "structural" | "fts" | "semantic"
    score: float | None = None
