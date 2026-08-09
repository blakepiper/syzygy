"""M14's elapsed-time, interruption, and reduced-motion guarantees."""

from __future__ import annotations

import pytest

from syzygy.tui.animation.animator import Animator
from syzygy.tui.animation.easing import (
    ease_in_cubic,
    ease_in_out_quad,
    ease_out_back,
    ease_out_cubic,
)
from syzygy.tui.animation.motion import MotionLevel, MotionSettings, resolve_motion
from syzygy.tui.animation.timeline import Tween
from syzygy.tui.app import SyzygyApp
from syzygy.tui.screens.welcome import WelcomeScreen


@pytest.mark.parametrize(
    "easing,midpoint",
    [
        (ease_out_cubic, 0.875),
        (ease_in_out_quad, 0.5),
        (ease_out_back, 1.0876975),
        (ease_in_cubic, 0.125),
    ],
)
def test_easing_endpoints_and_midpoint(easing, midpoint):
    assert easing(0.0) == pytest.approx(0.0)
    assert easing(0.5) == pytest.approx(midpoint)
    assert easing(1.0) == pytest.approx(1.0)


def test_retargeting_settles_the_replaced_timeline_without_stale_state():
    values: list[float] = []
    animator = Animator()
    first = animator.run(
        Tween.between(values.append, start=0, end=10, duration=1), channel="focus"
    )
    animator.tick(0.5)
    second = animator.run(
        Tween.between(values.append, start=values[-1], end=20, duration=1), channel="focus"
    )
    assert first.done
    animator.tick(1)
    assert second.done
    assert 20 == pytest.approx(values[-1])


def test_motion_off_finishes_synchronously():
    values: list[float] = []
    animator = Animator(MotionSettings(level=MotionLevel.OFF))
    handle = animator.run(Tween.between(values.append, start=0, end=1, duration=10))
    assert handle.done
    assert values == [1]
    assert not animator.active


def test_reduced_motion_environment_is_honored():
    assert resolve_motion(environ={"NO_MOTION": "1"}).level is MotionLevel.REDUCED
    assert resolve_motion(environ={"SYZYGY_ANIMATIONS": "off"}).level is MotionLevel.OFF


async def test_welcome_reaches_same_settled_state_with_motion_off(services, monkeypatch):
    """The opening sequence moved to `StartupScreen` in M17.1 (see
    `test_startup.py`); what this still pins is that motion `off` lands on
    the settled welcome copy rather than on a half-drawn one."""
    monkeypatch.setenv("SYZYGY_ANIMATIONS", "off")
    app = SyzygyApp(services)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, WelcomeScreen)
        assert "PRESS ANY KEY" in screen.query_one("#welcome-keys").visual.plain


async def test_any_key_skips_startup_to_interactive_welcome(services):
    app = SyzygyApp(services)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("x")
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, WelcomeScreen)
        assert "PRESS ANY KEY" in screen.query_one("#welcome-keys").visual.plain


async def test_startup_reaches_interactive_welcome_when_timeline_completes(services):
    app = SyzygyApp(services)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.animations.animator.tick(2.0)
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, WelcomeScreen)
        assert "PRESS ANY KEY" in screen.query_one("#welcome-keys").visual.plain


async def test_routine_screens_remain_navigable_with_motion_off(
    services, profile, monkeypatch
):
    """The same navigation/state transitions work when visuals are instant."""
    monkeypatch.setenv("SYZYGY_ANIMATIONS", "off")
    app = SyzygyApp(services)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.profile == profile

        for key, expected_name in (
            ("c", "ChartScreen"),
            ("t", "CosmosScreen"),
            ("a", "ArchiveScreen"),
            ("p", "ProfileSelectScreen"),
            ("m", "ModelSetupScreen"),
        ):
            await pilot.press(key)
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()
            assert app.screen.__class__.__name__ == expected_name
            await pilot.press("escape")
            await pilot.pause()
            assert app.screen.__class__.__name__ == "HomeScreen"


async def test_the_cast_reveal_lands_settled_with_motion_off(
    services, profile, monkeypatch
):
    """M22.4c: the six lines build upward, and `off` still shows all six.

    The beat is honest either way - both chance objects are committed
    before it plays, so the motion reports a finished fact rather than
    deciding one.
    """
    monkeypatch.setenv("SYZYGY_ANIMATIONS", "off")
    app = SyzygyApp(services)
    async with app.run_test() as pilot:
        await pilot.pause()
        from tests.tui.test_oracle import complete_oracle

        await complete_oracle(pilot, "What is settled?")
        screen = pilot.app.screen
        lines = screen.query(".cast-line")

        assert screen.consultation.card_draw is not None
        assert screen.consultation.cast is not None
        assert len(lines) == 6
        assert all(line.styles.opacity == 1.0 for line in lines)
