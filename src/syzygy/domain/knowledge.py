"""Book of Thoth knowledge-base domain models.

See docs/THOTH_INGESTION_MAP.md for how these are populated from the PDF,
and docs/old/DESIGN.md section 11 for the two-tier (structural, then lexical)
retrieval policy these support.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

#: The canonical source. Tier 0 is the only source `thoth_deck.yaml` is
#: grounded against and the only one anything may cite as stating a Thoth
#: correspondence as fact (AGENTS.md, docs/KNOWLEDGE_SOURCES.md section 1.1).
TIER_0_SOURCE_TYPE = "book_of_thoth"

#: Every `source_type` Syzygy knows, and its tier. Declared here rather
#: than in `syzygy.knowledge` so retrieval, storage and the interface all
#: read one table - a source that is Tier 0 to the retriever and Tier 1 in
#: the reading's citation list would be a silent grounding lie.
SOURCE_TIERS: dict[str, int] = {
    TIER_0_SOURCE_TYPE: 0,
    "duquette_companion": 1,
    "ziegler_mirror_of_soul": 1,
}


def tier_for_source_type(source_type: str) -> int:
    """The tier of `source_type`. An unrecognised source is supplementary:
    nothing becomes canonical by not being listed."""
    return SOURCE_TIERS.get(source_type, 1)


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
    #: The owning source's `source_type`, resolved by the retrieval query.
    #: `KnowledgeChunk.source_id` is a row id, which says nothing about
    #: tier; callers that need to know whether a hit is canonical need
    #: this, and joining for it again per hit would be absurd.
    source_type: str | None = None


class RetrievedCitation(BaseModel):
    """Where a card is discussed, as recorded on the reading itself (M18.1a).

    This is deliberately *not* part of `InterpretationContext`: that type
    is a provider's entire input surface (AGENTS.md), and a citation with
    no passage under it is exactly the thing a model will fabricate the
    contents of. Citations reach the user; passages reach the provider.
    `text_available` is what separates the two, recorded at retrieval time
    so the `[I]` inputs view can say which chunks were actually sent.
    """

    model_config = ConfigDict(frozen=True)

    chunk_id: str
    source_id: str
    source_type: str
    tier: int
    title: str
    card_id: str | None = None
    page_start: int
    page_end: int
    retrieval_method: str
    text_available: bool

    @classmethod
    def from_hit(cls, hit: KnowledgeHit) -> RetrievedCitation:
        source_type = hit.source_type or ""
        return cls(
            chunk_id=hit.chunk.id,
            source_id=hit.chunk.source_id,
            source_type=source_type,
            tier=tier_for_source_type(source_type),
            title=hit.chunk.title,
            card_id=hit.chunk.card_id,
            page_start=hit.chunk.page_start,
            page_end=hit.chunk.page_end,
            retrieval_method=hit.retrieval_method,
            text_available=hit.chunk.has_text,
        )

    @property
    def reference(self) -> str:
        """Where the passage is, in a form a person can go and read."""
        return f"{self.title} (pages {self.page_start}-{self.page_end})"
