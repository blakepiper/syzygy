"""The waiting indicator: what the screen does while a model is thinking.

The frame itself is a pure function of one phase, so most of this needs
no terminal at all. What does need one is the property that matters:
the sweep runs exactly while a provider call is in flight, and never a
moment longer.
"""

from __future__ import annotations

import asyncio

import pytest
from textual.widgets import Static

from syzygy.domain.reading import ReadingStatus
from syzygy.interpretation.providers.fixture import FixtureProvider
from syzygy.tui.animation.events import _awaiting_channel
from syzygy.tui.animation.motion import MotionLevel, MotionSettings
from syzygy.tui.app import SyzygyApp
from syzygy.tui.screens.consultation_result import ConsultationResultScreen
from syzygy.tui.widgets.waiting import (
    ELAPSED_AFTER,
    FIELD_CELLS,
    MIN_FIELD_CELLS,
    STILL_PHASE,
    WaitingIndicator,
    waiting_frame,
)

from .test_oracle import complete_oracle
from .test_ritual_flow import FailingProvider, q, settle, text_of, turn_the_wheel


def _core_index(phase: float, cells: int = FIELD_CELLS) -> int:
    """Where the bright core sits, in cells."""
    field = waiting_frame(phase, label="INTERPRETING", cells=cells).plain.splitlines()[0]
    return field.index("✧") // 2


# -- the frame ------------------------------------------------------------


def test_the_core_sweeps_there_and_back_over_one_phase():
    assert _core_index(0.0) == 0
    assert _core_index(0.25) == FIELD_CELLS // 2
    assert _core_index(0.5) == FIELD_CELLS - 1
    assert _core_index(0.75) == FIELD_CELLS // 2
    # A loop that ends where it began has no seam when it repeats.
    assert _core_index(1.0) == _core_index(0.0)


def test_the_core_is_haloed_rather_than_alone():
    """Glyph cycling, not a single moving character: the cells around the
    core carry the intermediate glyphs, which is what makes the sweep read
    as motion on a terminal that cannot blend colours."""
    field = waiting_frame(0.25, label="INTERPRETING").plain.splitlines()[0]

    assert field.count("✧") == 1
    assert field.count("⋆") == 2
    assert field.count("✦") == 2
    assert "·" in field


def test_the_dot_sequence_cycles_within_one_sweep():
    counts = [
        waiting_frame(phase, label="INTERPRETING").plain.splitlines()[1].count("·")
        for phase in (0.0, 0.3, 0.55, 0.8)
    ]

    assert counts == [0, 1, 2, 3]


def test_the_label_and_note_are_both_carried():
    frame = waiting_frame(0.0, label="INTERPRETING", note="the card is fixed").plain

    assert "INTERPRETING" in frame
    assert "the card is fixed" in frame.splitlines()[2]


def test_elapsed_seconds_appear_only_once_the_wait_is_long_enough():
    """A counter under a few seconds is noise; past that it is the answer
    to "is this still alive?"."""
    early = waiting_frame(0.0, label="INTERPRETING", elapsed=ELAPSED_AFTER - 0.1).plain
    late = waiting_frame(0.0, label="INTERPRETING", elapsed=42.7).plain

    assert "s" not in early.splitlines()[1].replace("INTERPRETING", "")
    assert "42s" in late.splitlines()[1]


def test_no_frame_claims_a_proportion():
    """There is no fraction to report, so nothing may imply one."""
    for step in range(21):
        frame = waiting_frame(step / 20, label="INTERPRETING", elapsed=99.0).plain
        assert "%" not in frame
        assert "█" not in frame


def test_the_field_shrinks_to_fit_a_narrow_column():
    indicator = WaitingIndicator()
    assert indicator.field_cells() == FIELD_CELLS  # unmeasured: full width

    class _Sized(WaitingIndicator):
        def __init__(self, width: int) -> None:
            super().__init__()
            self._width = width

        @property
        def size(self):  # type: ignore[override]
            from textual.geometry import Size

            return Size(self._width, 3)

    assert _Sized(24).field_cells() == 11
    assert _Sized(8).field_cells() == MIN_FIELD_CELLS
    assert _Sized(400).field_cells() == FIELD_CELLS
    # Odd, always: a still frame needs a true centre.
    assert all(_Sized(width).field_cells() % 2 for width in range(10, 60))


def test_the_indicator_reports_elapsed_from_its_own_clock():
    ticks = iter([100.0, 137.5])
    indicator = WaitingIndicator(monotonic=lambda: next(ticks))

    assert indicator.elapsed is None
    indicator.begin()
    assert indicator.elapsed == pytest.approx(37.5)


# -- driven by the animator ----------------------------------------------


def test_reduced_motion_does_not_make_the_loop_faster():
    """`reduced` shortens transitions, which is calmer. Doing the same to
    a loop just agitates it, so only the debug speed reaches this one."""
    from syzygy.tui.animation.animator import Animator
    from syzygy.tui.animation.events import AWAITING_CYCLE, Animations

    def cycle(level: MotionLevel, speed: float = 1.0) -> float:
        animator = Animator(MotionSettings(level=level, speed=speed))
        handle = Animations(animator).awaiting(WaitingIndicator())
        return handle._step.duration

    assert cycle(MotionLevel.FULL) == pytest.approx(AWAITING_CYCLE)
    assert cycle(MotionLevel.REDUCED) == pytest.approx(AWAITING_CYCLE)
    # The slow-motion debug multiplier still applies, as it does everywhere.
    assert cycle(MotionLevel.FULL, speed=0.5) == pytest.approx(AWAITING_CYCLE * 2)


async def test_the_oracle_sweeps_while_the_model_works_and_stops_after(
    services, profile
) -> None:
    release = asyncio.Event()

    class SlowProvider:
        provider_id = "slow"
        model_id = "slow-v1"

        async def interpret(self, context):
            await release.wait()
            return await FixtureProvider().interpret(context)

    services.provider = FailingProvider()
    app = SyzygyApp(services)
    async with app.run_test() as pilot:
        await settle(pilot)
        await complete_oracle(pilot, "What is taking so long?")
        screen = pilot.app.screen
        assert isinstance(screen, ConsultationResultScreen)

        indicator = q(pilot, "#consultation-waiting", WaitingIndicator)
        assert not indicator.display  # a failure is not a wait

        services.provider = SlowProvider()
        await pilot.press("r")
        await pilot.pause()

        assert indicator.display
        assert pilot.app.animations.animator.handle_for(_awaiting_channel(indicator))
        assert "INTERPRETING" in text_of(indicator)
        # The one thing it must never imply: that the chance is still open.
        assert "committed and will not change" in text_of(indicator)

        release.set()
        await settle(pilot)

        assert not indicator.display
        assert pilot.app.animations.animator.handle_for(_awaiting_channel(indicator)) is None
        assert "RESPONSE" in text_of(q(pilot, "#consultation-body", Static))


async def test_the_daily_reading_sweeps_while_the_model_works(services, profile) -> None:
    release = asyncio.Event()

    class SlowProvider:
        provider_id = "slow"
        model_id = "slow-v1"

        async def interpret(self, context):
            await release.wait()
            return await FixtureProvider().interpret(context)

    services.provider = FailingProvider()
    app = SyzygyApp(services)
    async with app.run_test() as pilot:
        await settle(pilot)
        await turn_the_wheel(pilot)
        screen = pilot.app.screen
        assert screen.reading.status == ReadingStatus.INTERPRETATION_FAILED

        indicator = q(pilot, "#reading-waiting", WaitingIndicator)
        assert not indicator.display

        services.provider = SlowProvider()
        await pilot.press("r")
        await pilot.pause()

        assert indicator.display
        assert pilot.app.animations.animator.handle_for(_awaiting_channel(indicator))

        release.set()
        await settle(pilot)

        assert not indicator.display
        assert pilot.app.animations.animator.handle_for(_awaiting_channel(indicator)) is None


async def test_a_stranded_reading_never_sweeps(services, profile, conn) -> None:
    """A row left in INTERPRETING by a dead process has nothing working on
    it, so nothing may animate as though something were (M11.4)."""
    from syzygy.tui.screens.reading import ReadingScreen

    from .test_retry import _drawn_reading, _strand_in_interpreting

    stranded = _strand_in_interpreting(conn, await _drawn_reading(conn, profile))

    app = SyzygyApp(services)
    async with app.run_test() as pilot:
        await settle(pilot)
        pilot.app.set_profile(profile)
        pilot.app.push_screen(ReadingScreen(stranded))
        await settle(pilot)

        indicator = q(pilot, "#reading-waiting", WaitingIndicator)
        assert not indicator.display
        assert pilot.app.animations.animator.handle_for(_awaiting_channel(indicator)) is None


async def test_leaving_mid_interpretation_stops_the_sweep(services, profile) -> None:
    """A loop that outlives its screen is a timer running forever."""
    release = asyncio.Event()

    class SlowProvider:
        provider_id = "slow"
        model_id = "slow-v1"

        async def interpret(self, context):
            await release.wait()
            return await FixtureProvider().interpret(context)

    services.provider = FailingProvider()
    app = SyzygyApp(services)
    async with app.run_test() as pilot:
        await settle(pilot)
        await turn_the_wheel(pilot)

        services.provider = SlowProvider()
        await pilot.press("r")
        await pilot.pause()
        indicator = q(pilot, "#reading-waiting", WaitingIndicator)
        assert pilot.app.animations.animator.handle_for(_awaiting_channel(indicator))

        await pilot.app.pop_screen()
        await pilot.pause()

        assert pilot.app.animations.animator.handle_for(_awaiting_channel(indicator)) is None

        release.set()
        await settle(pilot)


async def test_motion_off_gets_one_still_frame_and_no_loop(services, profile) -> None:
    release = asyncio.Event()

    class SlowProvider:
        provider_id = "slow"
        model_id = "slow-v1"

        async def interpret(self, context):
            await release.wait()
            return await FixtureProvider().interpret(context)

    services.provider = FailingProvider()
    app = SyzygyApp(services)
    async with app.run_test() as pilot:
        await settle(pilot)
        await turn_the_wheel(pilot)
        pilot.app.animations.animator.motion = MotionSettings(level=MotionLevel.OFF)

        services.provider = SlowProvider()
        await pilot.press("r")
        await pilot.pause()

        indicator = q(pilot, "#reading-waiting", WaitingIndicator)
        assert indicator.display
        assert pilot.app.animations.animator.handle_for(_awaiting_channel(indicator)) is None
        # The final state of a sweep that never runs: the core at rest, in
        # the middle of its travel.
        assert "✧" in text_of(indicator)
        assert text_of(indicator).splitlines()[0] == (
            waiting_frame(STILL_PHASE, label="INTERPRETING", cells=indicator.field_cells())
            .plain.splitlines()[0]
        )

        release.set()
        await settle(pilot)
