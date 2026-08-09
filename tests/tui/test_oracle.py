from __future__ import annotations

from textual.widgets import ListView, Static

from syzygy.domain.oracle import OracleStatus
from syzygy.storage.oracle import list_consultations
from syzygy.tui.app import SyzygyApp
from syzygy.tui.screens.archive import ArchiveScreen, OracleListItem
from syzygy.tui.screens.home import HomeScreen
from syzygy.tui.screens.oracle_ask import OracleAskScreen
from syzygy.tui.screens.oracle_result import OracleResultScreen
from syzygy.tui.screens.wheel import WheelScreen

from .test_ritual_flow import q, settle, text_of


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
    assert isinstance(pilot.app.screen, OracleResultScreen)


async def test_oracle_is_available_without_consuming_the_daily_reading(
    app: SyzygyApp, profile, conn
) -> None:
    async with app.run_test() as pilot:
        await settle(pilot)
        assert isinstance(pilot.app.screen, HomeScreen)
        await complete_oracle(pilot)

        screen = pilot.app.screen
        assert isinstance(screen, OracleResultScreen)
        assert screen.consultation.status is OracleStatus.COMPLETE
        assert screen.consultation.result is not None
        assert "What needs my attention?" in text_of(q(pilot, "#oracle-result-question", Static))
        assert "RESPONSE" in text_of(q(pilot, "#oracle-result-body", Static))

        from syzygy.storage.readings import list_readings

        assert list_readings(conn, profile.id) == []
        consultations = list_consultations(conn, profile.id)
        assert len(consultations) == 1
        assert consultations[0].card_draw == screen.consultation.card_draw


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


async def test_oracle_views_and_archive_reopen_are_read_only(app: SyzygyApp, profile) -> None:
    async with app.run_test() as pilot:
        await settle(pilot)
        await complete_oracle(pilot, "What can I release?")
        screen = pilot.app.screen
        assert isinstance(screen, OracleResultScreen)
        card = screen.consultation.card_draw

        await pilot.press("1")
        await pilot.pause()
        assert "ESOTERIC" in text_of(q(pilot, "#oracle-result-body", Static))
        await pilot.press("2")
        await pilot.pause()
        assert "CONVENTIONAL" in text_of(q(pilot, "#oracle-result-body", Static))
        await pilot.press("i")
        await pilot.pause()
        inputs = text_of(q(pilot, "#oracle-result-body", Static))
        assert "QUESTION (USER TEXT)" in inputs
        assert "PASSAGES SENT TO THE MODEL" in inputs
        assert "WHERE THIS CARD IS DISCUSSED" in inputs

        await pilot.press("escape", "escape")
        await settle(pilot)
        assert isinstance(pilot.app.screen, HomeScreen)
        await pilot.press("a")
        await settle(pilot)
        assert isinstance(pilot.app.screen, ArchiveScreen)
        listing = q(pilot, "#archive-list", ListView)
        assert any(isinstance(item, OracleListItem) for item in listing.children)
        await pilot.press("enter")
        await settle(pilot)
        reopened = pilot.app.screen
        assert isinstance(reopened, OracleResultScreen)
        assert reopened._may_interpret is False
        assert reopened.consultation.card_draw == card
