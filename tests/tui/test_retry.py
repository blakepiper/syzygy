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


# -- M11.4: a reading stranded in INTERPRETING ---------------------------


def _strand_in_interpreting(conn, reading):
    """Persist the state a process leaves behind when it stops between
    `begin_interpreting` and the provider's reply."""
    from syzygy.storage import readings as readings_store

    from .conftest import FIXED_NOW

    return readings_store.begin_interpreting(conn, reading.id, now=FIXED_NOW)


async def _drawn_reading(conn, profile):
    from syzygy.clock import FixedClock
    from syzygy.sortes.entropy import EntropyCollector
    from syzygy.storage.reading_service import draw_todays_reading

    from .conftest import FIXED_NOW, FixtureAstrologyEngine

    return draw_todays_reading(
        conn,
        profile,
        FixedClock(FIXED_NOW),
        FixtureAstrologyEngine(),
        EntropyCollector(session_nonce=b"probe"),
    )


async def test_a_reading_stranded_in_interpreting_is_retryable(services, profile, conn):
    """M11.4a, the reproduced cause. A reading left `INTERPRETING` by a
    killed process satisfied neither `on_mount`'s start condition nor
    `action_retry`'s old `== INTERPRETATION_FAILED` guard, so the screen
    showed "INTERPRETING…" forever with a spinner that wasn't running and
    an "r" key that only rang the bell. It is the canonical reading for
    that date, so there was no way out for the rest of the day.

    The realistic route there: select llama.cpp with no server running
    (M11.3), wait out part of the 120s provider timeout, give up, quit.
    """
    stranded = _strand_in_interpreting(conn, await _drawn_reading(conn, profile))
    assert stranded.status == ReadingStatus.INTERPRETING

    app = SyzygyApp(services)
    async with app.run_test() as pilot:
        await settle(pilot)
        pilot.app.set_profile(profile)
        pilot.app.push_screen(ReadingScreen(stranded))
        await settle(pilot)

        screen = pilot.app.screen
        card_before = screen.reading.card_draw.card_id

        # The screen must not claim to be working when nothing is.
        assert "INTERRUPTED" in text_of(q(pilot, "#reading-body"))
        assert "[R] RETRY" in text_of(q(pilot, "#reading-keys"))

        await pilot.press("r")
        await settle(pilot)

        assert screen.reading.status == ReadingStatus.COMPLETE
        # M11.4c: the same card, never a redraw.
        assert screen.reading.card_draw.card_id == card_before


async def test_stranded_reading_says_interrupted_not_in_progress(services, profile, conn):
    stranded = _strand_in_interpreting(conn, await _drawn_reading(conn, profile))

    app = SyzygyApp(services)
    async with app.run_test() as pilot:
        await settle(pilot)
        pilot.app.set_profile(profile)
        pilot.app.push_screen(ReadingScreen(stranded))
        await settle(pilot)

        body = text_of(q(pilot, "#reading-body"))
        assert "INTERPRETATION WAS INTERRUPTED" in body
        assert "IN PROGRESS" not in body


async def test_a_stranded_reading_reopened_from_the_archive_offers_no_retry(
    services, profile, conn
):
    """Read-only reopens must still not invite a retry they would refuse."""
    stranded = _strand_in_interpreting(conn, await _drawn_reading(conn, profile))

    app = SyzygyApp(services)
    async with app.run_test() as pilot:
        await settle(pilot)
        pilot.app.push_screen(ReadingScreen(stranded, interpret=False))
        await settle(pilot)

        assert "[R] RETRY" not in text_of(q(pilot, "#reading-keys"))


async def test_a_retry_in_flight_shows_progress_and_hides_the_retry_hint(
    services, profile, conn
):
    """M11.4d: while a retry is actually running the screen says so - and
    a second "r" mid-flight must not stack a second provider call."""
    import asyncio

    from syzygy.domain.interpretation import InterpretationContext, InterpretationResult

    release = asyncio.Event()
    calls = 0

    class SlowProvider:
        provider_id = "slow"
        model_id = "slow"

        async def interpret(self, context: InterpretationContext) -> InterpretationResult:
            nonlocal calls
            calls += 1
            await release.wait()
            return await FixtureProvider().interpret(context)

    services.provider = FailingProvider()
    app = SyzygyApp(services)
    async with app.run_test() as pilot:
        await settle(pilot)
        await turn_the_wheel(pilot)
        screen = pilot.app.screen
        assert screen.reading.status == ReadingStatus.INTERPRETATION_FAILED

        services.provider = SlowProvider()
        await pilot.press("r")
        await pilot.pause()

        # The waiting indicator carries the activity now (M23); the title
        # carries only what is true of the reading itself.
        assert "INTERPRETING" in text_of(q(pilot, "#reading-waiting"))
        assert "THE ALIGNMENT IS FIXED." in text_of(q(pilot, "#reading-title"))
        assert "[R] RETRY" not in text_of(q(pilot, "#reading-keys"))

        # Retry is not offered while one is running, so a second press is
        # a visible no-op rather than a second call.
        screen.app.bell = Mock()
        await pilot.press("r")
        await pilot.pause()
        screen.app.bell.assert_called_once()

        release.set()
        await settle(pilot)

        assert calls == 1
        assert screen.reading.status == ReadingStatus.COMPLETE
        assert "[R] RETRY" not in text_of(q(pilot, "#reading-keys"))


async def test_interpretation_failure_actually_reaches_the_failed_status(
    services, profile, conn
):
    """M11.4b: retry is only offered from INTERPRETATION_FAILED, so a
    provider error that left the row in INTERPRETING would make retry
    permanently unreachable. Assert the status the row actually lands on,
    not just what the screen renders."""
    from syzygy.storage import readings as readings_store

    services.provider = FailingProvider()
    app = SyzygyApp(services)
    async with app.run_test() as pilot:
        await settle(pilot)
        await turn_the_wheel(pilot)

        stored = readings_store.get_by_id(conn, pilot.app.screen.reading.id)
        assert stored.status == ReadingStatus.INTERPRETATION_FAILED


async def test_a_second_failure_leaves_the_reading_retryable_again(services, profile, conn):
    """M11.4c: failing twice must not be a terminal state."""
    services.provider = FailingProvider()
    app = SyzygyApp(services)
    async with app.run_test() as pilot:
        await settle(pilot)
        await turn_the_wheel(pilot)
        screen = pilot.app.screen
        card = screen.reading.card_draw.card_id

        await pilot.press("r")
        await settle(pilot)

        assert screen.reading.status == ReadingStatus.INTERPRETATION_FAILED
        assert screen.reading.card_draw.card_id == card
        assert "[R] RETRY" in text_of(q(pilot, "#reading-keys"))

        services.provider = FixtureProvider()
        await pilot.press("r")
        await settle(pilot)
        assert screen.reading.status == ReadingStatus.COMPLETE
