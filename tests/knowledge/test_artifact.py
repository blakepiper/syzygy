"""The bundled citations-and-vectors index (M13.3).

The decision this milestone implements is recorded in
`docs/adr/0003-ship-derived-knowledge-index-without-source-text.md`: ship
derived data, never the passages. Several tests here exist specifically to
keep that promise mechanically rather than by review - most importantly
`test_the_committed_index_contains_no_prose`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib import resources

import numpy as np
import pytest

from syzygy.domain.knowledge import KnowledgeChunk, KnowledgeSource
from syzygy.knowledge.artifact import (
    ARTIFACT_VERSION,
    ArtifactError,
    build_artifact,
    chunk_vectors,
    ensure_knowledge_base,
    install_artifact,
    load_bundled_artifact,
    normalize_title,
    parse_artifact,
)
from syzygy.knowledge.embedding import DIMENSIONS, VECTOR_VERSION, lexical_vector
from syzygy.knowledge.retrieve import retrieve_for_card, search, search_vectors
from syzygy.knowledge.store import get_source_by_type, has_full_text, replace_source
from syzygy.storage.database import connect
from syzygy.storage.migrations import apply_all

NOW = datetime(2026, 8, 8, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path):
    """A migrated database with *no* artifact installed - `connect` plus
    `apply_all`, not `open_database`, which would install one."""
    connection = connect(tmp_path / "test.db")
    apply_all(connection)
    yield connection
    connection.close()


def _source(source_type: str, source_id: str) -> KnowledgeSource:
    return KnowledgeSource(
        id=source_id,
        source_type=source_type,
        title=f"Title of {source_type}",
        file_hash=f"hash-{source_id}",
        ingestion_version="v1",
        created_at_utc=NOW,
    )


def _chunk(source_id: str, card_id: str, text: str, chunk_index: int = 0) -> KnowledgeChunk:
    import hashlib

    return KnowledgeChunk(
        id=f"chunk-{source_id}-{card_id}-{chunk_index}",
        source_id=source_id,
        section_id=f"sec-{source_id}-{card_id}",
        section_type="card",
        card_id=card_id,
        title=f"Heading for {card_id}",
        page_start=10 + chunk_index,
        page_end=12 + chunk_index,
        chunk_index=chunk_index,
        text=text,
        text_hash=hashlib.sha256(text.encode()).hexdigest(),
    )


def _ingested(conn) -> None:
    replace_source(
        conn,
        _source("book_of_thoth", "s0"),
        [
            _chunk("s0", "the_fool", "The Fool is the negative issuing into manifestation."),
            _chunk("s0", "the_fool", "Folly and innocence walk the cliff edge.", chunk_index=1),
            _chunk("s0", "the_magus", "The Magus is the messenger of the gods."),
        ],
    )
    replace_source(
        conn,
        _source("duquette_companion", "s1"),
        [_chunk("s1", "the_fool", "DuQuette on the Fool: a commentary passage.")],
    )


# -- what the artifact carries -------------------------------------------


def test_build_produces_a_citation_per_chunk_and_no_text(conn):
    _ingested(conn)
    artifact = build_artifact(conn)

    assert len(artifact.chunks) == 4
    assert {source.source_type for source in artifact.sources} == {
        "book_of_thoth",
        "duquette_companion",
    }
    # The type simply has nowhere to put text.
    assert not any(hasattr(chunk, "text") for chunk in artifact.chunks)
    assert "negative issuing into manifestation" not in artifact.index_json()


def test_build_records_word_counts_and_hashes_but_not_words(conn):
    _ingested(conn)
    artifact = build_artifact(conn)
    chunk = next(c for c in artifact.chunks if c.card_id == "the_magus")

    assert chunk.word_count == 8
    assert len(chunk.text_hash) == 64
    assert chunk.page_start == 10


def test_vectors_are_unit_length_and_correctly_shaped(conn):
    _ingested(conn)
    artifact = build_artifact(conn)

    assert artifact.vectors.shape == (4, DIMENSIONS)
    assert artifact.vectors.dtype == np.float32
    norms = np.linalg.norm(artifact.vectors, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)


def test_building_without_any_ingested_source_is_an_error(conn):
    with pytest.raises(ArtifactError, match="no ingested sources"):
        build_artifact(conn)


def test_a_mismatched_vector_matrix_is_rejected(conn):
    from io import BytesIO

    _ingested(conn)
    artifact = build_artifact(conn)

    wrong = BytesIO()
    np.save(wrong, np.zeros((2, DIMENSIONS), np.float32), allow_pickle=False)

    with pytest.raises(ArtifactError, match="does not match"):
        parse_artifact(artifact.index_json(), wrong.getvalue())


# -- reproducibility (M13.3e) --------------------------------------------


def test_rebuilding_is_byte_identical(conn):
    """The committed artifact has to be auditable against its inputs, so
    a rebuild from the same database must not differ."""
    _ingested(conn)
    first = build_artifact(conn)
    second = build_artifact(conn)

    assert first.index_json() == second.index_json()
    assert first.vectors_bytes() == second.vectors_bytes()


def test_ids_do_not_depend_on_the_databases_own_uuids(tmp_path):
    """`ingest` assigns `uuid4` ids; the artifact must not inherit them or
    every rebuild would differ."""
    artifacts = []
    for name in ("a.db", "b.db"):
        connection = connect(tmp_path / name)
        apply_all(connection)
        _ingested(connection)
        artifacts.append(build_artifact(connection))
        connection.close()

    assert artifacts[0].index_json() == artifacts[1].index_json()


def test_round_trips_through_its_serialized_form(conn):
    _ingested(conn)
    artifact = build_artifact(conn)
    restored = parse_artifact(artifact.index_json(), artifact.vectors_bytes())

    assert restored.chunks == artifact.chunks
    assert restored.sources == artifact.sources
    assert np.array_equal(restored.vectors, artifact.vectors)


def test_an_artifact_from_a_different_vector_scheme_is_refused(conn):
    _ingested(conn)
    artifact = build_artifact(conn)
    raw = json.loads(artifact.index_json())
    raw["vector_version"] = "some-other-scheme"

    with pytest.raises(ArtifactError, match="lexical-v1"):
        parse_artifact(json.dumps(raw), artifact.vectors_bytes())


# -- installing ------------------------------------------------------------


def test_install_writes_citations_with_empty_text(conn):
    source_conn = conn
    _ingested(source_conn)
    artifact = build_artifact(source_conn)

    fresh = connect(":memory:")
    apply_all(fresh)
    result = install_artifact(fresh, artifact, now=NOW)

    assert set(result.installed) == {"book_of_thoth", "duquette_companion"}
    assert result.chunk_count == 4
    rows = fresh.execute("SELECT text, vector, word_count FROM knowledge_chunks").fetchall()
    assert all(row["text"] == "" for row in rows)
    assert all(row["vector"] is not None for row in rows)
    assert all(row["word_count"] > 0 for row in rows)
    fresh.close()


def test_install_never_overwrites_locally_ingested_text(conn):
    """The real passages always win over the shipped citations."""
    _ingested(conn)
    artifact = build_artifact(conn)

    result = install_artifact(conn, artifact, now=NOW)

    assert result.installed == ()
    assert set(result.skipped) == {"book_of_thoth", "duquette_companion"}
    assert has_full_text(conn, "s0")


def test_installed_chunks_are_retrievable_by_card(conn):
    _ingested(conn)
    artifact = build_artifact(conn)

    fresh = connect(":memory:")
    apply_all(fresh)
    install_artifact(fresh, artifact, now=NOW)

    hits = retrieve_for_card(fresh, "the_fool")
    assert len(hits) == 3
    assert all(not hit.chunk.has_text for hit in hits)
    assert all(hit.chunk.citation for hit in hits)
    # Tier 0 still comes first.
    assert hits[0].chunk.source_id == get_source_by_type(fresh, "book_of_thoth").id
    fresh.close()


def test_fts_finds_nothing_on_a_citation_only_install(conn):
    """Correct, not broken: FTS5 indexes text, and there is none."""
    _ingested(conn)
    artifact = build_artifact(conn)

    fresh = connect(":memory:")
    apply_all(fresh)
    install_artifact(fresh, artifact, now=NOW)

    assert search(fresh, "folly") == []
    fresh.close()


def test_vector_search_works_on_a_citation_only_install(conn):
    """The reason the vectors ship at all."""
    _ingested(conn)
    artifact = build_artifact(conn)

    fresh = connect(":memory:")
    apply_all(fresh)
    install_artifact(fresh, artifact, now=NOW)

    hits = search_vectors(fresh, "folly innocence cliff", limit=3)
    assert hits
    assert hits[0].chunk.card_id == "the_fool"
    assert hits[0].retrieval_method == "semantic"
    assert 0 < hits[0].score <= 1.0
    fresh.close()


def test_a_query_sharing_no_vocabulary_returns_nothing(conn):
    _ingested(conn)
    assert search_vectors(conn, "kubernetes helm chart", limit=5) == []


def test_an_all_stopword_query_returns_nothing(conn):
    _ingested(conn)
    assert search_vectors(conn, "the and of", limit=5) == []


def test_chunk_vectors_skips_a_stale_vector_scheme(conn):
    _ingested(conn)
    conn.execute("UPDATE knowledge_chunks SET vector_version = 'ancient-v0'")

    ids, matrix = chunk_vectors(conn)
    assert ids == []
    assert matrix.shape == (0, DIMENSIONS)


# -- the committed artifact ------------------------------------------------


def test_the_package_ships_an_artifact():
    artifact = load_bundled_artifact()
    assert artifact is not None
    assert {source.source_type for source in artifact.sources} == {
        "book_of_thoth",
        "duquette_companion",
        "ziegler_mirror_of_soul",
    }
    assert len(artifact.chunks) == len(artifact.vectors)


def test_the_committed_index_covers_all_78_cards():
    artifact = load_bundled_artifact()
    assert artifact is not None
    from syzygy.sortes.deck import load_deck

    covered = {chunk.card_id for chunk in artifact.chunks if chunk.card_id}
    assert covered == {card.id for card in load_deck()}


def test_the_committed_index_contains_no_prose():
    """The promise of ADR 0003, enforced rather than reviewed.

    Every string in the index is an identifier, a hash, or a heading. No
    field may hold a sentence, so none may be long or contain the
    sentence-shaped punctuation that prose does.
    """
    raw = json.loads(
        resources.files("syzygy.resources")
        .joinpath("knowledge/index.json")
        .read_text(encoding="utf-8")
    )
    for chunk in raw["chunks"]:
        title = chunk["title"]
        assert len(title) <= 80, f"suspiciously long title: {title!r}"
        assert "\n" not in title
        for key, value in chunk.items():
            if key == "title":
                continue
            assert not isinstance(value, str) or len(value) <= 96, f"{key} is too long"


def test_the_committed_vectors_match_the_committed_index():
    artifact = load_bundled_artifact()
    assert artifact is not None
    assert artifact.vectors.shape == (len(artifact.chunks), DIMENSIONS)
    assert np.allclose(np.linalg.norm(artifact.vectors, axis=1), 1.0, atol=1e-4)


def test_the_committed_artifact_declares_the_current_versions():
    raw = json.loads(
        resources.files("syzygy.resources")
        .joinpath("knowledge/index.json")
        .read_text(encoding="utf-8")
    )
    assert raw["artifact_version"] == ARTIFACT_VERSION
    assert raw["vector_version"] == VECTOR_VERSION
    assert raw["dimensions"] == DIMENSIONS


# -- first run --------------------------------------------------------------


def test_a_fresh_database_self_populates(tmp_path):
    from syzygy.storage.database import open_database

    connection = open_database(tmp_path / "fresh.db")
    try:
        total = connection.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
        assert total > 0
        hits = retrieve_for_card(connection, "the_fool")
        assert hits
        assert all(not hit.chunk.has_text for hit in hits)
    finally:
        connection.close()


def test_opening_an_existing_database_twice_does_not_duplicate(tmp_path):
    from syzygy.storage.database import open_database

    first = open_database(tmp_path / "fresh.db")
    count = first.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
    first.close()

    second = open_database(tmp_path / "fresh.db")
    try:
        assert second.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0] == count
    finally:
        second.close()


def test_ensure_is_a_no_op_when_everything_is_present(tmp_path):
    from syzygy.storage.database import open_database

    connection = open_database(tmp_path / "fresh.db")
    try:
        result = ensure_knowledge_base(connection, now=NOW)
        assert result.installed == ()
        assert len(result.skipped) == 3
    finally:
        connection.close()


# -- titles -----------------------------------------------------------------


def test_normalize_title_collapses_whitespace():
    assert normalize_title("  0. THE\n FOOL  ") == "0. THE FOOL"


def test_normalize_title_recovers_a_heading_swept_up_with_prose():
    """The segmenters occasionally take a run-on line as a heading, which
    would put a sentence of the source into a redistributed file."""
    messy = (
        "general effect is one of intense strain; yet the symbol implies "
        "long-continued\ninaction. / SIX OF DISKS"
    )
    assert normalize_title(messy) == "SIX OF DISKS"


def test_normalize_title_truncates_when_there_is_no_heading_to_recover():
    long_title = "word " * 40
    normalized = normalize_title(long_title)
    assert len(normalized) <= 80
    assert normalized.endswith("…")


# -- the vectorizer ---------------------------------------------------------


def test_vectors_are_stable_across_processes():
    """`blake2b`, never Python's salted `hash()` - otherwise the committed
    vectors would not match freshly computed query vectors."""
    import subprocess
    import sys

    code = (
        "from syzygy.knowledge.embedding import lexical_vector;"
        "print(lexical_vector('the fool walks the cliff edge')[:4].tolist())"
    )
    outputs = {
        subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
            env={"PYTHONHASHSEED": seed, "PATH": ""},
        ).stdout
        for seed in ("0", "1", "random")
    }
    assert len(outputs) == 1


def test_similar_text_scores_higher_than_unrelated_text():
    from syzygy.knowledge.embedding import similarities

    query = lexical_vector("the fool folly innocence")
    close = lexical_vector("folly and innocence are the fool's gifts")
    far = lexical_vector("saturn square venus applying orb degrees")

    scores = similarities(query, np.vstack([close, far]))
    assert scores[0] > scores[1]


def test_an_empty_text_vectorizes_to_zero():
    assert not lexical_vector("").any()
    assert not lexical_vector("the and of").any()
