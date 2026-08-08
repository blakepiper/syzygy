"""Writes to `knowledge_sources` / `knowledge_chunks` (source-agnostic).

The `knowledge_chunks_fts` FTS5 index (migration 3,
`syzygy.storage.migrations`) stays in sync automatically via that
migration's own AFTER INSERT/DELETE/UPDATE triggers - nothing in this
module touches it directly.

Vectors are computed here rather than by the caller (M13.3). This is the
one write path for chunk text, so doing it here is what guarantees every
stored chunk - ingested locally or installed from the bundled artifact -
carries a signature at the current `VECTOR_VERSION` and is findable by
`retrieve.search_vectors`.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from syzygy.domain.knowledge import KnowledgeChunk, KnowledgeSource
from syzygy.knowledge.embedding import VECTOR_VERSION, lexical_vector


def _row_to_source(row: sqlite3.Row) -> KnowledgeSource:
    return KnowledgeSource(
        id=row["id"],
        source_type=row["source_type"],
        title=row["title"],
        file_hash=row["file_hash"],
        ingestion_version=row["ingestion_version"],
        created_at_utc=datetime.fromisoformat(row["created_at"]),
    )


def get_source_by_type(conn: sqlite3.Connection, source_type: str) -> KnowledgeSource | None:
    """A given `source_type` has at most one currently-ingested source -
    re-ingestion replaces it wholesale (see `replace_source`)."""
    row = conn.execute(
        "SELECT * FROM knowledge_sources WHERE source_type = ?", (source_type,)
    ).fetchone()
    return _row_to_source(row) if row is not None else None


def count_chunks(conn: sqlite3.Connection, source_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM knowledge_chunks WHERE source_id = ?", (source_id,)
    ).fetchone()
    return int(row[0])


def has_full_text(conn: sqlite3.Connection, source_id: str) -> bool:
    """Whether this source's chunks carry passages, or only citations.

    A source installed from the bundled artifact (M13.3) has rows, a real
    `file_hash` and a real `ingestion_version`, but empty text - so
    "is it present?" and "does it have the text?" are different questions,
    and `ingest`'s skip check has to ask the second one.
    """
    row = conn.execute(
        "SELECT 1 FROM knowledge_chunks WHERE source_id = ? AND text != '' LIMIT 1",
        (source_id,),
    ).fetchone()
    return row is not None


def replace_source(
    conn: sqlite3.Connection, source: KnowledgeSource, chunks: list[KnowledgeChunk]
) -> None:
    """Atomically replace any existing source of `source.source_type` (and
    all of its chunks) with `source`/`chunks`. Re-ingesting the same file
    at a bumped `ingestion_version`, a changed file at the same
    `source_type`, or a first-time ingest are all the same operation from
    here - `ingest.py` is responsible for deciding *whether* to call this
    (its idempotency/skip check happens before this is ever invoked).

    `syzygy.storage.database.connect` opens connections with
    `isolation_level=None` (autocommit), so - as in
    `syzygy.storage.migrations.apply_all` - atomicity across these
    statements requires an explicit `BEGIN`/`COMMIT` rather than the
    `with conn:` context manager, which only batches statements into one
    transaction under the (unused here) default `isolation_level`."""
    conn.execute("BEGIN")
    try:
        existing = conn.execute(
            "SELECT id FROM knowledge_sources WHERE source_type = ?", (source.source_type,)
        ).fetchall()
        for row in existing:
            conn.execute("DELETE FROM knowledge_chunks WHERE source_id = ?", (row["id"],))
        conn.execute(
            "DELETE FROM knowledge_sources WHERE source_type = ?", (source.source_type,)
        )

        conn.execute(
            """
            INSERT INTO knowledge_sources
                (id, source_type, title, file_hash, ingestion_version, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                source.id,
                source.source_type,
                source.title,
                source.file_hash,
                source.ingestion_version,
                source.created_at_utc.isoformat(),
            ),
        )
        conn.executemany(
            """
            INSERT INTO knowledge_chunks
                (id, source_id, section_id, section_type, card_id, title,
                 page_start, page_end, chunk_index, text, text_hash,
                 vector, vector_version, word_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    chunk.id,
                    chunk.source_id,
                    chunk.section_id,
                    chunk.section_type,
                    chunk.card_id,
                    chunk.title,
                    chunk.page_start,
                    chunk.page_end,
                    chunk.chunk_index,
                    chunk.text,
                    chunk.text_hash,
                    lexical_vector(chunk.text).tobytes(),
                    VECTOR_VERSION,
                    len(chunk.text.split()),
                )
                for chunk in chunks
            ],
        )
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
