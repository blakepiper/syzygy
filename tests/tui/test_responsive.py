"""The "terminal too small" state (docs/old/DESIGN.md section 18.6, `TASKS.md`
M9.3): below the compact floor of 80x24, `SyzygyApp` shows a dedicated
static state instead of a broken layout, and returns to whatever screen
was active - without losing its state - once the terminal grows back.
"""

from __future__ import annotations

from textual.widgets import Static

from syzygy.tui.app import SyzygyApp
from syzygy.tui.screens.home import HomeScreen
from syzygy.tui.screens.too_small import MIN_HEIGHT, MIN_WIDTH, TooSmallScreen
from syzygy.tui.screens.wheel import WheelScreen

from .test_ritual_flow import q, settle, text_of, turn_the_wheel


async def test_below_minimum_size_shows_the_too_small_state(app: SyzygyApp, profile):
    async with app.run_test(size=(MIN_WIDTH, MIN_HEIGHT)) as pilot:
        await settle(pilot)
        assert isinstance(pilot.app.screen, HomeScreen)

        await pilot.resize_terminal(MIN_WIDTH - 20, MIN_HEIGHT - 6)
        await pilot.pause()
        assert isinstance(pilot.app.screen, TooSmallScreen)
        message = text_of(q(pilot, "#too-small-message", Static))
        assert f"{MIN_WIDTH - 20}x{MIN_HEIGHT - 6}" in message
        assert f"{MIN_WIDTH}x{MIN_HEIGHT}" in message


async def test_growing_back_above_minimum_restores_the_covered_screen(app: SyzygyApp, profile):
    async with app.run_test(size=(MIN_WIDTH, MIN_HEIGHT)) as pilot:
        await settle(pilot)

        await pilot.resize_terminal(40, 12)
        await pilot.pause()
        assert isinstance(pilot.app.screen, TooSmallScreen)

        await pilot.resize_terminal(MIN_WIDTH, MIN_HEIGHT)
        await pilot.pause()
        assert isinstance(pilot.app.screen, HomeScreen)


async def test_too_small_state_does_not_lose_progress_mid_wheel(app: SyzygyApp, profile):
    """Covering the Wheel does not tear it down - shrinking and growing
    the terminal back returns to the same in-progress screen.
    """
    async with app.run_test(size=(100, 32)) as pilot:
        await settle(pilot)
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(pilot.app.screen, WheelScreen)
        wheel_screen = pilot.app.screen

        await pilot.resize_terminal(40, 12)
        await pilot.pause()
        assert isinstance(pilot.app.screen, TooSmallScreen)

        await pilot.resize_terminal(100, 32)
        await pilot.pause()
        assert pilot.app.screen is wheel_screen


async def test_compact_class_applies_between_the_floor_and_the_ideal_size(app: SyzygyApp, profile):
    """Below the 100x32 ideal but at/above the 80x24 floor: `-compact` is
    set, no too-small gate appears (docs/old/DESIGN.md 18.6).
    """
    async with app.run_test(size=(MIN_WIDTH, MIN_HEIGHT)) as pilot:
        await settle(pilot)
        assert not isinstance(pilot.app.screen, TooSmallScreen)
        assert "-compact" in pilot.app.screen.classes


async def test_no_compact_class_at_the_ideal_size(app: SyzygyApp, profile):
    async with app.run_test(size=(100, 32)) as pilot:
        await settle(pilot)
        assert "-compact" not in pilot.app.screen.classes


async def test_at_minimum_size_no_gate_appears(app: SyzygyApp, profile):
    """80x24 is the compact floor, not below it - the ritual stays fully
    reachable there, per `test_ritual_flow.test_screens_survive_their_supported_sizes`.
    """
    async with app.run_test(size=(MIN_WIDTH, MIN_HEIGHT)) as pilot:
        await settle(pilot)
        assert not isinstance(pilot.app.screen, TooSmallScreen)
        await turn_the_wheel(pilot)
        assert not isinstance(pilot.app.screen, TooSmallScreen)
