"""Deleting a profile from the TUI (M11.2).

Deletion is destructive and irreversible - it takes the profile's readings
with it - so these tests care as much about what *doesn't* happen (no
single-keypress delete, no stray-ENTER delete, no app left holding a
profile whose row is gone) as about the delete itself.
"""

from __future__ import annotations

import uuid

import pytest
from textual.widgets import Button, ListView, Static

from syzygy.domain.profile import Profile
from syzygy.storage.profiles import insert_profile, list_profiles
from syzygy.tui.app import SyzygyApp
from syzygy.tui.screens.profile_select import ProfileSelectScreen
from syzygy.tui.screens.welcome import WelcomeScreen

from .conftest import BIRTH_DATA, FIXED_NOW, NATAL_CHART
from .test_ritual_flow import q, settle, text_of, turn_the_wheel


@pytest.fixture
def second_profile(conn) -> Profile:
    saved = Profile(
        id=str(uuid.uuid4()),
        display_name="Alex",
        birth_data=BIRTH_DATA,
        natal_chart=NATAL_CHART,
        created_at_utc=FIXED_NOW,
        updated_at_utc=FIXED_NOW,
    )
    insert_profile(conn, saved)
    return saved


async def _open_profiles(pilot) -> None:
    await settle(pilot)
    if not isinstance(pilot.app.screen, ProfileSelectScreen):
        await pilot.press("p")
    await pilot.pause()
    assert isinstance(pilot.app.screen, ProfileSelectScreen)


def _confirm_hidden(pilot) -> bool:
    return q(pilot, "#profile-delete-confirm").has_class("hidden")


async def test_d_asks_before_deleting_anything(app: SyzygyApp, profile, conn):
    async with app.run_test() as pilot:
        await _open_profiles(pilot)
        await pilot.press("d")
        await pilot.pause()

        assert not _confirm_hidden(pilot)
        # Nothing destroyed yet.
        assert len(list_profiles(conn)) == 1

        body = text_of(q(pilot, "#delete-body", Static))
        assert "Blake" in body
        assert "cannot be undone" in body


async def test_confirm_panel_names_the_readings_that_will_be_lost(
    app: SyzygyApp, profile, conn
):
    async with app.run_test() as pilot:
        await settle(pilot)
        await turn_the_wheel(pilot)
        await settle(pilot)

        await pilot.press("escape")
        await _open_profiles(pilot)
        await pilot.press("d")
        await pilot.pause()

        body = text_of(q(pilot, "#delete-body", Static))
        assert "1 reading will be deleted" in body


async def test_enter_on_the_confirm_panel_does_not_delete(app: SyzygyApp, profile, conn):
    """CANCEL takes focus, not DELETE: a reflexive ENTER on a destructive
    prompt must not be what destroys the data."""
    async with app.run_test() as pilot:
        await _open_profiles(pilot)
        await pilot.press("d")
        await pilot.pause()

        assert pilot.app.focused is q(pilot, "#delete-cancel", Button)

        await pilot.press("enter")
        await settle(pilot)

        assert len(list_profiles(conn)) == 1
        assert _confirm_hidden(pilot)


async def test_escape_cancels_the_confirmation(app: SyzygyApp, profile, conn):
    async with app.run_test() as pilot:
        await _open_profiles(pilot)
        await pilot.press("d")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert _confirm_hidden(pilot)
        assert len(list_profiles(conn)) == 1
        assert isinstance(pilot.app.screen, ProfileSelectScreen)


async def test_confirming_deletes_the_profile_and_its_readings(
    app: SyzygyApp, profile, second_profile, conn
):
    async with app.run_test() as pilot:
        await _open_profiles(pilot)
        listing = q(pilot, "#profile-list", ListView)
        assert len(listing.children) == 2

        await pilot.press("d")
        await pilot.pause()
        q(pilot, "#delete-confirm", Button).press()
        await settle(pilot)

        remaining = list_profiles(conn)
        assert [p.display_name for p in remaining] == ["Alex"]
        assert len(q(pilot, "#profile-list", ListView).children) == 1
        assert _confirm_hidden(pilot)


async def test_deleting_the_active_profile_clears_it(
    app: SyzygyApp, profile, second_profile, conn
):
    """M11.2c: the app must not keep a `Profile` whose row no longer
    exists - it would try to write readings against a dangling id."""
    async with app.run_test() as pilot:
        await settle(pilot)
        pilot.app.set_profile(profile)
        await _open_profiles(pilot)

        # The fixture profile ("Blake") is created first, so it is first
        # in creation order and highlighted by default.
        await pilot.press("d")
        await pilot.pause()
        assert "currently being read for" in text_of(q(pilot, "#delete-body", Static))

        q(pilot, "#delete-confirm", Button).press()
        await settle(pilot)

        assert pilot.app.profile is None
        # Stays on the picker rather than silently adopting the survivor.
        assert isinstance(pilot.app.screen, ProfileSelectScreen)


async def test_deleting_the_last_profile_returns_to_welcome(app: SyzygyApp, profile, conn):
    async with app.run_test() as pilot:
        await settle(pilot)
        pilot.app.set_profile(profile)
        await _open_profiles(pilot)
        await pilot.press("d")
        await pilot.pause()
        q(pilot, "#delete-confirm", Button).press()
        await settle(pilot)

        assert list_profiles(conn) == []
        assert pilot.app.profile is None
        assert isinstance(pilot.app.screen, WelcomeScreen)


async def test_d_with_an_empty_list_is_a_visible_noop(app: SyzygyApp, conn):
    """No profiles at all: `d` must not open a confirmation for nothing."""
    async with app.run_test() as pilot:
        await settle(pilot)
        pilot.app.push_screen("profile_select")
        await pilot.pause()

        await pilot.press("d")
        await pilot.pause()

        assert _confirm_hidden(pilot)
