"""M10.2: "q" quits from every screen, not just the ones that happened to
declare their own `("q", "quit", "quit")` binding.

`SyzygyApp.BINDINGS` now carries this binding once, app-wide (`app.py`),
rather than each screen repeating it - these regression tests exercise it
from screens that previously had no quit binding at all: `WheelScreen`,
`RevealScreen`, and `ReadingScreen`.
"""

from __future__ import annotations

from syzygy.tui.app import SyzygyApp
from syzygy.tui.screens.reveal import RevealScreen
from syzygy.tui.screens.wheel import WheelScreen

from .test_ritual_flow import settle, turn_the_wheel


def has_exited(pilot) -> bool:
    return bool(pilot.app._exit)


async def test_q_quits_from_the_wheel_screen(app: SyzygyApp, profile):
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("enter")  # home -> wheel
        await pilot.pause()
        assert isinstance(pilot.app.screen, WheelScreen)

        await pilot.press("q")
        await pilot.pause()
        assert has_exited(pilot)


async def test_q_quits_from_the_reveal_screen(app: SyzygyApp, profile):
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("enter")  # home -> wheel
        await pilot.pause()
        for _ in range(3):
            await pilot.press("space")
        await pilot.press("enter")  # release -> reveal
        await settle(pilot)
        assert isinstance(pilot.app.screen, RevealScreen)

        await pilot.press("q")
        await pilot.pause()
        assert has_exited(pilot)


async def test_q_quits_from_the_reading_screen(app: SyzygyApp, profile):
    async with app.run_test() as pilot:
        await settle(pilot)
        await turn_the_wheel(pilot)

        await pilot.press("q")
        await pilot.pause()
        assert has_exited(pilot)


async def test_q_quits_from_the_home_screen(app: SyzygyApp, profile):
    """Regression guard: this one always worked, kept as a control so a
    future refactor of the app-level binding can't silently drop it."""
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("q")
        await pilot.pause()
        assert has_exited(pilot)
