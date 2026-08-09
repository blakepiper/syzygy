from textual.widgets import ListView, Static

from syzygy.domain.iching_consultation import IChingStatus
from syzygy.storage.iching import list_consultations
from syzygy.tui.app import SyzygyApp
from syzygy.tui.screens.archive import ArchiveScreen, IChingListItem
from syzygy.tui.screens.home import HomeScreen
from syzygy.tui.screens.iching_result import IChingResultScreen
from syzygy.tui.screens.oracle_ask import OracleAskScreen
from syzygy.tui.screens.wheel import WheelScreen

from .test_ritual_flow import q, settle, text_of


async def complete_iching(pilot, question: str = "What is changing?") -> None:
    await pilot.press("o")
    await settle(pilot)
    assert isinstance(pilot.app.screen, OracleAskScreen)
    pilot.app.screen.query_one("#oracle-question").value = question
    await pilot.click("#iching-submit")
    await settle(pilot)
    assert isinstance(pilot.app.screen, WheelScreen)
    for _ in range(3):
        await pilot.press("space")
    await pilot.press("enter")
    await settle(pilot, 6)
    assert isinstance(pilot.app.screen, IChingResultScreen)


async def test_iching_is_an_alternative_oracle_with_one_committed_cast(
    app: SyzygyApp, profile, conn
) -> None:
    async with app.run_test() as pilot:
        await settle(pilot)
        assert isinstance(pilot.app.screen, HomeScreen)
        await complete_iching(pilot)

        screen = pilot.app.screen
        assert isinstance(screen, IChingResultScreen)
        assert screen.consultation.status is IChingStatus.COMPLETE
        assert screen.consultation.cast is not None
        assert screen.consultation.result is not None
        assert "What is changing?" in text_of(q(pilot, "#iching-result-question", Static))
        assert "RESPONSE" in text_of(q(pilot, "#iching-result-body", Static))

        consultations = list_consultations(conn, profile.id)
        assert len(consultations) == 1
        assert consultations[0].cast == screen.consultation.cast


async def test_iching_inputs_and_archive_reopen_are_read_only(app: SyzygyApp, profile) -> None:
    async with app.run_test() as pilot:
        await settle(pilot)
        await complete_iching(pilot, "Where should I wait?")
        screen = pilot.app.screen
        assert isinstance(screen, IChingResultScreen)
        fixed_cast = screen.consultation.cast

        await pilot.press("i")
        await pilot.pause()
        inputs = text_of(q(pilot, "#iching-result-body", Static))
        assert "CAST (FIXED, BOTTOM LINE FIRST)" in inputs
        assert "LEGGE 1882 CITATIONS" in inputs
        assert "prompt version: iching-v1" in inputs

        await pilot.press("escape", "escape")
        await settle(pilot)
        await pilot.press("a")
        await settle(pilot)
        assert isinstance(pilot.app.screen, ArchiveScreen)
        listing = q(pilot, "#archive-list", ListView)
        assert any(isinstance(item, IChingListItem) for item in listing.children)
        await pilot.press("enter")
        await settle(pilot)
        reopened = pilot.app.screen
        assert isinstance(reopened, IChingResultScreen)
        assert reopened._may_interpret is False
        assert reopened.consultation.cast == fixed_cast
