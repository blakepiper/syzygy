"""The full daily ritual, driven through Textual's `Pilot`.

Milestone 5's acceptance criterion: profile -> home -> wheel -> reveal ->
reading must be navigable and coherent with fixture interpretation text
only. These tests also pin the oracle invariants at the interface level -
reopening cannot redraw, and a failed interpretation cannot redraw either.
"""

from __future__ import annotations

import pytest
from textual.widgets import Button, Input, Static

from syzygy.domain.interpretation import InterpretationContext, InterpretationResult
from syzygy.domain.reading import ReadingStatus
from syzygy.interpretation.providers.fixture import FixtureProvider
from syzygy.storage.readings import get_today
from syzygy.tui.animation.events import SCREEN_ENTER_CHANNEL
from syzygy.tui.app import SyzygyApp
from syzygy.tui.screens.home import OPEN_TODAYS_READING, TURN_THE_WHEEL, HomeScreen
from syzygy.tui.screens.reading import ReadingScreen
from syzygy.tui.screens.reveal import RevealScreen
from syzygy.tui.screens.welcome import WelcomeScreen
from syzygy.tui.screens.wheel import WheelScreen
from syzygy.tui.widgets.reading_panel import NO_PASSAGES_NOTE, ReadingPanel

from .conftest import FIXED_NOW


class FailingProvider:
    """Stands in for an unreachable model (docs/old/DESIGN.md section 23)."""

    provider_id = "failing"
    model_id = "none"

    async def interpret(self, context: InterpretationContext) -> InterpretationResult:
        raise RuntimeError("no model configured")


def text_of(widget: Static) -> str:
    return widget.visual.plain


def q(pilot, selector: str, expect_type=None):
    """Query the active screen (not the app root, which also holds the
    default screen underneath the stack)."""
    if expect_type is None:
        return pilot.app.screen.query_one(selector)
    return pilot.app.screen.query_one(selector, expect_type)


#: Timelines that are chrome rather than ritual: the opening sequence and
#: the screen-entry transition. `settle` lands them on their final state
#: the way a keypress would, because a headless pilot has no wall clock to
#: run them on and nothing in a test should ever wait on one (M17.2f: no
#: test asserts wall-clock timing). The ritual's own choreographies -
#: `draw-complete`, `ritual-reveal` - are deliberately *not* in here: they
#: are the thing under test on the screens that own them.
CHROME_CHANNELS = ("startup", SCREEN_ENTER_CHANNEL)


async def settle(pilot, cycles: int = 3) -> None:
    """Let the opening sequence, the workers, and the UI updates finish."""
    for _ in range(cycles):
        for channel in CHROME_CHANNELS:
            handle = pilot.app.animations.animator.handle_for(channel)
            if handle is not None:
                handle.finish()
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()


async def turn_the_wheel(pilot) -> None:
    """Home -> wheel -> released draw -> reveal -> reading."""
    await pilot.press("enter")  # primary action: TURN THE WHEEL
    await pilot.pause()
    assert isinstance(pilot.app.screen, WheelScreen)

    for _ in range(3):
        await pilot.press("space")
    await pilot.press("enter")  # release
    await settle(pilot)

    assert isinstance(pilot.app.screen, RevealScreen)
    await pilot.press("enter")  # skip the reveal's staged timers
    await settle(pilot)


async def test_no_profile_shows_welcome(app: SyzygyApp):
    async with app.run_test() as pilot:
        await settle(pilot)
        assert isinstance(pilot.app.screen, WelcomeScreen)
        assert "No self is configured." in text_of(q(pilot, ".lede", Static))


async def test_create_profile_then_home(app: SyzygyApp):
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("n")
        await pilot.pause()

        values = {
            "display-name": "Blake",
            "birth-date": "1990-08-07",
            "birth-time": "14:22",
            "place-label": "Alexandria, Virginia, USA",
            "latitude": "38.8048",
            "longitude": "-77.0469",
            "timezone": "America/New_York",
        }
        for field_id, value in values.items():
            q(pilot, f"#{field_id}", Input).value = value

        q(pilot, "#review", Button).press()
        await pilot.pause()
        assert "America/New_York" in text_of(q(pilot, "#confirm-body", Static))

        q(pilot, "#confirm", Button).press()
        await settle(pilot)

        assert isinstance(pilot.app.screen, HomeScreen)
        assert pilot.app.profile is not None
        assert pilot.app.profile.display_name == "Blake"
        # The chart was calculated once, at creation, and stored.
        assert pilot.app.profile.natal_chart.placements


async def test_profile_creation_rejects_bad_input(app: SyzygyApp):
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("n")
        await pilot.pause()
        q(pilot, "#display-name", Input).value = "Blake"
        q(pilot, "#birth-date", Input).value = "the seventh of August"
        q(pilot, "#review", Button).press()
        await pilot.pause()
        assert "not an ISO date" in text_of(q(pilot, "#form-error", Static))


async def test_full_ritual_produces_a_complete_reading(app: SyzygyApp, profile, conn):
    async with app.run_test() as pilot:
        await settle(pilot)
        assert isinstance(pilot.app.screen, HomeScreen)  # the home screen's sky preview
        assert str(q(pilot, "#primary-action", Button).label) == TURN_THE_WHEEL

        await turn_the_wheel(pilot)

        screen = pilot.app.screen
        assert isinstance(screen, ReadingScreen)
        assert screen.reading.status == ReadingStatus.COMPLETE
        assert screen.reading.card_draw is not None

        panel = q(pilot, "#reading-panel", ReadingPanel)
        body = text_of(q(pilot, "#reading-body", Static))
        assert "ESOTERIC" in body
        assert screen.reading.interpretation is not None
        assert screen.reading.interpretation.provider_id == FixtureProvider.provider_id

        await pilot.press("2")
        await pilot.pause()
        assert "TODAY" in text_of(q(pilot, "#reading-body", Static))
        assert panel.view.value == "conventional"

        # The stored reading is what the screen is showing.
        stored = get_today(conn, profile.id, FIXED_NOW.astimezone().date().isoformat())
        assert stored is not None
        assert stored.card_draw is not None
        assert stored.card_draw.card_id == screen.reading.card_draw.card_id


async def test_inputs_view_shows_the_exact_model_inputs(app: SyzygyApp, profile):
    async with app.run_test() as pilot:
        await settle(pilot)
        await turn_the_wheel(pilot)

        await pilot.press("i")
        await pilot.pause()
        body = text_of(q(pilot, "#reading-body", Static))

        assert "SELECTED TRANSITS" in body
        assert "PROVENANCE" in body
        assert "fixture" in body  # provider identity is never hidden
        # Only policy-passing transits reach the model: the Moon sextile
        # in the fixture sky is outside the transiting-Moon cap.
        assert "Saturn" in body or "♄" in body
        assert "Pluto" not in body
        # No source chunks were retrieved, and the screen says so rather
        # than implying Crowley grounding (docs/old/DESIGN.md section 23).
        assert "PASSAGES SENT TO THE MODEL" in body
        assert NO_PASSAGES_NOTE in body


async def test_reopening_the_day_does_not_redraw(app: SyzygyApp, services, profile, conn):
    async with app.run_test() as pilot:
        await settle(pilot)
        await turn_the_wheel(pilot)
        first_card = pilot.app.screen.reading.card_draw.card_id

    # A fresh application against the same database - the equivalent of
    # quitting and reopening later the same day.
    reopened = SyzygyApp(services)
    async with reopened.run_test() as pilot:
        await settle(pilot)
        assert isinstance(pilot.app.screen, HomeScreen)
        assert str(q(pilot, "#primary-action", Button).label) == OPEN_TODAYS_READING

        await pilot.press("enter")
        await settle(pilot)
        screen = pilot.app.screen
        assert isinstance(screen, ReadingScreen)
        assert screen.reading.card_draw is not None
        assert screen.reading.card_draw.card_id == first_card

        # And there is still exactly one reading for the day.
        rows = conn.execute(
            "SELECT COUNT(*) AS n FROM readings WHERE profile_id = ?", (profile.id,)
        ).fetchone()
        assert rows["n"] == 1


async def test_failed_interpretation_retries_the_same_card(services, profile, conn):
    services.provider = FailingProvider()
    app = SyzygyApp(services)
    async with app.run_test() as pilot:
        await settle(pilot)
        await turn_the_wheel(pilot)

        screen = pilot.app.screen
        assert isinstance(screen, ReadingScreen)
        assert screen.reading.status == ReadingStatus.INTERPRETATION_FAILED
        drawn_card = screen.reading.card_draw.card_id
        body = text_of(q(pilot, "#reading-body", Static))
        assert "INTERPRETATION IS UNAVAILABLE." in body
        assert "THE ALIGNMENT IS FIXED." in body

        # Retrying reaches a working provider - with the same card.
        services.provider = FixtureProvider()
        await pilot.press("r")
        await settle(pilot)
        assert screen.reading.status == ReadingStatus.COMPLETE
        assert screen.reading.card_draw.card_id == drawn_card


@pytest.mark.parametrize("size", [(100, 32), (80, 24)])
async def test_screens_survive_their_supported_sizes(app: SyzygyApp, profile, size):
    """Ideal and compact terminals (docs/old/DESIGN.md 18.6) both stay fully usable
    end to end - no screen raises or loses its primary action.

    Below-compact sizes (< 80x24) are Milestone 9's dedicated "terminal
    too small" state, covered separately in `test_responsive.py`.
    """
    async with app.run_test(size=size) as pilot:
        await settle(pilot)
        assert q(pilot, "#primary-action", Button).label

        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(pilot.app.screen, WheelScreen)
        # The Wheel renders at whatever size it is given.
        wheel = q(pilot, "#wheel")
        assert wheel.size.width > 0
