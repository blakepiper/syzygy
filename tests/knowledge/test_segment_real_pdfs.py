"""Golden tests against the real source PDFs (M6.8).

The PDFs are local reference copies, not committed to the repository
(`.gitignore`: `docs/*.pdf` - see docs/KNOWLEDGE_SOURCES.md section 1.2).
Every test here is skipped when a given PDF is absent, so the suite stays
green on a fresh checkout; run these for real confidence whenever the
source files are present locally (as they were for the session that
authored this module).
"""

from datetime import UTC, datetime
from pathlib import Path

import pymupdf
import pytest

from syzygy.knowledge.ingest import ingest
from syzygy.knowledge.retrieve import retrieve_for_card
from syzygy.knowledge.segment import segment_book_of_thoth, segment_duquette, segment_ziegler
from syzygy.sortes.deck import load_deck
from syzygy.storage.database import connect
from syzygy.storage.migrations import apply_all

_BOOK_OF_THOTH = Path("docs/book_of_thoth.pdf")
_DUQUETTE = Path("docs/understanding_crowley_thoth_tarot.pdf")
_ZIEGLER = Path("docs/mirror_of_the_soul.pdf")

_ALL_CARD_IDS = {c.id for c in load_deck()}

requires_book_of_thoth = pytest.mark.skipif(
    not _BOOK_OF_THOTH.exists(), reason="docs/book_of_thoth.pdf not present locally"
)
requires_duquette = pytest.mark.skipif(
    not _DUQUETTE.exists(), reason="docs/understanding_crowley_thoth_tarot.pdf not present locally"
)
requires_ziegler = pytest.mark.skipif(
    not _ZIEGLER.exists(), reason="docs/mirror_of_the_soul.pdf not present locally"
)
requires_all_three = pytest.mark.skipif(
    not (_BOOK_OF_THOTH.exists() and _DUQUETTE.exists() and _ZIEGLER.exists()),
    reason="not all three source PDFs are present locally",
)


def _card_sections(sections):
    return {s.card_id: s for s in sections if s.section_type == "card"}


@requires_book_of_thoth
def test_book_of_thoth_maps_every_card_exactly_once():
    doc = pymupdf.open(_BOOK_OF_THOTH)
    sections = segment_book_of_thoth(doc)
    by_card = _card_sections(sections)
    assert set(by_card) == _ALL_CARD_IDS


@requires_book_of_thoth
def test_book_of_thoth_major_minor_court_representative_retrieval():
    doc = pymupdf.open(_BOOK_OF_THOTH)
    by_card = _card_sections(segment_book_of_thoth(doc))

    major = by_card["the_high_priestess"]
    assert "letter Gimel" in major.text

    minor = by_card["two_of_wands"]
    assert "TWO OF WANDS" in minor.text.upper()
    assert "Chokmah" in minor.text

    court = by_card["knight_of_wands"]
    assert "KNIGHT OF WANDS" in court.text.upper()


@requires_book_of_thoth
def test_book_of_thoth_alias_resolution_the_juggler():
    # The Book of Thoth's own heading for The Magus reads "I. THE JUGGLER"
    # (docs/THOTH_INGESTION_MAP.md section 10) - this only maps to
    # `the_magus` via its book_of_thoth_aliases entry, not its
    # display_name, so this is a real test of alias resolution.
    doc = pymupdf.open(_BOOK_OF_THOTH)
    by_card = _card_sections(segment_book_of_thoth(doc))
    assert "the_magus" in by_card
    assert "JUGGLER" in by_card["the_magus"].text.upper()


@requires_book_of_thoth
def test_book_of_thoth_no_chunk_crosses_a_card_section_boundary():
    doc = pymupdf.open(_BOOK_OF_THOTH)
    by_card = _card_sections(segment_book_of_thoth(doc))
    two_of_wands = by_card["two_of_wands"].text.upper()
    # Neither its heading neighbor (Ace of Wands, immediately before) nor
    # the next numbered card's heading should leak into this section.
    assert "ACE OF WANDS" not in two_of_wands
    assert "THREE OF WANDS" not in two_of_wands


@requires_duquette
def test_duquette_maps_every_card_exactly_once():
    doc = pymupdf.open(_DUQUETTE)
    by_card = _card_sections(segment_duquette(doc))
    assert set(by_card) == _ALL_CARD_IDS


@requires_ziegler
def test_ziegler_maps_every_card_exactly_once():
    doc = pymupdf.open(_ZIEGLER)
    by_card = _card_sections(segment_ziegler(doc))
    assert set(by_card) == _ALL_CARD_IDS


@requires_ziegler
def test_ziegler_alias_resolution_the_priestess():
    # Ziegler titles the_high_priestess "The Priestess", not the Book of
    # Thoth's "The High Priestess" - a companion-source-local alias
    # override (docs/KNOWLEDGE_SOURCES.md section 4.2), not a change to
    # thoth_deck.yaml.
    doc = pymupdf.open(_ZIEGLER)
    by_card = _card_sections(segment_ziegler(doc))
    assert "the_high_priestess" in by_card


@requires_all_three
def test_tier_0_ranked_ahead_of_tier_1_end_to_end(tmp_path):
    conn = connect(tmp_path / "test.db")
    apply_all(conn)
    now = datetime.now(UTC)
    for path in (_BOOK_OF_THOTH, _DUQUETTE, _ZIEGLER):
        ingest(conn, path, now=now)

    hits = retrieve_for_card(conn, "the_fool")
    assert len(hits) > 0
    source_types = dict(
        conn.execute("SELECT id, source_type FROM knowledge_sources").fetchall()
    )
    tiers = [source_types[hit.chunk.source_id] for hit in hits]
    first_tier1_index = next(
        (i for i, t in enumerate(tiers) if t != "book_of_thoth"), len(tiers)
    )
    # every book_of_thoth hit precedes every non-book_of_thoth hit
    assert all(t == "book_of_thoth" for t in tiers[:first_tier1_index])
    assert all(t != "book_of_thoth" for t in tiers[first_tier1_index:])
    conn.close()


@requires_book_of_thoth
def test_tier_0_only_ingestion_unaffected_by_absent_companions(tmp_path):
    conn = connect(tmp_path / "test.db")
    apply_all(conn)
    now = datetime.now(UTC)
    ingest(conn, _BOOK_OF_THOTH, now=now)

    hits = retrieve_for_card(conn, "the_fool")
    assert len(hits) > 0
    assert all(hit.chunk.card_id == "the_fool" for hit in hits)
    conn.close()
