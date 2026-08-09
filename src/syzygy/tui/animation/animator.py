"""The clock that drives timelines, and the handles that interrupt them.

One `Animator` per application. It owns:

- **the running set** - every timeline currently in flight, keyed by
  channel;
- **time scaling** - `MotionSettings.time_scale` is applied here, once, so
  reduced motion and the debug slow-motion multiplier are impossible to
  forget in a primitive;
- **the pump's lifetime** - `on_active`/`on_idle` fire as the running set
  gains its first entry and loses its last, which is how
  `docs/animation.md` section 35's "must not increase CPU usage when idle"
  is actually kept: with nothing animating there is no timer at all, not a
  timer that ticks and finds nothing to do.

## Channels, and why there is no queue

`docs/animation.md` section 27 divides animations into retargetable,
replaceable, and nonessential, and section 14 requires that rapid input
*retarget* rather than queue. A channel is how both are expressed:
starting a timeline on a channel that is already busy settles the old one
first (it lands on its final state - never a stale intermediate) and
replaces it. Because the movement primitives read their starting value off
the widget at build time, replacing a half-finished move with a new one is
retargeting.

There is deliberately no way to enqueue. If two things must happen in
order, that is one timeline with a `Sequence` in it, not two animations
racing for a channel.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Hashable
from typing import Final

from syzygy.tui.animation.motion import MotionLevel, MotionSettings
from syzygy.tui.animation.timeline import Step

__all__ = ["Animator", "FRAME_INTERVAL", "Handle"]

#: 30 FPS, the rate `docs/animation.md` section 4 prefers. Only ticks
#: while something is animating.
FRAME_INTERVAL: Final = 1 / 30


class Handle:
    """A running timeline, and the three ways to interrupt it.

    `finish` and `cancel` both land the timeline on its final state, which
    is the property that makes interruption safe: whatever the animation
    was going to leave on screen, it leaves, immediately. They differ only
    in whether the completion callback runs. `drop` is for the
    nonessential (section 27) - a particle burst that should simply stop
    existing when the interface has something better to do.
    """

    def __init__(
        self,
        animator: Animator,
        step: Step,
        *,
        channel: Hashable | None,
        loop: bool,
        on_complete: Callable[[], None] | None,
    ) -> None:
        self._animator = animator
        self._step = step
        self.channel = channel
        self._loop = loop
        self._on_complete = on_complete
        self._elapsed = 0.0
        self._done = False

    @property
    def done(self) -> bool:
        return self._done

    @property
    def elapsed(self) -> float:
        return self._elapsed

    def _advance(self, delta: float) -> None:
        """One frame. Returns nothing; the animator reaps finished handles."""
        if self._done:
            return
        self._elapsed += delta
        if self._loop:
            duration = self._step.duration
            if duration > 0.0 and self._elapsed >= duration:
                self._elapsed %= duration
                self._step.reset()
            self._step.seek(self._elapsed)
            return
        if self._elapsed >= self._step.duration:
            self.finish()
            return
        self._step.seek(self._elapsed)

    def finish(self) -> None:
        """Land on the final state and run the completion callback."""
        if self._done:
            return
        self._done = True
        self._step.finish()
        self._animator._reap(self)
        if self._on_complete is not None:
            self._on_complete()

    def cancel(self) -> None:
        """Land on the final state without completing.

        The default interruption. The visual result is identical to
        letting the animation run out, so nothing is left half-faded or
        offset by a cell; only the "and then..." is dropped.
        """
        if self._done:
            return
        self._done = True
        self._step.finish()
        self._animator._reap(self)

    def drop(self) -> None:
        """Stop without landing on anything (`nonessential`, section 27).

        For effects whose final state is "gone" - particles, decorative
        overlays. Using this on anything that leaves a widget mid-fade is
        exactly the stale-state bug the other two methods avoid.
        """
        if self._done:
            return
        self._done = True
        self._animator._reap(self)


class Animator:
    """Runs timelines. One per application; screens reach it through
    `syzygy.tui.animation.events.Animations`, not directly."""

    def __init__(
        self,
        motion: MotionSettings | None = None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        on_active: Callable[[], None] | None = None,
        on_idle: Callable[[], None] | None = None,
    ) -> None:
        self.motion = motion or MotionSettings()
        self._monotonic = monotonic
        self.on_active = on_active
        self.on_idle = on_idle
        self._handles: list[Handle] = []
        self._by_channel: dict[Hashable, Handle] = {}
        self._last_tick: float | None = None

    # -- running ----------------------------------------------------------

    @property
    def active(self) -> bool:
        return bool(self._handles)

    def run(
        self,
        step: Step,
        *,
        channel: Hashable | None = None,
        loop: bool = False,
        on_complete: Callable[[], None] | None = None,
    ) -> Handle:
        """Start `step`, replacing whatever was on `channel`.

        With motion `off` this finishes the timeline synchronously and
        returns an already-done handle: the caller's next line of code
        sees the final state, and any `Call` in the timeline has already
        fired. That is the whole of "off renders the final state
        immediately" (`docs/animation.md` section 34) - there is no second
        code path for a screen to get wrong.
        """
        if channel is not None:
            existing = self._by_channel.get(channel)
            if existing is not None:
                existing.cancel()

        scale = self.motion.time_scale
        if scale <= 0.0 or self.motion.level is MotionLevel.OFF:
            handle = Handle(self, step, channel=None, loop=False, on_complete=on_complete)
            handle.finish()
            return handle

        scaled = step if scale == 1.0 else _TimeScaled(step, scale)
        handle = Handle(self, scaled, channel=channel, loop=loop, on_complete=on_complete)
        # The initial frame is rendered now rather than on the next tick,
        # so an element that enters from opacity 0 is never painted at
        # opacity 1 for one frame first (section 39: unreadable
        # intermediate frames, and the flicker they cause).
        scaled.seek(0.0)
        self._register(handle)
        return handle

    def _register(self, handle: Handle) -> None:
        was_idle = not self._handles
        self._handles.append(handle)
        if handle.channel is not None:
            self._by_channel[handle.channel] = handle
        if was_idle:
            self._last_tick = self._monotonic()
            if self.on_active is not None:
                self.on_active()

    def _reap(self, handle: Handle) -> None:
        try:
            self._handles.remove(handle)
        except ValueError:
            return
        if handle.channel is not None and self._by_channel.get(handle.channel) is handle:
            del self._by_channel[handle.channel]
        if not self._handles:
            self._last_tick = None
            if self.on_idle is not None:
                self.on_idle()

    # -- interrupting ------------------------------------------------------

    def handle_for(self, channel: Hashable) -> Handle | None:
        return self._by_channel.get(channel)

    def cancel(self, channel: Hashable) -> None:
        """Settle and remove whatever is running on `channel`. A no-op if
        nothing is - callers should not have to check first."""
        handle = self._by_channel.get(channel)
        if handle is not None:
            handle.cancel()

    def finish_all(self) -> None:
        """Land every running timeline on its final state.

        What a skip key does (`docs/animation.md` section 1.3: input must
        never wait on animation).
        """
        for handle in list(self._handles):
            handle.finish()

    def cancel_all(self) -> None:
        for handle in list(self._handles):
            handle.cancel()

    # -- the pump ----------------------------------------------------------

    def pump(self) -> None:
        """One frame, timed off the monotonic clock.

        Wired to a Textual interval by `SyzygyApp`; called directly by
        tests, which supply their own `monotonic` so a 400 ms timeline
        takes no wall-clock time to verify.
        """
        now = self._monotonic()
        previous = self._last_tick
        self._last_tick = now
        if previous is None:
            return
        self.tick(max(0.0, now - previous))

    def tick(self, delta: float) -> None:
        """Advance every running timeline by `delta` seconds."""
        for handle in list(self._handles):
            handle._advance(delta)


class _TimeScaled(Step):
    """Stretches a timeline in time without touching what it does.

    Where `MotionSettings.time_scale` is applied. Wrapping rather than
    scaling each duration in place keeps the primitives written in the
    numbers `docs/animation.md` uses - a 180 ms transition says 0.18 in the
    source whatever the user's motion level is.
    """

    def __init__(self, step: Step, scale: float) -> None:
        self._step = step
        self._scale = scale
        self.duration = step.duration * scale

    def seek(self, elapsed: float) -> None:
        self._step.seek(elapsed / self._scale)

    def finish(self) -> None:
        self._step.finish()

    def reset(self) -> None:
        self._step.reset()
