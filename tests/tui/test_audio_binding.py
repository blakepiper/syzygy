"""The theme's interface surface (M15.1c/d).

Every test here drives a `FakeTheme` rather than a real device: CI has no
audio, and asserting on calls is what actually pins the behaviour anyway.
"""

from __future__ import annotations

from textual.widgets import Static

from syzygy.tui.app import SyzygyApp
from syzygy.tui.screens.welcome import WelcomeScreen

from .test_ritual_flow import q, settle, text_of


class FakeTheme:
    """A `ThemePlayer` that records what the app asked of it."""

    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self._muted = False
        self.calls: list[str] = []

    @property
    def muted(self) -> bool:
        return self._muted

    def start(self) -> None:
        self.calls.append("start")

    def toggle_mute(self) -> bool:
        self._muted = not self._muted
        self.calls.append("mute" if self._muted else "unmute")
        return self._muted

    def stop(self) -> None:
        self.calls.append("stop")

    def play_notification(self) -> None:
        self.calls.append("notification")


async def test_the_theme_starts_with_the_app(services):
    theme = FakeTheme()
    app = SyzygyApp(services, theme_player=theme)
    async with app.run_test() as pilot:
        await settle(pilot)
        assert theme.calls[0] == "start"


async def test_the_theme_stops_when_the_app_exits(services):
    """M15.1c: a process that exits leaving audio playing is a bug."""
    theme = FakeTheme()
    app = SyzygyApp(services, theme_player=theme)
    async with app.run_test() as pilot:
        await settle(pilot)
    assert "stop" in theme.calls


async def test_q_stops_the_theme_on_the_way_out(services, profile):
    theme = FakeTheme()
    app = SyzygyApp(services, theme_player=theme)
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("q")
        await pilot.pause()
    assert "stop" in theme.calls


async def test_s_toggles_mute_from_any_screen(services, profile):
    theme = FakeTheme()
    app = SyzygyApp(services, theme_player=theme)
    async with app.run_test() as pilot:
        await settle(pilot)

        await pilot.press("s")
        await pilot.pause()
        assert theme.muted is True

        await pilot.press("s")
        await pilot.pause()
        assert theme.muted is False


async def test_s_on_a_silent_build_says_so_rather_than_doing_nothing(services, profile):
    theme = FakeTheme(available=False)
    app = SyzygyApp(services, theme_player=theme)
    async with app.run_test() as pilot:
        await settle(pilot)

        await pilot.press("s")
        await pilot.pause()

        assert "mute" not in theme.calls
        assert app._notifications  # a visible response, not a dead key


async def test_a_focused_input_takes_a_literal_s(services):
    """Same rule as `q` (M10.2b): a focused widget gets first refusal."""
    from textual.widgets import Input

    theme = FakeTheme()
    app = SyzygyApp(services, theme_player=theme)
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("n")  # create-profile form
        await pilot.pause()

        display_name = q(pilot, "#display-name", Input)
        display_name.focus()
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()

        assert display_name.value == "s"
        assert theme.muted is False


async def test_the_welcome_screen_advertises_the_mute_key(services):
    theme = FakeTheme()
    app = SyzygyApp(services, theme_player=theme)
    async with app.run_test() as pilot:
        await settle(pilot)
        assert isinstance(app.screen, WelcomeScreen)
        assert "[S] Sound" in text_of(q(pilot, "#welcome-keys", Static))


async def test_a_silent_build_does_not_advertise_a_key_that_does_nothing(services):
    theme = FakeTheme(available=False)
    app = SyzygyApp(services, theme_player=theme)
    async with app.run_test() as pilot:
        await settle(pilot)
        keys = text_of(q(pilot, "#welcome-keys", Static))
        assert "[S] Sound" not in keys
        assert "[Q] Quit" in keys
