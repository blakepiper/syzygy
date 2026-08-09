"""Three-tier retrieval: exact `card_id` structural lookup, SQLite FTS5
lexical search, and vector search over hashed lexical signatures
(docs/old/DESIGN.md section 11.2).

Structural lookup is tier-aware across sources (docs/old/IMPLEMENTATION_PLAN.md
Milestone 6): Tier 0 (`book_of_thoth`) chunks are always returned first,
then any ingested Tier 1 (`duquette_companion`, `ziegler_mirror_of_soul`)
chunks for the same card - a source that was never ingested simply
contributes nothing (docs/KNOWLEDGE_SOURCES.md section 5).

Note which tiers work on which installs. Structural lookup and vector
search work everywhere, because the bundled artifact (M13.3) carries
citations and vectors for all three sources. FTS5 needs the passages
themselves and so only finds anything for sources the user has ingested
from their own PDFs - `search` on a citation-only install returns nothing,
which is correct rather than broken.
"""

from __future__ import annotations

import sqlite3

from syzygy.domain.knowledge import KnowledgeChunk, KnowledgeHit

_TIER_0_SOURCE_TYPE = "book_of_thoth"


def _row_to_chunk(row: sqlite3.Row) -> KnowledgeChunk:
    return KnowledgeChunk(
        id=row["id"],
        source_id=row["source_id"],
        section_id=row["section_id"],
        section_type=row["section_type"],
        card_id=row["card_id"],
        title=row["title"],
        page_start=row["page_start"],
        page_end=row["page_end"],
        chunk_index=row["chunk_index"],
        text=row["text"],
        text_hash=row["text_hash"],
    )


def retrieve_for_card(conn: sqlite3.Connection, card_id: str) -> list[KnowledgeHit]:
    """Exact structural lookup for one card: Tier 0 chunks first (in their
    original section/chunk order), then Tier 1 chunks grouped by source."""
    rows = conn.execute(
        """
        SELECT knowledge_chunks.*
        FROM knowledge_chunks
        JOIN knowledge_sources ON knowledge_sources.id = knowledge_chunks.source_id
        WHERE knowledge_chunks.card_id = ?
        ORDER BY
            CASE knowledge_sources.source_type WHEN ? THEN 0 ELSE 1 END,
            knowledge_sources.source_type,
            knowledge_chunks.section_id,
            knowledge_chunks.chunk_index
        """,
        (card_id, _TIER_0_SOURCE_TYPE),
    ).fetchall()
    return [
        KnowledgeHit(chunk=_row_to_chunk(row), retrieval_method="structural", score=None)
        for row in rows
    ]


def search(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[KnowledgeHit]:
    """SQLite FTS5 lexical search across every ingested source. `query`
    is passed through to FTS5's MATCH syntax as-is - callers that want
    plain free-text search should not include FTS5 special characters."""
    rows = conn.execute(
        """
        SELECT knowledge_chunks.*, bm25(knowledge_chunks_fts) AS fts_score
        FROM knowledge_chunks_fts
        JOIN knowledge_chunks ON knowledge_chunks.rowid = knowledge_chunks_fts.rowid
        WHERE knowledge_chunks_fts MATCH ?
        ORDER BY fts_score
        LIMIT ?
        """,
        (query, limit),
    ).fetchall()
    return [
        KnowledgeHit(chunk=_row_to_chunk(row), retrieval_method="fts", score=row["fts_score"])
        for row in rows
    ]


def search_vectors(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[KnowledgeHit]:
    """Vector search over every chunk carrying a current-version vector.

    Works on a citation-only install, where FTS5 has nothing to match
    against - the vectors ship with the package even though the passages
    do not (M13.3). Scores are cosine similarities in `[-1, 1]`; hits at
    or below zero share no vocabulary with the query and are dropped
    rather than padded out to `limit`.

    These are hashed lexical signatures, not neural embeddings (see
    `syzygy.knowledge.embedding`): this finds shared vocabulary, not
    shared meaning.
    """
    from syzygy.knowledge.artifact import chunk_vectors
    from syzygy.knowledge.embedding import lexical_vector, similarities

    query_vector = lexical_vector(query)
    if not query_vector.any():
        return []

    ids, matrix = chunk_vectors(conn)
    if not ids:
        return []

    scores = similarities(query_vector, matrix)
    ranked = sorted(zip(ids, scores, strict=True), key=lambda pair: -pair[1])[:limit]

    hits: list[KnowledgeHit] = []
    for chunk_id, score in ranked:
        if score <= 0:
            continue
        row = conn.execute(
            "SELECT * FROM knowledge_chunks WHERE id = ?", (chunk_id,)
        ).fetchone()
        if row is not None:
            hits.append(
                KnowledgeHit(
                    chunk=_row_to_chunk(row),
                    retrieval_method="semantic",
                    score=float(score),
                )
            )
    return hits
