"""M18.1e: on a bare install, "where this card is discussed" is never empty.

The whole of M18.1b rests on this. If the shipped artifact missed even one
of the 78 cards, that card's reading would show an empty passages list
*and* an empty citations list - which is exactly the unexplained dead end
the milestone exists to remove, reintroduced for one card in seventy-eight
and invisible until somebody drew it.

Everything here runs against the artifact that actually ships, installed
into a fresh database the way `open_database` installs it on first launch,
with no PDF anywhere.
"""

from __future__ import annotations

import pytest

from syzygy.domain.knowledge import TIER_0_SOURCE_TYPE, RetrievedCitation
from syzygy.knowledge.artifact import load_bundled_artifact
from syzygy.knowledge.retrieve import retrieve_for_card
from syzygy.sortes.deck import load_deck
from syzygy.storage.database import open_database

pytestmark = pytest.mark.skipif(
    load_bundled_artifact() is None, reason="this build ships no knowledge artifact"
)


@pytest.fixture
def conn(tmp_path):
    """A first launch: migrations applied, bundled citations installed."""
    connection = open_database(tmp_path / "fresh.db")
    yield connection
    connection.close()


def test_every_card_has_at_least_one_tier_0_citation(conn):
    missing = []
    for card in load_deck():
        citations = [RetrievedCitation.from_hit(hit) for hit in retrieve_for_card(conn, card.id)]
        if not any(citation.tier == 0 for citation in citations):
            missing.append(card.id)
    assert missing == []


def test_the_canonical_source_is_returned_first_for_every_card(conn):
    for card in load_deck():
        hits = retrieve_for_card(conn, card.id)
        assert hits, card.id
        assert hits[0].source_type == TIER_0_SOURCE_TYPE, card.id


def test_a_bare_install_carries_citations_and_no_passages(conn):
    """The shipped artifact is citations and vectors, never text
    (ADR 0003) - so every hit on a fresh install is unsendable, and the
    citation list is populated anyway."""
    hits = retrieve_for_card(conn, "the_fool")
    assert hits
    assert all(not hit.chunk.has_text for hit in hits)
    citations = [RetrievedCitation.from_hit(hit) for hit in hits]
    assert all(not citation.text_available for citation in citations)
    assert all(citation.page_start > 0 for citation in citations)
