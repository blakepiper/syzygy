"""Screens transition instead of cutting (M17.2).

Two separate defects, both of which look like "nothing animates":

*Coverage.* Only `wheel.py` ever called `animations.trigger("enter", …)`
on mount, so every other screen simply appeared. Entry now belongs to
`SyzygyScreen`, which is what makes "every screen" checkable rather than a
list somebody keeps in step by hand.

*Perceptibility.* The primitives that did run were 100-250 ms, which at a
33 ms frame interval is a handful of frames. These pin the durations to a
range a person can notice without asserting a wall clock anywhere - the
timelines are advanced by the animator's own clock.
"""

from __future__ import annotations

import pytest

from syzygy.tui.animation import primitives
from syzygy.tui.animation.animator import FRAME_INTERVAL, Animator
from syzygy.tui.animation.events import (
    ENTRY_DURATION,
    Animations,
    SemanticEvent,
)
from syzygy.tui.animation.motion import (
    ANIMATION_SECTION,
    MotionLevel,
    MotionSettings,
    resolve_motion,
)
from syzygy.tui.animation.timeline import Call, Delay, Sequence, Tween
from syzygy.tui.app import SyzygyApp
from syzygy.tui.screens.base import SyzygyScreen
from syzygy.tui.screens.reveal import RevealScreen
from syzygy.tui.screens.startup import StartupScreen
from syzygy.tui.screens.wheel import WheelScreen

from .test_ritual_flow import settle

#: The screens reachable from home by a single key.
ROUTINE_SCREENS = [("c", "ChartScreen"), ("t", "CosmosScreen"), ("a", "ArchiveScreen")]


# -- coverage ---------------------------------------------------------------


def record_transitions(monkeypatch) -> tuple[list[str], list[str]]:
    """`(entered, exited)`, by screen class name, as they happen.

    Recorded at the call rather than read off the animator afterwards: a
    screen with a background worker can hold the event loop long enough
    for a real 550 ms timeline to finish before the test looks, which
    would make "did it animate?" a question about how fast the machine
    is.
    """
    entered: list[str] = []
    exited: list[str] = []
    enter_screen = Animations.enter_screen
    trigger = Animations.trigger

    def spy_enter(self, screen, regions, title=None, title_text=""):
        entered.append(type(screen).__name__)
        return enter_screen(self, screen, regions, title, title_text)

    def spy_trigger(self, event, target):
        if SemanticEvent(event) is SemanticEvent.EXIT:
            exited.append(type(target).__name__)
        return trigger(self, event, target)

    monkeypatch.setattr(Animations, "enter_screen", spy_enter)
    monkeypatch.setattr(Animations, "trigger", spy_trigger)
    return entered, exited


@pytest.mark.parametrize(("key", "expected"), ROUTINE_SCREENS)
async def test_every_screen_animates_its_entry(
    app: SyzygyApp, profile, monkeypatch, key, expected
):
    entered, _ = record_transitions(monkeypatch)
    async with app.run_test() as pilot:
        await settle(pilot)
        entered.clear()

        await pilot.press(key)
        await pilot.pause()

        assert pilot.app.screen.__class__.__name__ == expected
        assert expected in entered


async def test_home_animates_its_entry_on_the_way_back(app: SyzygyApp, profile, monkeypatch):
    """Returning to a screen is an arrival too - and it is what restores
    the opacity that leaving took away."""
    entered, _ = record_transitions(monkeypatch)
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("c")
        await settle(pilot)
        entered.clear()

        await pilot.press("escape")
        await pilot.pause()

        assert pilot.app.screen.__class__.__name__ == "HomeScreen"
        assert "HomeScreen" in entered


async def test_leaving_a_screen_is_a_transition_not_a_cut(
    app: SyzygyApp, profile, monkeypatch
):
    _, exited = record_transitions(monkeypatch)
    async with app.run_test() as pilot:
        await settle(pilot)
        exited.clear()

        await pilot.press("c")
        await pilot.pause()

        assert "HomeScreen" in exited


async def test_returning_restores_a_screen_that_leaving_dimmed(app: SyzygyApp, profile):
    """The stale-visual-state failure, at screen scale: a screen that is
    left and returned to must not stay half-faded."""
    async with app.run_test() as pilot:
        await settle(pilot)
        home = pilot.app.screen

        await pilot.press("c")
        await settle(pilot)
        await pilot.press("escape")
        await settle(pilot)

        assert pilot.app.screen is home
        assert float(home.styles.opacity) == pytest.approx(1.0)


@pytest.mark.parametrize("screen", [StartupScreen, RevealScreen, WheelScreen])
def test_screens_with_their_own_choreography_opt_out(screen):
    """A screen that animates itself must not be animated twice (M17.2a)."""
    assert screen.SCREEN_TRANSITIONS is False
    assert SyzygyScreen.SCREEN_TRANSITIONS is True


def test_every_choreography_is_reachable_from_the_screen_that_owns_it():
    """A named choreography nobody calls is the M17 defect in miniature -
    built, styled, and unreachable on the path a user takes."""
    import inspect
    from importlib import resources

    sources = "\n".join(
        path.read_text()
        for directory in ("screens", "widgets", "animation")
        for path in resources.files("syzygy.tui").joinpath(directory).iterdir()
        if path.name.endswith(".py")
    )
    sources += resources.files("syzygy.tui").joinpath("app.py").read_text()

    unreachable = [
        name
        for name, member in inspect.getmembers(Animations, inspect.isfunction)
        if not name.startswith("_") and f".{name}(" not in sources
    ]
    assert unreachable == [], f"nothing calls: {unreachable}"


def test_every_screen_with_somewhere_to_go_back_to_binds_escape():
    """M17.5a's other half. The screens that do not bind it are the ones
    with nowhere to back out to - the roots of the stack, and the
    too-small gate, which must not be dismissable."""
    from syzygy.tui.app import SyzygyApp as _App

    roots = {"startup", "welcome", "home", "too_small"}
    for name, screen in _App.SCREENS.items():
        keys = {
            binding[0] if isinstance(binding, tuple) else binding.key
            for binding in screen.BINDINGS
        }
        has_escape = any("escape" in key for key in keys)
        assert has_escape is (name not in roots), name


async def test_navigation_never_waits_on_the_transition(app: SyzygyApp, profile):
    """The screen switches now; the animation accompanies it. A dropped
    frame must not strand anybody."""
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("c")
        await pilot.pause()
        # No animator tick between the keypress and this assertion.
        assert pilot.app.screen.__class__.__name__ == "ChartScreen"


# -- perceptibility ---------------------------------------------------------


def test_entry_durations_are_long_enough_to_see():
    """M17.2c: roughly 350-600 ms at `full`, which is several times the
    33 ms frame interval rather than a handful of frames."""
    assert 0.3 <= ENTRY_DURATION <= 0.6
    assert ENTRY_DURATION / FRAME_INTERVAL >= 8

    for name in ("reveal", "decode", "typewriter"):
        duration = getattr(primitives, name).__defaults__[-1]
        assert duration >= 0.3, f"{name} is {duration}s - too short to notice"


def test_the_screen_entry_carries_more_than_opacity():
    """A terminal with poor opacity blending still gets a signal: the
    title bar decodes into place (M17.2c)."""
    from textual.widgets import Static

    written: list[str] = []

    class Recording(Static):
        def update(self, renderable="", *args, **kwargs):  # type: ignore[override]
            written.append(str(renderable))

    animations = Animations(Animator())
    title = Recording()
    handle = animations.enter_screen(Static(), [Static()], title, "SYZYGY   ARCHIVE")
    animations.animator.tick(0.05)
    handle.finish()

    assert written, "the title bar was never written to"
    assert written[-1] == "SYZYGY   ARCHIVE"
    assert any(frame != "SYZYGY   ARCHIVE" for frame in written), "no intermediate frames"


def test_a_fresh_install_gets_full_motion(tmp_path):
    """M17.2c: `resolve_motion` must not be reading a stale or absent
    section and quietly landing on something quieter than `full`."""
    settings = tmp_path / "settings.json"
    assert resolve_motion(settings, environ={}).level is MotionLevel.FULL

    settings.write_text('{"provider": {"provider_id": "fixture"}}\n')
    assert resolve_motion(settings, environ={}).level is MotionLevel.FULL

    settings.write_text('{"' + ANIMATION_SECTION + '": {"level": "reduced"}}\n')
    assert resolve_motion(settings, environ={}).level is MotionLevel.REDUCED


@pytest.mark.parametrize(
    "level", [MotionLevel.FULL, MotionLevel.REDUCED, MotionLevel.OFF]
)
def test_every_level_degrades_the_way_m14_specifies(level):
    animations = Animations(Animator(MotionSettings(level=level)))
    settings = animations.motion

    assert settings.enabled is (level is not MotionLevel.OFF)
    assert settings.allows_shake is (level is MotionLevel.FULL)
    assert settings.allows_particles is (level is MotionLevel.FULL)
    if level is MotionLevel.OFF:
        assert settings.time_scale == 0.0
    else:
        assert settings.time_scale > 0.0
        assert settings.time_scale <= 1.0


# -- the pump ---------------------------------------------------------------


def test_a_queued_step_actually_advances_frames_under_a_test_clock():
    """M17.2d: "no animation at all" was indistinguishable from a silent
    scheduling failure, because a timeline that is never pumped raises
    nothing and simply sits at frame zero."""
    now = [0.0]
    seen: list[float] = []
    animator = Animator(monotonic=lambda: now[0])
    animator.run(Tween.between(seen.append, start=0.0, end=1.0, duration=0.3))

    assert seen == [0.0]  # the initial frame, rendered on `run`
    for _ in range(4):
        now[0] += FRAME_INTERVAL
        animator.pump()

    assert len(seen) > 1
    assert seen[-1] > seen[0]
    assert all(later >= earlier for earlier, later in zip(seen, seen[1:], strict=False))


def test_the_pump_runs_only_while_something_is_animating():
    """`docs/animation.md` section 35: no idle cost, which means no timer
    at all rather than a cheap tick."""
    started: list[str] = []
    animator = Animator(
        on_active=lambda: started.append("active"), on_idle=lambda: started.append("idle")
    )
    assert started == []

    handle = animator.run(Sequence([Delay(0.1), Call(lambda: None)]))
    assert started == ["active"]

    handle.finish()
    assert started == ["active", "idle"]
    assert not animator.active


async def test_the_application_wires_the_pump_to_a_real_interval(app: SyzygyApp, profile):
    async with app.run_test() as pilot:
        await pilot.pause()
        driver = pilot.app.animation_driver
        # The opening sequence is running, so the interval must be too.
        assert driver.animator.active
        assert driver.pumping

        # Finishing cascades - the opening routes, and arriving somewhere
        # starts the arrival's own animations - so settle it out rather
        # than assuming one call empties the running set.
        for _ in range(6):
            driver.animator.finish_all()
            await pilot.pause()
            if not driver.animator.active:
                break

        assert not driver.animator.active
        assert not driver.pumping
