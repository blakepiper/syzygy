"""Birthplace geocoding autopopulation on `ProfileCreateScreen` (M10.1).

Exercises the prefill, manual-override, and failure paths through the real
form -> confirm flow, with `resolve_birthplace` faked at the screen's
import site so no real network call or geocoding-extra behavior is
involved (M10.1e).
"""

from __future__ import annotations

from textual.widgets import Button, Input, Static

from syzygy.geocoding import GeocodingFailed, ResolvedPlace
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
