"""The Oracle in the interface: one rite, two objects, no mode (M22.4)."""

from __future__ import annotations

from datetime import UTC, datetime

from textual.widgets import ListView, Static

from syzygy.domain.consultation import ConsultationStatus
from syzygy.iching.book import get_hexagram
from syzygy.storage.consultations import list_consultations
from syzygy.tui.app import SyzygyApp
from syzygy.tui.screens.archive import (
    ArchiveScreen,
    ConsultationListItem,
    IChingListItem,
    OracleListItem,
)
from syzygy.tui.screens.consultation_result import ConsultationResultScreen
from syzygy.tui.screens.home import HomeScreen
from syzygy.tui.screens.oracle_ask import OracleAskScreen
from syzygy.tui.screens.wheel import WheelScreen

from .test_ritual_flow import q, settle, text_of

NOW = datetime(2026, 8, 9, 12, tzinfo=UTC)


async def complete_oracle(pilot, question: str = "What needs my attention?") -> None:
    await pilot.press("o")
    await settle(pilot)
    assert isinstance(pilot.app.screen, OracleAskScreen)
    for character in question:
        await pilot.press("space" if character == " " else character)
    await pilot.press("enter")
    await settle(pilot)
    assert isinstance(pilot.app.screen, WheelScreen)
    for _ in range(3):
        await pilot.press("space")
    await pilot.press("enter")
    await settle(pilot, 6)
    assert isinstance(pilot.app.screen, ConsultationResultScreen)


async def test_one_question_yields_one_card_and_one_cast(
    app: SyzygyApp, profile, conn
) -> None:
    async with app.run_test() as pilot:
        await settle(pilot)
        assert isinstance(pilot.app.screen, HomeScreen)
        await complete_oracle(pilot)

        screen = pilot.app.screen
        assert isinstance(screen, ConsultationResultScreen)
        consultation = screen.consultation
        assert consultation.status is ConsultationStatus.COMPLETE
        assert consultation.card_draw is not None
        assert consultation.cast is not None
        assert consultation.result is not None
        assert "What needs my attention?" in text_of(q(pilot, "#consultation-question", Static))
        assert "RESPONSE" in text_of(q(pilot, "#consultation-body", Static))

        # Both objects are legible at a glance, and so is whether anything
        # is moving.
        primary = get_hexagram(consultation.cast.primary_hexagram_number)
        assert primary.name in text_of(q(pilot, "#consultation-hexagram", Static))
        assert len(pilot.app.screen.query(".cast-line")) == 6
        movement = text_of(q(pilot, "#consultation-movement", Static))
        assert ("moving at line" in movement) is bool(consultation.cast.changing_lines)

        from syzygy.storage.readings import list_readings

        assert list_readings(conn, profile.id) == []
        stored = list_consultations(conn, profile.id)
        assert len(stored) == 1
        assert stored[0].card_draw == consultation.card_draw
        assert stored[0].cast == consultation.cast


async def test_the_ask_screen_offers_no_mode_choice(app: SyzygyApp, profile) -> None:
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("o")
        await settle(pilot)
        ask = pilot.app.screen
        assert isinstance(ask, OracleAskScreen)

        assert not ask.query("#iching-submit")
        assert not ask.query("#oracle-mode-buttons")
        assert len(ask.query("Button")) == 1


async def test_question_keystrokes_and_wheel_share_one_entropy_collector(
    app: SyzygyApp, profile
) -> None:
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("o")
        await settle(pilot)
        ask = pilot.app.screen
        assert isinstance(ask, OracleAskScreen)
        await pilot.press("a", "b", "c")
        assert ask._collector.event_count >= 3
        await pilot.press("enter")
        await settle(pilot)
        wheel = pilot.app.screen
        assert isinstance(wheel, WheelScreen)
        assert wheel._collector is ask._collector


async def test_views_and_archive_reopen_are_read_only(app: SyzygyApp, profile) -> None:
    async with app.run_test() as pilot:
        await settle(pilot)
        await complete_oracle(pilot, "What can I release?")
        screen = pilot.app.screen
        assert isinstance(screen, ConsultationResultScreen)
        card, cast = screen.consultation.card_draw, screen.consultation.cast

        await pilot.press("1")
        await pilot.pause()
        assert "ESOTERIC" in text_of(q(pilot, "#consultation-body", Static))
        await pilot.press("2")
        await pilot.pause()
        assert "CONVENTIONAL" in text_of(q(pilot, "#consultation-body", Static))
        await pilot.press("i")
        await pilot.pause()
        inputs = text_of(q(pilot, "#consultation-body", Static))
        assert "QUESTION (USER TEXT)" in inputs
        assert "THE GROUND (FIXED, BOTTOM LINE FIRST)" in inputs
        assert "THE FIGURE (FIXED, UPRIGHT)" in inputs
        assert "LEGGE 1882 CITATIONS" in inputs
        # M18's two lists survive unchanged.
        assert "PASSAGES SENT TO THE MODEL" in inputs
        assert "WHERE THIS CARD IS DISCUSSED" in inputs
        assert "prompt version: oracle-v2" in inputs

        await pilot.press("escape", "escape")
        await settle(pilot)
        assert isinstance(pilot.app.screen, HomeScreen)
        await pilot.press("a")
        await settle(pilot)
        assert isinstance(pilot.app.screen, ArchiveScreen)
        listing = q(pilot, "#archive-list", ListView)
        assert any(isinstance(item, ConsultationListItem) for item in listing.children)
        await pilot.press("enter")
        await settle(pilot)
        reopened = pilot.app.screen
        assert isinstance(reopened, ConsultationResultScreen)
        assert reopened._may_interpret is False
        assert reopened.consultation.card_draw == card
        assert reopened.consultation.cast == cast


async def test_an_interpretation_failure_keeps_both_objects(app: SyzygyApp, profile) -> None:
    class FailingProvider:
        provider_id = "failure"
        model_id = "failure-v1"

        async def interpret(self, context):
            raise RuntimeError("no interpreter")

    app.services.provider = FailingProvider()
    async with app.run_test() as pilot:
        await settle(pilot)
        await complete_oracle(pilot, "What holds when the model does not?")
        screen = pilot.app.screen
        assert isinstance(screen, ConsultationResultScreen)
        card, cast = screen.consultation.card_draw, screen.consultation.cast

        assert screen.consultation.status is ConsultationStatus.INTERPRETATION_FAILED
        body = text_of(q(pilot, "#consultation-body", Static))
        assert "THE CONSULTATION IS FIXED." in body
        assert "INTERPRETATION IS UNAVAILABLE." in body
        assert "[R] Retry" in body
        assert screen._may_retry()
        assert len(pilot.app.screen.query(".cast-line")) == 6

        # Recovery re-interprets; it never redraws and never recasts.
        await pilot.press("f")
        await settle(pilot, 6)
        recovered = pilot.app.screen
        assert isinstance(recovered, ConsultationResultScreen)
        assert recovered.consultation.status is ConsultationStatus.COMPLETE
        assert recovered.consultation.card_draw == card
        assert recovered.consultation.cast == cast


async def test_the_archive_distinguishes_four_record_kinds(
    app: SyzygyApp, profile, conn
) -> None:
    from tests.storage.test_legacy_consultations import (
        insert_legacy_iching_row,
        insert_legacy_oracle_row,
    )

    insert_legacy_oracle_row(conn, profile.id)
    insert_legacy_iching_row(conn, profile.id)

    async with app.run_test() as pilot:
        await settle(pilot)
        await complete_oracle(pilot, "What is now?")
        await pilot.press("escape", "escape")
        await settle(pilot)
        # A daily reading too, so all four kinds are present at once.
        await pilot.press("enter")
        await pilot.pause()
        for _ in range(3):
            await pilot.press("space")
        await pilot.press("enter")
        await settle(pilot, 8)
        while not isinstance(pilot.app.screen, HomeScreen):
            await pilot.press("escape")
            await settle(pilot)

        await pilot.press("a")
        await settle(pilot)
        assert isinstance(pilot.app.screen, ArchiveScreen)
        listing = q(pilot, "#archive-list", ListView)
        kinds = {type(item) for item in listing.children}
        assert ConsultationListItem in kinds
        assert OracleListItem in kinds
        assert IChingListItem in kinds

        labels = "\n".join(text_of(item.query_one(Static)) for item in listing.children)
        assert "ORACLE" in labels
        assert "was: THOTH" in labels
        assert "was: I CHING" in labels
        assert "earlier single-oracle rites 2" in text_of(q(pilot, "#archive-summary", Static))


async def test_a_legacy_record_reopens_read_only_and_says_so(
    app: SyzygyApp, profile, conn
) -> None:
    from tests.storage.test_legacy_consultations import insert_legacy_oracle_row

    insert_legacy_oracle_row(conn, profile.id)

    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("a")
        await settle(pilot)
        listing = q(pilot, "#archive-list", ListView)
        assert isinstance(listing.children[0], OracleListItem)
        await pilot.press("enter")
        await settle(pilot)

        screen = pilot.app.screen
        assert isinstance(screen, ConsultationResultScreen)
        assert screen._may_interpret is False
        assert screen.record.is_legacy
        assert "HISTORICAL RITE" in text_of(q(pilot, "#consultation-legacy", Static))
        assert "no cast" in text_of(q(pilot, "#consultation-hexagram", Static))
        assert not screen.query(".cast-line")
        # No recovery path exists for it, whatever key is pressed.
        assert not screen._may_retry()
        await pilot.press("r")
        await pilot.pause()
        assert screen.consultation.result is None
