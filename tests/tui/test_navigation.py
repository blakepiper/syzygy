"""Keyboard navigation between screens, and the archive's read-only rule."""

from __future__ import annotations

from textual.widgets import ListView, Static

from syzygy.domain.reading import ReadingStatus
from syzygy.tui.app import SyzygyApp
from syzygy.tui.screens.archive import ArchiveScreen
from syzygy.tui.screens.chart import ChartScreen
from syzygy.tui.screens.home import HomeScreen
from syzygy.tui.screens.profile_select import ProfileSelectScreen
from syzygy.tui.screens.reading import ReadingScreen

from .test_ritual_flow import FailingProvider, q, settle, text_of, turn_the_wheel


async def test_chart_screen_shows_the_saved_chart(app: SyzygyApp, profile):
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("c")
        await pilot.pause()

        assert isinstance(pilot.app.screen, ChartScreen)
        body = text_of(q(pilot, "#chart-body", Static))
        assert "Blake" in body
        assert "Virgo" in body  # natal Sun, from the stored chart
        assert "Ascendant" in body

        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(pilot.app.screen, HomeScreen)


async def test_profile_screen_lists_the_saved_profile(app: SyzygyApp, profile):
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("p")
        await pilot.pause()

        assert isinstance(pilot.app.screen, ProfileSelectScreen)
        assert len(q(pilot, "#profile-list", ListView).children) == 1


async def test_empty_archive(app: SyzygyApp, profile):
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("a")
        await pilot.pause()

        assert isinstance(pilot.app.screen, ArchiveScreen)
        assert "No readings yet." in text_of(q(pilot, "#archive-summary", Static))


async def test_archive_frequency_toggle_shows_and_hides_counts(services, profile):
    async with SyzygyApp(services).run_test() as pilot:
        await settle(pilot)
        await turn_the_wheel(pilot)
        card_id = pilot.app.screen.reading.card_draw.card_id
        await pilot.press("escape")
        await pilot.pause()

        await pilot.press("a")
        await settle(pilot)
        assert isinstance(pilot.app.screen, ArchiveScreen)

        from syzygy.sortes.deck import get_card

        await pilot.press("f")
        await pilot.pause()
        counts_text = text_of(q(pilot, "#archive-frequency", Static))
        assert get_card(card_id).full_name in counts_text

        await pilot.press("f")
        await pilot.pause()
        panel = q(pilot, "#archive-frequency-panel")
        assert "hidden" in panel.classes


async def test_archive_reopens_a_reading_without_interpreting_it(services, profile):
    """A past reading is rendered from storage, never regenerated."""
    async with SyzygyApp(services).run_test() as pilot:
        await settle(pilot)
        await turn_the_wheel(pilot)
        card_id = pilot.app.screen.reading.card_draw.card_id
        await pilot.press("escape")
        await pilot.pause()

        await pilot.press("a")
        await settle(pilot)
        assert "Readings 1" in text_of(q(pilot, "#archive-summary", Static))

        # Any later interpretation attempt would fail loudly with this
        # provider, so reaching a complete reading proves nothing re-ran.
        services.provider = FailingProvider()
        await pilot.press("enter")
        await settle(pilot)

        screen = pilot.app.screen
        assert isinstance(screen, ReadingScreen)
        assert screen.reading.status == ReadingStatus.COMPLETE
        assert screen.reading.card_draw.card_id == card_id
