from datetime import UTC, datetime

import pytest

from syzygy.domain.knowledge import KnowledgeChunk, KnowledgeSource
from syzygy.knowledge.retrieve import retrieve_for_card, search
from syzygy.knowledge.store import replace_source
from syzygy.storage.database import connect
from syzygy.storage.migrations import apply_all


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "test.db")
    apply_all(connection)
    yield connection
    connection.close()


def _source(source_type: str, source_id: str) -> KnowledgeSource:
    return KnowledgeSource(
        id=source_id,
        source_type=source_type,
        title=source_type,
        file_hash=f"hash-{source_id}",
        ingestion_version="v1",
        created_at_utc=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _chunk(source_id: str, card_id: str, text: str, chunk_index: int = 0) -> KnowledgeChunk:
    return KnowledgeChunk(
        id=f"chunk-{source_id}-{card_id}-{chunk_index}",
        source_id=source_id,
        section_id=f"sec-{source_id}-{card_id}",
        section_type="card",
        card_id=card_id,
        title=card_id,
        page_start=1,
        page_end=1,
        chunk_index=chunk_index,
        text=text,
        text_hash=f"hash-{source_id}-{card_id}-{chunk_index}",
    )


def test_retrieve_for_card_returns_only_matching_card(conn):
    bot = _source("book_of_thoth", "src-bot")
    replace_source(
        conn,
        bot,
        [_chunk(bot.id, "the_fool", "Fool text"), _chunk(bot.id, "the_magus", "Magus text")],
    )
    hits = retrieve_for_card(conn, "the_fool")
    assert len(hits) == 1
    assert hits[0].chunk.card_id == "the_fool"
    assert hits[0].retrieval_method == "structural"


def test_retrieve_for_card_ranks_tier_0_ahead_of_tier_1(conn):
    bot = _source("book_of_thoth", "src-bot")
    replace_source(conn, bot, [_chunk(bot.id, "the_fool", "Tier 0 text about the Fool")])

    duquette = _source("duquette_companion", "src-duq")
    replace_source(conn, duquette, [_chunk(duquette.id, "the_fool", "Tier 1 DuQuette text")])

    ziegler = _source("ziegler_mirror_of_soul", "src-zieg")
    replace_source(conn, ziegler, [_chunk(ziegler.id, "the_fool", "Tier 1 Ziegler text")])

    hits = retrieve_for_card(conn, "the_fool")
    assert len(hits) == 3
    assert hits[0].chunk.source_id == bot.id
    tier1_source_ids = {hits[1].chunk.source_id, hits[2].chunk.source_id}
    assert tier1_source_ids == {duquette.id, ziegler.id}


def test_retrieve_for_card_tier_0_only_unaffected_by_absent_tier_1(conn):
    bot = _source("book_of_thoth", "src-bot")
    replace_source(conn, bot, [_chunk(bot.id, "the_fool", "Tier 0 text about the Fool")])

    hits = retrieve_for_card(conn, "the_fool")
    assert len(hits) == 1
    assert hits[0].chunk.source_id == bot.id


def test_retrieve_for_card_unknown_card_returns_empty(conn):
    assert retrieve_for_card(conn, "nonexistent_card") == []


def test_search_finds_matching_chunk_by_text(conn):
    bot = _source("book_of_thoth", "src-bot")
    replace_source(
        conn,
        bot,
        [
            _chunk(bot.id, "the_fool", "This card is attributed to the letter Aleph."),
            _chunk(bot.id, "the_magus", "This card is attributed to the letter Beth."),
        ],
    )
    hits = search(conn, "Aleph")
    assert len(hits) == 1
    assert hits[0].chunk.card_id == "the_fool"
    assert hits[0].retrieval_method == "fts"
    assert hits[0].score is not None


def test_search_respects_limit(conn):
    bot = _source("book_of_thoth", "src-bot")
    chunks = [_chunk(bot.id, f"card_{i}", "shared search term appears here") for i in range(5)]
    replace_source(conn, bot, chunks)

    hits = search(conn, "shared", limit=2)
    assert len(hits) == 2
