"""The opening sequence runs on every launch (M17.1).

The defect: `SyzygyApp.on_mount` routed straight past it whenever a
profile was saved, so the wordmark, the logo and the mascot were built,
styled, and never seen by anybody who had used the application before.

What these hold to the fire is the *pair* of properties, because either
one alone is a different bug: every launch plays the sequence, and no
launch is ever detained by it.
"""

from __future__ import annotations

import uuid

import pytest

from syzygy.storage.profiles import insert_profile
from syzygy.tui.animation.motion import MotionLevel
from syzygy.tui.app import SyzygyApp
from syzygy.tui.screens.home import HomeScreen
from syzygy.tui.screens.profile_select import ProfileSelectScreen
from syzygy.tui.screens.startup import StartupScreen
from syzygy.tui.screens.too_small import MIN_HEIGHT, MIN_WIDTH, TooSmallScreen
from syzygy.tui.screens.welcome import WelcomeScreen
from syzygy.tui.widgets.brand import Logo, Mascot

from .conftest import FIXED_NOW
from .test_ritual_flow import settle


@pytest.fixture
def two_profiles(conn, profile):
    second = profile.model_copy(
        update={"id": str(uuid.uuid4()), "display_name": "Other", "created_at_utc": FIXED_NOW}
    )
    insert_profile(conn, second)
    return [profile, second]


def finish_startup(pilot) -> None:
    handle = pilot.app.animations.animator.handle_for("startup")
    if handle is not None:
        handle.finish()


# -- every launch passes through it -----------------------------------------


async def test_a_launch_with_no_profile_starts_on_the_startup_screen(app: SyzygyApp):
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(pilot.app.screen, StartupScreen)
        await settle(pilot)
        assert isinstance(pilot.app.screen, WelcomeScreen)


async def test_a_launch_with_one_profile_starts_on_the_startup_screen(
    app: SyzygyApp, profile
):
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(pilot.app.screen, StartupScreen)
        await settle(pilot)
        assert isinstance(pilot.app.screen, HomeScreen)
        assert pilot.app.profile is not None
        assert pilot.app.profile.id == profile.id


async def test_a_launch_with_several_profiles_starts_on_the_startup_screen(
    services, two_profiles
):
    async with SyzygyApp(services).run_test() as pilot:
        await pilot.pause()
        assert isinstance(pilot.app.screen, StartupScreen)
        await settle(pilot)
        assert isinstance(pilot.app.screen, ProfileSelectScreen)
        # Which self is being read for is never chosen for the user.
        assert pilot.app.profile is None


async def test_the_startup_screen_shows_the_logo_and_the_mascot(app: SyzygyApp, profile):
    """The whole point: a returning user sees the brand, not a cut to a
    list of profiles."""
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, StartupScreen)
        assert screen.query_one("#startup-logo", Logo)
        assert screen.query_one("#startup-mascot", Mascot)


async def test_the_startup_brand_is_centered_on_the_terminal(app: SyzygyApp, profile):
    async with app.run_test(size=(110, 36)) as pilot:
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, StartupScreen)
        logo = screen.query_one("#startup-logo", Logo)
        mascot = screen.query_one("#startup-mascot", Mascot)
        terminal_center = screen.size.width // 2
        assert logo.region.center[0] == terminal_center
        assert mascot.region.center[0] == terminal_center


@pytest.mark.parametrize("level", [MotionLevel.FULL, MotionLevel.REDUCED])
async def test_the_mark_never_spells_the_name_the_logo_already_carries(services, level):
    """The mark used to morph to `S Y Z Y G Y` one row above a logo whose
    art is that same word, so the opening said the name twice at once.

    Seeking is the honest way to ask this: every frame the sequence can
    render is a point on the timeline, so sampling it densely covers what
    a viewer could see, including the states a dropped frame would skip
    straight past.
    """
    from textual.widgets import Static

    from syzygy.tui.animation.animator import Animator
    from syzygy.tui.animation.events import Animations
    from syzygy.tui.animation.motion import MotionSettings

    mark = Static()
    shown: list[str] = []
    mark.update = lambda renderable="": shown.append(str(renderable))  # type: ignore[method-assign]

    animations = Animations(Animator(MotionSettings(level=level)))
    handle = animations.startup(mark, Static(), Static(), lambda: None)
    step = handle._step
    for frame in range(201):
        step.seek(step.duration * frame / 200)
    step.finish()

    assert shown, "the mark was never written to"
    for text in shown:
        letters = {character for character in text.upper() if character.isalpha()}
        assert not letters, f"the mark spelled {text!r}"
    assert "" in shown, "the mark has to clear once the wordmark has taken over"


# -- and is never detained by it --------------------------------------------


async def test_a_keypress_finishes_the_sequence_and_routes_at_once(app: SyzygyApp, profile):
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(pilot.app.screen, StartupScreen)

        await pilot.press("x")
        await pilot.pause()

        assert isinstance(pilot.app.screen, HomeScreen)
        assert pilot.app.animations.animator.handle_for("startup") is None


async def test_motion_off_routes_with_no_animation_at_all(services, profile, monkeypatch):
    monkeypatch.setenv("SYZYGY_ANIMATIONS", "off")
    app = SyzygyApp(services)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.animations.motion.level is MotionLevel.OFF
        assert isinstance(pilot.app.screen, HomeScreen)
        # Not merely finished - never registered. `off` is "final states,
        # immediately", not "a timeline nobody watched".
        assert not app.animations.animator.active
        assert app.animations.animator.handle_for("startup") is None


async def test_waiting_for_the_sequence_lands_in_the_same_place_as_skipping_it(
    services, profile
):
    """The two paths through `startup` must agree, or a dropped frame
    would change where a launch ends up."""
    app = SyzygyApp(services)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Play it out frame by frame against the animator's own clock,
        # rather than waiting on a wall clock (M17.2f).
        app.animations.animator.tick(2.0)
        await pilot.pause()
        assert isinstance(pilot.app.screen, HomeScreen)


async def test_quit_still_works_during_the_sequence(app: SyzygyApp, profile):
    """`[Q]` is the one key the startup screen must not swallow."""
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(pilot.app.screen, StartupScreen)
        await pilot.press("q")
        await pilot.pause()
    assert app.return_value is None


# -- the gates around it ----------------------------------------------------


async def test_the_too_small_gate_wins_over_the_startup_sequence(app: SyzygyApp, profile):
    """Below the floor there is nothing worth drawing, including this."""
    async with app.run_test(size=(MIN_WIDTH - 10, MIN_HEIGHT - 4)) as pilot:
        await pilot.pause()
        assert isinstance(pilot.app.screen, TooSmallScreen)
        assert not pilot.app.animations.animator.active

        await pilot.resize_terminal(100, 32)
        await settle(pilot)
        assert isinstance(pilot.app.screen, HomeScreen)


async def test_startup_seen_suppresses_a_second_sequence_in_one_process(
    app: SyzygyApp, profile
):
    """M17.1c: it suppresses a *second* startup within one process, never
    the first one of a launch."""
    async with app.run_test() as pilot:
        await pilot.pause()
        assert not pilot.app.startup_seen  # the first one is not suppressed
        await settle(pilot)
        assert pilot.app.startup_seen

        pilot.app.push_screen("startup")
        await pilot.pause()
        # Straight through: no timeline, no second opening.
        assert pilot.app.animations.animator.handle_for("startup") is None
        assert isinstance(pilot.app.screen, HomeScreen)


async def test_the_reduced_sequence_is_shorter_than_the_full_one(services, profile):
    """`reduced` is a shortened *sequence*, not the same one played fast
    (M17.1b) - two beats rather than four, and about a third of the time
    once `time_scale` is applied."""
    from textual.widgets import Static

    from syzygy.tui.animation.animator import Animator
    from syzygy.tui.animation.events import Animations
    from syzygy.tui.animation.motion import MotionSettings

    def duration(level: MotionLevel) -> float:
        animations = Animations(Animator(MotionSettings(level=level)))
        handle = animations.startup(Static(), Static(), Static(), lambda: None)
        return handle._step.duration

    full = duration(MotionLevel.FULL)
    reduced = duration(MotionLevel.REDUCED)

    assert 1.2 <= full <= 1.6
    assert 0.4 <= reduced <= 0.7


async def test_the_welcome_screen_no_longer_owns_the_opening(app: SyzygyApp):
    """It keeps its copy and its keys; the sequence and the routing moved
    (M17.1a)."""
    async with app.run_test() as pilot:
        await settle(pilot)
        screen = pilot.app.screen
        assert isinstance(screen, WelcomeScreen)
        assert not screen.query("#welcome-startup-mark")
        assert "PRESS ANY KEY" in screen.query_one("#welcome-keys").visual.plain

        await pilot.press("n")
        await settle(pilot)
        assert pilot.app.screen.__class__.__name__ == "ProfileCreateScreen"
