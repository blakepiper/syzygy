"""M10.3: "r" (retry) audit and fix.

The existing `test_failed_interpretation_retries_the_same_card` in
`test_ritual_flow.py` already passed against a lowercase `r` before this
milestone, so this isn't a straightforward logic bug in `action_retry`
itself. Reproducing with `Pilot.press("R")` (what a real terminal sends
for a shifted/caps-locked "r", a distinct key from plain "r" in Textual's
binding system) reproduces the reported symptom exactly: the binding only
ever matched lowercase "r", so retry silently did nothing for that input.
`ReadingScreen.BINDINGS` now binds both cases to `action_retry`.
"""

from __future__ import annotations

from unittest.mock import Mock

from syzygy.domain.reading import ReadingStatus
from syzygy.interpretation.providers.fixture import FixtureProvider
from syzygy.tui.app import SyzygyApp
from syzygy.tui.screens.reading import ReadingScreen
from syzygy.tui.widgets.reading_panel import ReadingPanel

from .test_ritual_flow import FailingProvider, q, settle, text_of, turn_the_wheel


async def test_retry_works_with_an_uppercase_R(services, profile, conn):
    """M10.3a: the root cause - Textual treats "R" as a different key from
    "r", and the binding only ever covered the latter."""
    services.provider = FailingProvider()
    app = SyzygyApp(services)
    async with app.run_test() as pilot:
        await settle(pilot)
        await turn_the_wheel(pilot)

        screen = pilot.app.screen
        assert isinstance(screen, ReadingScreen)
        assert screen.reading.status == ReadingStatus.INTERPRETATION_FAILED
        drawn_card = screen.reading.card_draw.card_id

        services.provider = FixtureProvider()
        await pilot.press("R")
        await settle(pilot)

        assert screen.reading.status == ReadingStatus.COMPLETE
        assert screen.reading.card_draw.card_id == drawn_card


async def test_retry_on_a_complete_reading_is_a_visible_noop(app: SyzygyApp, profile):
    """M10.3b: a stray "r" with nothing to retry must not look identical
    to a broken binding."""
    async with app.run_test() as pilot:
        await settle(pilot)
        await turn_the_wheel(pilot)

        screen = pilot.app.screen
        assert isinstance(screen, ReadingScreen)
        assert screen.reading.status == ReadingStatus.COMPLETE

        screen.app.bell = Mock()
        await pilot.press("r")
        await settle(pilot)

        screen.app.bell.assert_called_once()
        assert screen.reading.status == ReadingStatus.COMPLETE


async def test_retry_hint_only_shown_while_failed_quit_always_shown(services, profile, conn):
    """M10.3c: retry (and quit) are discoverable from the hint line itself,
    not only embedded in the failed-state panel body."""
    services.provider = FailingProvider()
    app = SyzygyApp(services)
    async with app.run_test() as pilot:
        await settle(pilot)
        await turn_the_wheel(pilot)

        screen = pilot.app.screen
        assert isinstance(screen, ReadingScreen)
        assert screen.reading.status == ReadingStatus.INTERPRETATION_FAILED

        keys = text_of(q(pilot, "#reading-keys"))
        assert "[R] RETRY" in keys
        assert "[Q] QUIT" in keys

        services.provider = FixtureProvider()
        await pilot.press("r")
        await settle(pilot)
        assert screen.reading.status == ReadingStatus.COMPLETE

        keys = text_of(q(pilot, "#reading-keys"))
        assert "[R] RETRY" not in keys
        assert "[Q] QUIT" in keys


async def test_archive_reopened_reading_never_offers_retry(services, profile, conn):
    """A read-only archive reopen (`interpret=False`) must not invite a
    retry it will silently refuse (`action_retry`'s `_may_interpret` guard)."""
    from syzygy.domain.reading import Reading

    services.provider = FailingProvider()
    app = SyzygyApp(services)
    async with app.run_test() as pilot:
        await settle(pilot)
        await turn_the_wheel(pilot)
        failed_reading: Reading = pilot.app.screen.reading
        assert failed_reading.status == ReadingStatus.INTERPRETATION_FAILED

    reopened = SyzygyApp(services)
    async with reopened.run_test() as pilot:
        await settle(pilot)
        pilot.app.push_screen(ReadingScreen(failed_reading, interpret=False))
        await settle(pilot)

        keys = text_of(q(pilot, "#reading-keys"))
        assert "[R] RETRY" not in keys
        assert isinstance(q(pilot, "#reading-panel", ReadingPanel), ReadingPanel)
