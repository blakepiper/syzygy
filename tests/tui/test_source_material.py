"""Source material end to end (M18.1b-f).

The complaint: a daily reading reported "no source chunks were supplied
to the model" and stopped there. These tests pin the three halves of the
answer - the `[I]` view's two lists, home saying so before the draw, and
`[K]` being a route to fixing it that cannot ingest an arbitrary file.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from textual.widgets import Button, Input, Static

from syzygy.domain.knowledge import KnowledgeChunk, KnowledgeSource
from syzygy.knowledge.ingest import SourceFileMismatchError, verify_known_source_file
from syzygy.knowledge.status import source_note_dismissed
from syzygy.knowledge.store import replace_source
from syzygy.sortes.deck import load_deck
from syzygy.tui.app import SyzygyApp, SyzygyServices
from syzygy.tui.screens.home import HomeScreen
from syzygy.tui.screens.source_material import SourceMaterialScreen
from syzygy.tui.widgets.reading_panel import NO_PASSAGES_ACTION, NO_PASSAGES_NOTE

from .test_ritual_flow import q, settle, text_of, turn_the_wheel

NOW = datetime(2026, 8, 9, tzinfo=UTC)


def install_for_every_card(conn, source_type: str, *, with_text: bool) -> None:
    """One chunk per card, so a test does not have to know which card the
    wheel will draw - the draw is real entropy and must stay that way."""
    replace_source(
        conn,
        KnowledgeSource(
            id=f"src-{source_type}",
            source_type=source_type,
            title=f"Book of {source_type}",
            file_hash="0" * 64,
            ingestion_version="v1",
            created_at_utc=NOW,
        ),
        [
            KnowledgeChunk(
                id=f"{source_type}-{card.id}",
                source_id=f"src-{source_type}",
                section_id=card.id,
                section_type="card",
                card_id=card.id,
                title=card.full_name,
                page_start=100,
                page_end=104,
                chunk_index=0,
                text=f"A passage about {card.full_name}." if with_text else "",
                text_hash=f"h-{card.id}",
            )
            for card in load_deck()
        ],
    )


async def inputs_view(pilot) -> str:
    await turn_the_wheel(pilot)
    await pilot.press("i")
    await pilot.pause()
    return text_of(q(pilot, "#reading-body", Static))


# -- the two lists (M18.1b) -------------------------------------------------


async def test_citation_only_install_shows_where_the_card_is_discussed(
    app: SyzygyApp, profile, conn
):
    install_for_every_card(conn, "book_of_thoth", with_text=False)
    async with app.run_test() as pilot:
        await settle(pilot)
        body = await inputs_view(pilot)

    assert "PASSAGES SENT TO THE MODEL" in body
    assert NO_PASSAGES_NOTE in body
    assert NO_PASSAGES_ACTION in body
    # ...and the list that is always populated, which is the point.
    assert "WHERE THIS CARD IS DISCUSSED" in body
    assert "pages 100-104" in body
    assert "canonical" in body
    assert "citation only" in body


async def test_ingested_passages_reach_the_model_and_both_lists_agree(
    app: SyzygyApp, profile, conn
):
    """M18.1f. With text installed the prompt is populated, and the `[I]`
    view's two lists describe the same chunks."""
    install_for_every_card(conn, "book_of_thoth", with_text=True)
    async with app.run_test() as pilot:
        await settle(pilot)
        body = await inputs_view(pilot)
        reading = pilot.app.screen.reading

    assert NO_PASSAGES_NOTE not in body
    context = reading.interpretation_context
    assert context is not None
    assert len(context.knowledge_chunks) == 1
    sent = context.knowledge_chunks[0]
    assert sent.text
    assert sent.id in body

    # The prompt the provider would build actually carries the passage.
    from syzygy.interpretation.prompts import build_user_prompt

    prompt = build_user_prompt(context)
    assert "SOURCE PASSAGES" in prompt
    assert "none supplied" not in prompt
    assert sent.text in prompt

    # Both lists, one set of chunks.
    assert [citation.chunk_id for citation in reading.retrieved_citations] == [sent.id]
    assert reading.retrieved_citations[0].text_available is True


async def test_tier_0_is_listed_before_tier_1(app: SyzygyApp, profile, conn):
    install_for_every_card(conn, "ziegler_mirror_of_soul", with_text=True)
    install_for_every_card(conn, "book_of_thoth", with_text=True)
    async with app.run_test() as pilot:
        await settle(pilot)
        await turn_the_wheel(pilot)
        reading = pilot.app.screen.reading

    assert [citation.tier for citation in reading.retrieved_citations] == [0, 1]
    context = reading.interpretation_context
    assert context is not None
    assert context.knowledge_chunks[0].id.startswith("book_of_thoth-")


# -- the home note (M18.1d) -------------------------------------------------


async def test_home_says_so_before_the_draw(app: SyzygyApp, profile, conn):
    install_for_every_card(conn, "book_of_thoth", with_text=False)
    async with app.run_test() as pilot:
        await settle(pilot)
        note = q(pilot, "#home-sources", Static)
        assert note.display
        assert "[K]" in text_of(note)


async def test_the_note_disappears_once_passages_are_installed(
    app: SyzygyApp, profile, conn
):
    install_for_every_card(conn, "book_of_thoth", with_text=True)
    async with app.run_test() as pilot:
        await settle(pilot)
        assert q(pilot, "#home-sources", Static).display is False


async def test_the_note_can_be_dismissed_for_good(services: SyzygyServices, profile, tmp_path):
    install_for_every_card(services.conn, "book_of_thoth", with_text=False)
    settings = tmp_path / "settings.json"
    services.settings_path = settings

    async with SyzygyApp(services).run_test() as pilot:
        await settle(pilot)
        assert q(pilot, "#home-sources", Static).display
        await pilot.press("k")
        await settle(pilot)
        q(pilot, "#source-dismiss", Button).press()
        await settle(pilot)
        assert source_note_dismissed(settings) is True
        await pilot.press("escape")
        await settle(pilot)
        assert isinstance(pilot.app.screen, HomeScreen)
        assert q(pilot, "#home-sources", Static).display is False


# -- the screen (M18.1c) ----------------------------------------------------


async def test_k_opens_source_material_and_reports_every_source(
    app: SyzygyApp, profile, conn
):
    install_for_every_card(conn, "book_of_thoth", with_text=False)
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("k")
        await settle(pilot)
        assert isinstance(pilot.app.screen, SourceMaterialScreen)

        listing = text_of(q(pilot, "#source-list", Static))
        assert "citations only" in listing
        assert listing.count("not present") == 2  # the two uningested companions
        expected = text_of(q(pilot, "#source-expected", Static))
        assert "book_of_thoth.pdf" in expected
        assert "understanding_crowley_thoth_tarot.pdf" in expected
        assert "mirror_of_the_soul.pdf" in expected


async def test_a_missing_file_is_reported_not_ingested(app: SyzygyApp, profile, tmp_path):
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("k")
        await settle(pilot)
        q(pilot, "#source-path", Input).value = str(tmp_path / "nope.pdf")
        q(pilot, "#source-ingest", Button).press()
        await settle(pilot)
        assert "No such file" in text_of(q(pilot, "#source-message", Static))


async def test_a_file_that_is_not_a_known_edition_is_refused(
    app: SyzygyApp, profile, tmp_path
):
    """M18.1c's hard rule. Every shipped citation's page range is one
    edition's pagination; ingesting a different scan under the same source
    would silently repoint all of them."""
    impostor = tmp_path / "book_of_thoth.pdf"
    impostor.write_bytes(b"not the book")

    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("k")
        await settle(pilot)
        q(pilot, "#source-path", Input).value = str(impostor)
        q(pilot, "#source-ingest", Button).press()
        await settle(pilot)
        message = text_of(q(pilot, "#source-message", Static))
        assert "not the edition" in message
        assert "syzygy knowledge ingest" in message


def test_verification_accepts_only_the_recorded_hash(tmp_path):
    path = tmp_path / "book_of_thoth.pdf"
    path.write_bytes(b"still not the book")
    with pytest.raises(SourceFileMismatchError):
        verify_known_source_file(path)


def test_verification_refuses_a_file_it_cannot_name(tmp_path):
    from syzygy.knowledge.ingest import UnknownSourceTypeError

    path = tmp_path / "some_other_book.pdf"
    path.write_bytes(b"x")
    with pytest.raises(UnknownSourceTypeError):
        verify_known_source_file(path)
