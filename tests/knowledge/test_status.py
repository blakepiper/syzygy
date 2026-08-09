"""The four source states, and the one that is routinely misread (M18.1d).

"Citations only" is what a healthy fresh install looks like; "broken" is
the only state worth acting on. Before `syzygy.knowledge.status` these
rendered identically in `doctor`, which is how "no source chunks were
supplied to the model" read as a fault rather than as the arrangement.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from syzygy.domain.knowledge import KnowledgeChunk, KnowledgeSource
from syzygy.knowledge.ingest import INGESTION_VERSIONS
from syzygy.knowledge.status import (
    SourceState,
    any_full_text,
    broken,
    set_source_note_dismissed,
    source_note_dismissed,
    source_statuses,
)
from syzygy.knowledge.store import replace_source
from syzygy.storage.database import connect
from syzygy.storage.migrations import apply_all

NOW = datetime(2026, 8, 9, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "test.db")
    apply_all(connection)
    yield connection
    connection.close()


def _install(conn, source_type, chunks, *, version=None):
    replace_source(
        conn,
        KnowledgeSource(
            id=f"src-{source_type}",
            source_type=source_type,
            title=f"Title of {source_type}",
            file_hash="0" * 64,
            ingestion_version=version or INGESTION_VERSIONS[source_type],
            created_at_utc=NOW,
        ),
        chunks,
    )


def _chunk(source_type, index, *, text, card_id="the_fool"):
    return KnowledgeChunk(
        id=f"{source_type}-{index}",
        source_id=f"src-{source_type}",
        section_id="sec",
        section_type="card",
        card_id=card_id,
        title="The Fool",
        page_start=10,
        page_end=12,
        chunk_index=index,
        text=text,
        text_hash=f"h-{index}",
    )


def _state(conn, source_type):
    return next(s for s in source_statuses(conn) if s.source_type == source_type)


def test_an_unknown_source_is_absent(conn):
    assert all(status.state is SourceState.ABSENT for status in source_statuses(conn))
    assert any_full_text(source_statuses(conn)) is False
    assert broken(source_statuses(conn)) == []


def test_citations_with_no_text_are_the_normal_state_not_a_fault(conn):
    _install(conn, "book_of_thoth", [_chunk("book_of_thoth", 0, text="")])

    status = _state(conn, "book_of_thoth")
    assert status.state is SourceState.CITATIONS_ONLY
    assert status.detail is None
    assert status.has_text is False
    assert broken(source_statuses(conn)) == []


def test_passages_present_reads_as_full_text(conn):
    _install(conn, "book_of_thoth", [_chunk("book_of_thoth", 0, text="Aleph, the Fool.")])

    status = _state(conn, "book_of_thoth")
    assert status.state is SourceState.FULL_TEXT
    assert status.text_chunk_count == 1
    assert any_full_text(source_statuses(conn)) is True


def test_a_registered_source_with_no_chunks_is_broken(conn):
    _install(conn, "book_of_thoth", [])

    status = _state(conn, "book_of_thoth")
    assert status.state is SourceState.BROKEN
    assert "no chunks" in (status.detail or "")


def test_chunks_mapped_to_no_card_are_broken(conn):
    _install(conn, "book_of_thoth", [_chunk("book_of_thoth", 0, text="prose", card_id=None)])

    status = _state(conn, "book_of_thoth")
    assert status.state is SourceState.BROKEN
    assert "card" in (status.detail or "")


def test_an_out_of_date_ingestion_version_is_broken_not_merely_old(conn):
    _install(
        conn, "book_of_thoth", [_chunk("book_of_thoth", 0, text="prose")], version="v0-ancient"
    )

    status = _state(conn, "book_of_thoth")
    assert status.state is SourceState.BROKEN
    assert "re-ingest" in (status.detail or "")


def test_tiers_come_from_the_domain_table(conn):
    statuses = source_statuses(conn)
    assert statuses[0].source_type == "book_of_thoth"
    assert statuses[0].tier == 0
    assert {status.tier for status in statuses[1:]} == {1}


def test_the_home_note_preference_round_trips(tmp_path):
    settings = tmp_path / "settings.json"
    assert source_note_dismissed(settings) is False
    assert source_note_dismissed(None) is False

    set_source_note_dismissed(settings, True)
    assert source_note_dismissed(settings) is True

    set_source_note_dismissed(settings, False)
    assert source_note_dismissed(settings) is False


def test_dismissing_the_note_leaves_other_settings_sections_alone(tmp_path):
    """`syzygy.settings`' whole reason for existing - a preference added
    later must not destroy one added earlier."""
    import json

    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"audio": {"muted": True}}))

    set_source_note_dismissed(settings, True)

    assert json.loads(settings.read_text())["audio"] == {"muted": True}
