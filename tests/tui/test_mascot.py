"""The mascot appears past the first launch (M17.3).

It was constructed in exactly one place - `welcome.py`, a screen a
returning user never sees - so the artwork shipped and nobody who had used
the application before ever saw it. It now appears in the opening sequence
(which every launch plays) and as a companion on home wherever there are
columns or rows to spare.

The constraint that matters more than its presence: it must never displace
the SELF/COSMOS/CHANCE triad or push a control below the fold.
`tests/tui/test_layout.py` is the arbiter of that, and the assertions here
are deliberately about *where* and *whether*, not about how it looks.
"""

from __future__ import annotations

import pytest

from syzygy.tui.app import SyzygyApp
from syzygy.tui.screens.base import IDEAL_HEIGHT, IDEAL_WIDTH, TALL_HEIGHT, WIDE_WIDTH
from syzygy.tui.screens.startup import StartupScreen
from syzygy.tui.screens.too_small import MIN_HEIGHT, MIN_WIDTH
from syzygy.tui.widgets.brand import Mascot, MascotState

from .test_ritual_flow import settle, turn_the_wheel

FLOOR = (MIN_WIDTH, MIN_HEIGHT)
IDEAL = (IDEAL_WIDTH, IDEAL_HEIGHT)
WIDE = (WIDE_WIDTH, 40)
TALL = (IDEAL_WIDTH, TALL_HEIGHT)


def on_screen(widget) -> bool:
    return widget.screen.region.contains_region(widget.region)


# -- where it appears -------------------------------------------------------


async def test_the_opening_sequence_shows_the_mascot(app: SyzygyApp, profile):
    """The launch path a returning user actually takes."""
    async with app.run_test(size=IDEAL) as pilot:
        await pilot.pause()
        assert isinstance(pilot.app.screen, StartupScreen)
        assert pilot.app.screen.query_one("#startup-mascot", Mascot)


@pytest.mark.parametrize("size", [WIDE, TALL])
async def test_home_shows_the_companion_where_there_is_room(app: SyzygyApp, profile, size):
    async with app.run_test(size=size) as pilot:
        await settle(pilot)
        mascot = pilot.app.screen.query_one("#home-mascot", Mascot)
        assert mascot.display
        assert mascot.size.width > 0 and mascot.size.height > 0


@pytest.mark.parametrize("size", [FLOOR, IDEAL])
async def test_home_drops_the_companion_where_the_rows_are_needed(
    app: SyzygyApp, profile, size
):
    async with app.run_test(size=size) as pilot:
        await settle(pilot)
        mascot = pilot.app.screen.query_one("#home-mascot", Mascot)
        assert mascot.size.height == 0


@pytest.mark.parametrize("size", [FLOOR, IDEAL, WIDE, TALL, (200, 55)])
async def test_the_companion_never_displaces_the_triad_or_the_action(
    app: SyzygyApp, profile, size
):
    """The condition on M17.3a, at every tier."""
    async with app.run_test(size=size) as pilot:
        await settle(pilot)
        screen = pilot.app.screen

        assert on_screen(screen.query_one("#primary-action"))
        for name in ("self", "cosmos", "chance"):
            column = screen.query_one(f"#home-{name}")
            assert column.size.width > 0 and column.size.height > 0


# -- what it reacts to ------------------------------------------------------


async def test_the_companion_waits_before_a_draw(app: SyzygyApp, profile):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        assert pilot.app.screen.query_one("#home-mascot", Mascot).state is MascotState.WAITING


async def test_the_companion_reacts_to_a_finished_reading(services, profile):
    app = SyzygyApp(services)
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        await turn_the_wheel(pilot)
        await pilot.press("escape")
        await settle(pilot)

        mascot = pilot.app.screen.query_one("#home-mascot", Mascot)
        assert mascot.state is MascotState.COMPLETE
        assert mascot.has_class("-mascot-complete")
        assert not mascot.has_class("-mascot-waiting")


async def test_the_companion_recedes_while_chance_is_entering(app: SyzygyApp, profile):
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        home = pilot.app.screen
        mascot = home.query_one("#home-mascot", Mascot)

        home.action_primary()
        await pilot.pause()
        assert mascot.state is MascotState.DRAWING


def test_a_mascot_with_no_state_carries_no_state_class():
    """Decoration - the opening sequence, the welcome copy - is not a
    status display (M17.3b)."""
    mascot = Mascot()
    assert mascot.state is None
    assert not any(
        mascot.has_class(f"-mascot-{state.value}") for state in MascotState
    )


# -- and how it fails -------------------------------------------------------


async def test_an_undecodable_asset_degrades_to_nothing(services, profile, monkeypatch):
    """The `SilentTheme` precedent: decoration never becomes a traceback,
    and never becomes the reason a screen fails to render (M17.3c)."""
    from syzygy.tui.widgets import pixel_art

    def explode(*_args, **_kwargs):
        raise OSError("no such resource")

    monkeypatch.setattr(pixel_art, "render_braille", explode)
    monkeypatch.setattr(pixel_art, "fit_braille_size", explode)

    app = SyzygyApp(services)
    async with app.run_test(size=WIDE) as pilot:
        await settle(pilot)
        screen = pilot.app.screen
        assert screen.__class__.__name__ == "HomeScreen"
        assert on_screen(screen.query_one("#primary-action"))
        assert screen.query_one("#home-mascot", Mascot).visual.plain.strip() == ""
