"""Wiring an `Animator` to a Textual application's clock.

`Animator` deliberately knows nothing about Textual: it is driven by
whoever calls `pump`. This is the one adapter that calls it, and it exists
as its own object for two reasons.

First, "no animation at all" turned out to be indistinguishable from a
silent scheduling failure - if the interval is never created, every
timeline sits at frame zero forever and nothing raises (M17.2d). A named
object with a `pumping` flag is something a test can actually assert on.

Second, `syzygy dev animate` needs the same wiring without the rest of the
application, and a second copy of it would be a second place for the
scheduling to be wrong.

The timer only exists while something is animating: `docs/animation.md`
section 35 requires idle CPU to be zero, which means no timer ticking and
finding nothing to do, not a cheap tick.
"""

from __future__ import annotations

from typing import Any

from textual.app import App
from textual.timer import Timer

from syzygy.tui.animation.animator import FRAME_INTERVAL, Animator
from syzygy.tui.animation.events import Animations
from syzygy.tui.animation.motion import MotionSettings

__all__ = ["AnimationDriver"]


class AnimationDriver:
    """The `Animations` façade plus the interval that advances it."""

    def __init__(self, app: App[Any], motion: MotionSettings) -> None:
        self._app = app
        self._timer: Timer | None = None
        #: True while the frame interval is running. Read by tests, and by
        #: anything that wants to know whether motion is actually being
        #: delivered rather than merely scheduled.
        self.pumping = False
        self.animations = Animations(
            Animator(motion, on_active=self._start, on_idle=self._stop)
        )

    @property
    def animator(self) -> Animator:
        return self.animations.animator

    def _start(self) -> None:
        if self._timer is None:
            self._timer = self._app.set_interval(
                FRAME_INTERVAL, self.animator.pump, pause=False
            )
        else:
            self._timer.resume()
        self.pumping = True

    def _stop(self) -> None:
        if self._timer is not None:
            self._timer.pause()
        self.pumping = False
