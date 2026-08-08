from datetime import UTC, datetime

import pytest

from syzygy.domain.knowledge import KnowledgeChunk, KnowledgeSource
from syzygy.knowledge.store import count_chunks, get_source_by_type, replace_source
from syzygy.storage.database import connect
from syzygy.storage.migrations import apply_all


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "test.db")
    apply_all(connection)
    yield connection
    connection.close()


def _source(source_type: str = "book_of_thoth", file_hash: str = "hash1") -> KnowledgeSource:
    return KnowledgeSource(
        id=f"src-{file_hash}",
        source_type=source_type,
        title="The Book of Thoth",
        file_hash=file_hash,
        ingestion_version="v1",
        created_at_utc=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _chunk(source_id: str, card_id: str = "the_fool", chunk_index: int = 0) -> KnowledgeChunk:
    return KnowledgeChunk(
        id=f"chunk-{source_id}-{card_id}-{chunk_index}",
        source_id=source_id,
        section_id=f"sec-{card_id}",
        section_type="card",
        card_id=card_id,
        title="The Fool",
        page_start=27,
        page_end=27,
        chunk_index=chunk_index,
        text="This card is attributed to the letter Aleph.",
        text_hash="texthash1",
    )


def test_get_source_by_type_returns_none_when_absent(conn):
    assert get_source_by_type(conn, "book_of_thoth") is None


def test_replace_source_inserts_source_and_chunks(conn):
    source = _source()
    chunks = [_chunk(source.id, chunk_index=0), _chunk(source.id, chunk_index=1)]
    replace_source(conn, source, chunks)

    stored = get_source_by_type(conn, "book_of_thoth")
    assert stored is not None
    assert stored.file_hash == "hash1"
    assert count_chunks(conn, stored.id) == 2


def test_replace_source_replaces_existing_same_type(conn):
    first = _source(file_hash="hash1")
    replace_source(conn, first, [_chunk(first.id)])

    second = _source(file_hash="hash2")
    replace_source(conn, second, [_chunk(second.id), _chunk(second.id, chunk_index=1)])

    stored = get_source_by_type(conn, "book_of_thoth")
    assert stored is not None
    assert stored.file_hash == "hash2"
    assert count_chunks(conn, stored.id) == 2
    # the old source row is gone entirely, not just superseded
    assert conn.execute("SELECT COUNT(*) FROM knowledge_sources").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0] == 2


def test_replace_source_keeps_other_source_types_untouched(conn):
    bot = _source(source_type="book_of_thoth", file_hash="hash1")
    replace_source(conn, bot, [_chunk(bot.id)])

    duquette = _source(source_type="duquette_companion", file_hash="hash2")
    replace_source(conn, duquette, [_chunk(duquette.id)])

    assert get_source_by_type(conn, "book_of_thoth") is not None
    assert get_source_by_type(conn, "duquette_companion") is not None
    assert conn.execute("SELECT COUNT(*) FROM knowledge_sources").fetchone()[0] == 2


def test_replace_source_keeps_fts_index_in_sync(conn):
    source = _source()
    replace_source(conn, source, [_chunk(source.id)])
    hits = conn.execute(
        "SELECT COUNT(*) FROM knowledge_chunks_fts WHERE knowledge_chunks_fts MATCH 'Aleph'"
    ).fetchone()[0]
    assert hits == 1

    # re-ingesting should not leave the old chunk's text still searchable
    replaced = _source(file_hash="hash2")
    replace_source(
        conn,
        replaced,
        [
            KnowledgeChunk(
                id="chunk-new",
                source_id=replaced.id,
                section_id="sec-the_fool",
                section_type="card",
                card_id="the_fool",
                title="The Fool",
                page_start=27,
                page_end=27,
                chunk_index=0,
                text="Completely different replacement text.",
                text_hash="texthash2",
            )
        ],
    )
    stale_hits = conn.execute(
        "SELECT COUNT(*) FROM knowledge_chunks_fts WHERE knowledge_chunks_fts MATCH 'Aleph'"
    ).fetchone()[0]
    assert stale_hits == 0
