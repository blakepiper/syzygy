"""Every menu is completable with arrows and `enter` alone (M17.5).

Textual moves focus on `tab`/`shift+tab` only. Nothing in `syzygy.tui`
handled arrow keys, so every row of buttons in the application - the
delete confirmation, the local-setup actions, the confirm/edit pair on
profile creation - was mouse-or-tab only. These tests use neither: no
mouse events and no `tab`, so a screen that can only be completed that way
fails here.

The other half is not stealing keys. `Input` and `ListView` bind the
arrows for their own purposes, and a base handler that ran first would
have broken text editing and list navigation to fix button rows.
"""

from __future__ import annotations

import uuid

from textual.widgets import Input, ListView

from syzygy.storage.profiles import insert_profile
from syzygy.tui.app import SyzygyApp
from syzygy.tui.screens.home import HomeScreen
from syzygy.tui.screens.profile_create import ProfileCreateScreen

from .conftest import FIXED_NOW
from .test_ritual_flow import settle, turn_the_wheel


def focused_id(pilot) -> str | None:
    focused = pilot.app.focused
    return None if focused is None else focused.id


async def press_until(pilot, key: str, target_id: str, *, limit: int = 12) -> bool:
    """Press `key` until `target_id` has focus. False if it never does."""
    for _ in range(limit):
        if focused_id(pilot) == target_id:
            return True
        await pilot.press(key)
        await pilot.pause()
    return focused_id(pilot) == target_id


# -- the arrows move focus --------------------------------------------------


async def test_a_button_row_cycles_with_left_and_right(app: SyzygyApp, profile):
    """The delete confirmation is two buttons side by side, and was
    unreachable without a mouse or a Tab."""
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("p")
        await settle(pilot)
        await pilot.press("d")
        await pilot.pause()

        # CANCEL holds focus on a destructive confirmation (M11.2).
        assert focused_id(pilot) == "delete-cancel"
        await pilot.press("left")
        await pilot.pause()
        assert focused_id(pilot) == "delete-confirm"
        await pilot.press("right")
        await pilot.pause()
        assert focused_id(pilot) == "delete-cancel"


async def test_a_button_row_also_cycles_with_up_and_down(app: SyzygyApp, profile):
    """`up`/`left` are one direction and `down`/`right` the other,
    whichever way the row happens to be laid out."""
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("p")
        await settle(pilot)
        await pilot.press("d")
        await pilot.pause()

        await pilot.press("up")
        await pilot.pause()
        assert focused_id(pilot) == "delete-confirm"
        await pilot.press("down")
        await pilot.pause()
        assert focused_id(pilot) == "delete-cancel"


async def test_the_delete_confirmation_can_be_cancelled_with_arrows_and_enter(
    app: SyzygyApp, profile
):
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("p")
        await settle(pilot)
        await pilot.press("d")
        await pilot.pause()

        assert await press_until(pilot, "right", "delete-cancel")
        await pilot.press("enter")
        await settle(pilot)

        assert pilot.app.screen.query_one("#profile-delete-confirm").has_class("hidden")
        assert isinstance(pilot.app.focused, ListView)


async def test_the_profile_form_steps_between_fields_with_up_and_down(app: SyzygyApp):
    """`Input` binds left/right for the cursor but not up/down, so up/down
    is what walks a vertical form."""
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("n")
        await settle(pilot)
        assert isinstance(pilot.app.screen, ProfileCreateScreen)
        assert focused_id(pilot) == "display-name"

        await pilot.press("down")
        await pilot.pause()
        assert focused_id(pilot) == "birth-date"
        await pilot.press("down")
        await pilot.pause()
        assert focused_id(pilot) == "birth-time"
        await pilot.press("up")
        await pilot.pause()
        assert focused_id(pilot) == "birth-date"


async def test_the_whole_profile_form_is_completable_without_tab_or_a_mouse(app: SyzygyApp):
    """Arrows to each field, typing, arrows to the confirm row, enter."""
    values = {
        "display-name": "Blake",
        "birth-date": "1990-08-07",
        "birth-time": "14:22",
        "place-label": "Alexandria, Virginia, USA",
        "latitude": "38.8048",
        "longitude": "-77.0469",
        "timezone": "America/New_York",
    }
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("n")
        await settle(pilot)

        for field_id, value in values.items():
            assert await press_until(pilot, "down", field_id), f"never reached {field_id}"
            for character in value:
                await pilot.press(character if character != " " else "space")
            await pilot.pause()

        # `enter` from any field reviews (M11.1b); the confirm row then
        # takes focus and `enter` again commits.
        await pilot.press("enter")
        await settle(pilot)
        assert focused_id(pilot) == "confirm"

        await pilot.press("left")
        await pilot.pause()
        assert focused_id(pilot) == "edit"
        await pilot.press("right")
        await pilot.pause()
        assert focused_id(pilot) == "confirm"

        await pilot.press("enter")
        await settle(pilot)
        assert isinstance(pilot.app.screen, HomeScreen)


async def test_the_home_action_is_focused_and_activates_with_enter(app: SyzygyApp, profile):
    async with app.run_test() as pilot:
        await settle(pilot)
        assert focused_id(pilot) == "primary-action"
        await pilot.press("enter")
        await pilot.pause()
        assert pilot.app.screen.__class__.__name__ == "WheelScreen"


async def test_local_setup_focuses_its_action_row(app: SyzygyApp, profile):
    """Three buttons outside the scroll region; without an initial focus
    the arrows had nothing to move from (M17.5c)."""
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("m")
        await settle(pilot)
        pilot.app.push_screen("local_setup")
        await settle(pilot)

        assert focused_id(pilot) == "setup-primary"
        assert await press_until(pilot, "right", "setup-cancel")
        await pilot.press("right")
        await pilot.pause()
        # The row wraps rather than dead-ending at its last button.
        assert focused_id(pilot) == "setup-primary"


async def test_the_model_screen_opens_on_its_list(app: SyzygyApp, profile):
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("m")
        await settle(pilot)
        assert focused_id(pilot) == "model-list"


async def test_the_archive_opens_on_its_list_and_enter_opens_a_reading(services, profile):
    app = SyzygyApp(services)
    async with app.run_test() as pilot:
        await settle(pilot)
        await turn_the_wheel(pilot)
        await pilot.press("escape")
        await settle(pilot)

        await pilot.press("a")
        await settle(pilot)
        assert focused_id(pilot) == "archive-list"
        await pilot.press("enter")
        await settle(pilot)
        assert pilot.app.screen.__class__.__name__ == "ReadingScreen"


# -- and does not steal them -------------------------------------------------


async def test_an_input_keeps_its_own_left_and_right(app: SyzygyApp):
    """Cursor movement inside a field must not become focus movement."""
    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("n")
        await settle(pilot)

        field = pilot.app.screen.query_one("#display-name", Input)
        for character in "abc":
            await pilot.press(character)
        await pilot.pause()
        assert field.cursor_position == 3

        await pilot.press("left")
        await pilot.pause()
        assert pilot.app.focused is field
        assert field.cursor_position == 2

        await pilot.press("right")
        await pilot.pause()
        assert pilot.app.focused is field
        assert field.cursor_position == 3


async def test_a_list_keeps_its_own_up_and_down(services, conn, profile):
    """Two profiles, so `down` has to move the list cursor rather than
    jump focus out of the list."""
    second = profile.model_copy(
        update={"id": str(uuid.uuid4()), "display_name": "Other", "created_at_utc": FIXED_NOW}
    )
    insert_profile(conn, second)

    app = SyzygyApp(services)
    async with app.run_test() as pilot:
        await settle(pilot)
        listing = pilot.app.screen.query_one("#profile-list", ListView)
        assert pilot.app.focused is listing
        assert listing.index == 0

        await pilot.press("down")
        await pilot.pause()
        assert pilot.app.focused is listing
        assert listing.index == 1

        await pilot.press("up")
        await pilot.pause()
        assert listing.index == 0


async def test_the_wheel_keeps_its_disturbance_keys(app: SyzygyApp, profile):
    """`left`/`right` disturb the wheel's phase; they must not move focus
    off it mid-draw."""
    from syzygy.tui.widgets.wheel import WheelWidget

    async with app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("enter")
        await pilot.pause()

        wheel = pilot.app.screen.query_one("#wheel", WheelWidget)
        assert pilot.app.focused is wheel
        before = wheel.phase

        await pilot.press("left")
        await pilot.pause()
        assert pilot.app.focused is wheel
        assert wheel.phase != before


async def test_a_reading_pane_still_scrolls_with_the_arrows(services, profile):
    async with SyzygyApp(services).run_test(size=(80, 24)) as pilot:
        await settle(pilot)
        await turn_the_wheel(pilot)
        await settle(pilot, 8)

        pane = pilot.app.screen.query_one("#reading-panel")
        pane.focus()
        await pilot.pause()
        before = pane.scroll_offset.y

        for _ in range(4):
            await pilot.press("down")
        await pilot.pause()

        assert pilot.app.focused is pane
        assert pane.scroll_offset.y >= before
