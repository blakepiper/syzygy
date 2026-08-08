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


# -- M11.6: the dev-only reroll ------------------------------------------


async def test_reroll_key_does_nothing_without_the_dev_switch(app: SyzygyApp, profile, monkeypatch):
    """With `SYZYGY_DEV` unset the binding must not exist at all - a
    destructive action must not be one stray keypress away."""
    from syzygy.dev import DEV_MODE_ENV_VAR

    monkeypatch.delenv(DEV_MODE_ENV_VAR, raising=False)
    async with app.run_test() as pilot:
        await settle(pilot)
        await turn_the_wheel(pilot)
        await pilot.press("escape")
        await settle(pilot)

        home = pilot.app.screen
        assert isinstance(home, HomeScreen)
        assert "x" not in home.active_bindings
        assert text_of(q(pilot, "#home-dev", Static)) == ""

        reading_before = home._reading
        await pilot.press("x")
        await settle(pilot)

        assert q(pilot, "#home-reroll-confirm").has_class("hidden")
        assert home._reading is not None
        assert home._reading.id == reading_before.id


async def test_reroll_asks_before_discarding(services, profile, monkeypatch):
    from syzygy.dev import DEV_MODE_ENV_VAR

    monkeypatch.setenv(DEV_MODE_ENV_VAR, "1")
    app = SyzygyApp(services)
    async with app.run_test() as pilot:
        await settle(pilot)
        await turn_the_wheel(pilot)
        await pilot.press("escape")
        await settle(pilot)

        home = pilot.app.screen
        assert "x" in home.active_bindings
        assert "DEV MODE" in text_of(q(pilot, "#home-dev", Static))

        await pilot.press("x")
        await pilot.pause()

        assert not q(pilot, "#home-reroll-confirm").has_class("hidden")
        # Nothing discarded yet, and CANCEL holds focus.
        assert home._reading is not None
        assert pilot.app.focused is q(pilot, "#reroll-cancel")


async def test_reroll_discards_and_allows_a_new_draw(services, profile, conn, monkeypatch):
    from syzygy.dev import DEV_MODE_ENV_VAR
    from syzygy.storage import readings as readings_store

    monkeypatch.setenv(DEV_MODE_ENV_VAR, "1")
    app = SyzygyApp(services)
    async with app.run_test() as pilot:
        await settle(pilot)
        await turn_the_wheel(pilot)
        first_id = pilot.app.screen.reading.id
        local_date = pilot.app.screen.reading.consultation_local_date
        await pilot.press("escape")
        await settle(pilot)

        await pilot.press("x")
        await pilot.pause()
        q(pilot, "#reroll-confirm").press()
        await settle(pilot)

        home = pilot.app.screen
        assert home._reading is None
        assert readings_store.get_today(conn, profile.id, local_date) is None
        # The primary action goes back to offering the wheel.
        assert "TURN THE WHEEL" in str(q(pilot, "#primary-action").label)

        await turn_the_wheel(pilot)
        assert pilot.app.screen.reading.id != first_id


async def test_reroll_cancel_keeps_the_reading(services, profile, monkeypatch):
    from syzygy.dev import DEV_MODE_ENV_VAR

    monkeypatch.setenv(DEV_MODE_ENV_VAR, "1")
    app = SyzygyApp(services)
    async with app.run_test() as pilot:
        await settle(pilot)
        await turn_the_wheel(pilot)
        reading_id = pilot.app.screen.reading.id
        await pilot.press("escape")
        await settle(pilot)

        await pilot.press("x")
        await pilot.pause()
        q(pilot, "#reroll-cancel").press()
        await settle(pilot)

        assert q(pilot, "#home-reroll-confirm").has_class("hidden")
        assert pilot.app.screen._reading.id == reading_id


async def test_reroll_before_any_draw_is_a_visible_noop(services, profile, monkeypatch):
    from syzygy.dev import DEV_MODE_ENV_VAR

    monkeypatch.setenv(DEV_MODE_ENV_VAR, "1")
    app = SyzygyApp(services)
    async with app.run_test() as pilot:
        await settle(pilot)

        await pilot.press("x")
        await pilot.pause()

        assert q(pilot, "#home-reroll-confirm").has_class("hidden")
        assert "Nothing to reroll" in text_of(q(pilot, "#home-status", Static))
