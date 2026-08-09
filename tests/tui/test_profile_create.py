"""`ProfileCreateScreen`: geocoding autopopulation (M10.1) and the
keyboard path through the form (M11.1).

Exercises the prefill, manual-override, and failure paths through the real
form -> confirm flow, with `resolve_birthplace` faked at the screen's
import site so no real network call or geocoding dependency behavior is
involved (M10.1e).

The M11.1 tests at the bottom deliberately drive the screen with *keys
only* - no `pilot.click`, no assigning `Input.value` directly. The bug they
cover (initial focus landing on the scroll container, so every field
received the previous field's text) was invisible to every test that
filled the form programmatically.
"""

from __future__ import annotations

from textual.keys import _character_to_key
from textual.widgets import Button, Input, Static

from syzygy.geocoding import GeocodingFailed, ResolvedPlace
from syzygy.storage.profiles import list_profiles
from syzygy.tui.app import SyzygyApp
from syzygy.tui.screens import profile_create as profile_create_module


def text_of(widget: Static) -> str:
    return widget.visual.plain


def q(pilot, selector: str, expect_type=None):
    if expect_type is None:
        return pilot.app.screen.query_one(selector)
    return pilot.app.screen.query_one(selector, expect_type)


async def settle(pilot, cycles: int = 3) -> None:
    for _ in range(cycles):
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()


async def _open_profile_create(pilot) -> None:
    await pilot.pause()
    await pilot.press("n")
    await pilot.pause()


def _fill(pilot, values: dict[str, str]) -> None:
    for field_id, value in values.items():
        q(pilot, f"#{field_id}", Input).value = value


async def test_geocoding_prefills_confirm_panel_when_coordinates_blank(
    app: SyzygyApp, monkeypatch
):
    calls: list[str] = []

    def fake_resolve(place_label: str) -> ResolvedPlace:
        calls.append(place_label)
        return ResolvedPlace(latitude=38.8048, longitude=-77.0469, timezone="America/New_York")

    monkeypatch.setattr(profile_create_module, "resolve_birthplace", fake_resolve)

    async with app.run_test() as pilot:
        await _open_profile_create(pilot)
        _fill(
            pilot,
            {
                "display-name": "Blake",
                "birth-date": "1990-08-07",
                "birth-time": "14:22",
                "place-label": "Alexandria, Virginia, USA",
            },
        )
        q(pilot, "#review", Button).press()
        await settle(pilot)

        assert calls == ["Alexandria, Virginia, USA"]
        assert q(pilot, "#latitude", Input).value == "38.8048"
        assert q(pilot, "#longitude", Input).value == "-77.0469"
        assert q(pilot, "#timezone", Input).value == "America/New_York"

        body = text_of(q(pilot, "#confirm-body", Static))
        assert "Resolved (auto-resolved):" in body
        assert "America/New_York" in body
        assert not q(pilot, "#profile-confirm").has_class("hidden")


async def test_geocoding_is_skipped_when_coordinates_entered_manually(
    app: SyzygyApp, monkeypatch
):
    def fail_if_called(place_label: str) -> ResolvedPlace:
        raise AssertionError("resolve_birthplace should not be called for manual entry")

    monkeypatch.setattr(profile_create_module, "resolve_birthplace", fail_if_called)

    async with app.run_test() as pilot:
        await _open_profile_create(pilot)
        _fill(
            pilot,
            {
                "display-name": "Blake",
                "birth-date": "1990-08-07",
                "birth-time": "14:22",
                "place-label": "Alexandria, Virginia, USA",
                "latitude": "38.8048",
                "longitude": "-77.0469",
                "timezone": "America/New_York",
            },
        )
        q(pilot, "#review", Button).press()
        await settle(pilot)

        body = text_of(q(pilot, "#confirm-body", Static))
        assert "Resolved:" in body
        assert "(auto-resolved)" not in body
        assert not q(pilot, "#profile-confirm").has_class("hidden")


async def test_geocoding_failure_leaves_the_form_open_for_manual_entry(
    app: SyzygyApp, monkeypatch
):
    def fake_resolve(place_label: str) -> ResolvedPlace:
        raise GeocodingFailed(f"no location found for {place_label!r}")

    monkeypatch.setattr(profile_create_module, "resolve_birthplace", fake_resolve)

    async with app.run_test() as pilot:
        await _open_profile_create(pilot)
        _fill(
            pilot,
            {
                "display-name": "Blake",
                "birth-date": "1990-08-07",
                "birth-time": "14:22",
                "place-label": "Nowhereville",
            },
        )
        q(pilot, "#review", Button).press()
        await settle(pilot)

        # Never blocks profile creation on a geocoding failure: still on
        # the form phase, with the manual fields open and the button live.
        assert not q(pilot, "#profile-form").has_class("hidden")
        assert q(pilot, "#profile-confirm").has_class("hidden")
        assert not q(pilot, "#review", Button).disabled

        error = text_of(q(pilot, "#form-error", Static))
        assert "Could not resolve a location for 'Nowhereville'" in error
        assert "enter coordinates manually" in error


async def test_geocoding_transport_error_never_strands_the_form(app: SyzygyApp, monkeypatch):
    """M11.1c: `geopy` raises its own transport exceptions (DNS, TLS,
    timeout) that are neither `GeocodingUnavailable` nor `GeocodingFailed`.
    One escaping the worker used to leave REVIEW disabled behind a
    "Resolving…" message that never resolved - an unrecoverable form."""

    def fake_resolve(place_label: str) -> ResolvedPlace:
        raise TimeoutError("nominatim did not respond")

    monkeypatch.setattr(profile_create_module, "resolve_birthplace", fake_resolve)

    async with app.run_test() as pilot:
        await _open_profile_create(pilot)
        _fill(
            pilot,
            {
                "display-name": "Blake",
                "birth-date": "1990-08-07",
                "birth-time": "14:22",
                "place-label": "Alexandria, Virginia, USA",
            },
        )
        q(pilot, "#review", Button).press()
        await settle(pilot)

        assert not q(pilot, "#review", Button).disabled
        error = text_of(q(pilot, "#form-error", Static))
        assert "Resolving" not in error
        assert "TimeoutError" in error
        assert "enter coordinates manually" in error


async def test_focused_input_takes_a_literal_q_keystroke_over_quit(app: SyzygyApp):
    """M10.2b: `SyzygyApp`'s app-level quit binding must not steal a
    literal "q" keystroke from a focused form field - Textual gives a
    focused widget's own key handling first refusal, but this is worth
    asserting explicitly since M10.2 is specifically about "q" behavior.
    """
    async with app.run_test() as pilot:
        await _open_profile_create(pilot)
        display_name = q(pilot, "#display-name", Input)
        display_name.focus()
        await pilot.pause()

        await pilot.press("q")
        await pilot.pause()

        assert display_name.value == "q"
        assert not pilot.app._exit
        assert isinstance(pilot.app.screen, profile_create_module.ProfileCreateScreen)


# -- M11.1: the keyboard path through the form ---------------------------


async def _type(pilot, text: str) -> None:
    """Type `text` one key at a time, the way a terminal delivers it."""
    await pilot.press(*(_character_to_key(character) for character in text))


async def test_first_field_takes_focus_on_open(app: SyzygyApp):
    """M11.1: initial focus used to land on the `#profile-form` scroll
    container (focusable by default, and first in the DOM), so everything
    typed before the user's first Tab was silently discarded."""
    async with app.run_test() as pilot:
        await _open_profile_create(pilot)

        assert pilot.app.focused is q(pilot, "#display-name", Input)

        await _type(pilot, "Blake")
        assert q(pilot, "#display-name", Input).value == "Blake"


async def test_tab_walks_the_fields_without_shifting_values(app: SyzygyApp):
    """The visible symptom of the focus bug: each field received the
    *previous* field's text, so the name held a date and the date held a
    time - and validation then blamed the wrong field."""
    async with app.run_test() as pilot:
        await _open_profile_create(pilot)

        for text in ("Blake", "1990-08-07", "14:22", "Alexandria"):
            await _type(pilot, text)
            await pilot.press("tab")

        assert q(pilot, "#display-name", Input).value == "Blake"
        assert q(pilot, "#birth-date", Input).value == "1990-08-07"
        assert q(pilot, "#birth-time", Input).value == "14:22"
        assert q(pilot, "#place-label", Input).value == "Alexandria"


async def test_enter_from_a_field_reviews_the_form(app: SyzygyApp, monkeypatch):
    """M11.1b: ENTER had no handler, so the only way off the form was to
    Tab all the way to REVIEW - undiscoverable, and not what ENTER means
    anywhere else in the app."""

    def fail_if_called(place_label: str) -> ResolvedPlace:
        raise AssertionError("coordinates were entered by hand")

    monkeypatch.setattr(profile_create_module, "resolve_birthplace", fail_if_called)

    async with app.run_test() as pilot:
        await _open_profile_create(pilot)
        for text in ("Blake", "1990-08-07", "14:22", "Alexandria", "38.8048", "-77.0469"):
            await _type(pilot, text)
            await pilot.press("tab")
        await _type(pilot, "America/New_York")

        # ENTER from the last field, without ever reaching the button.
        await pilot.press("enter")
        await settle(pilot)

        assert not q(pilot, "#profile-confirm").has_class("hidden")
        assert "Alexandria" in text_of(q(pilot, "#confirm-body", Static))


async def test_keyboard_only_walk_creates_a_profile(app: SyzygyApp, conn, monkeypatch):
    """The whole point of M11.1: a user who only ever touches the keyboard
    can get from an empty form to a saved profile."""

    def fail_if_called(place_label: str) -> ResolvedPlace:
        raise AssertionError("coordinates were entered by hand")

    monkeypatch.setattr(profile_create_module, "resolve_birthplace", fail_if_called)

    async with app.run_test() as pilot:
        await _open_profile_create(pilot)
        for text in ("Blake", "1990-08-07", "14:22", "Alexandria", "38.8048", "-77.0469"):
            await _type(pilot, text)
            await pilot.press("tab")
        await _type(pilot, "America/New_York")

        await pilot.press("enter")  # review
        await settle(pilot)
        # Focus follows the phase change, so the second ENTER confirms.
        assert pilot.app.focused is q(pilot, "#confirm", Button)

        await pilot.press("enter")  # confirm
        await settle(pilot)

        saved = list_profiles(conn)
        assert [profile.display_name for profile in saved] == ["Blake"]
        assert saved[0].birth_data.local_date == "1990-08-07"
        assert saved[0].birth_data.timezone == "America/New_York"
        assert pilot.app.screen.id == "home" or type(pilot.app.screen).__name__ == "HomeScreen"


async def test_enter_is_ignored_while_a_lookup_is_in_flight(app: SyzygyApp, monkeypatch):
    """REVIEW is disabled during geocoding; ENTER must respect that rather
    than queueing a second lookup behind the first."""
    calls: list[str] = []
    release = False

    def fake_resolve(place_label: str) -> ResolvedPlace:
        calls.append(place_label)
        while not release:  # held until the test lets it finish
            pass
        return ResolvedPlace(latitude=38.8048, longitude=-77.0469, timezone="America/New_York")

    monkeypatch.setattr(profile_create_module, "resolve_birthplace", fake_resolve)

    async with app.run_test() as pilot:
        await _open_profile_create(pilot)
        _fill(
            pilot,
            {
                "display-name": "Blake",
                "birth-date": "1990-08-07",
                "birth-time": "14:22",
                "place-label": "Alexandria",
            },
        )
        q(pilot, "#place-label", Input).focus()
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()
        assert q(pilot, "#review", Button).disabled

        await pilot.press("enter")
        await pilot.pause()
        assert calls == ["Alexandria"]

        release = True
        await settle(pilot)
        assert calls == ["Alexandria"]
