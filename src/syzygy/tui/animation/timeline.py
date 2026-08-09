"""Timelines: what an animation *is*, before anything renders it.

`docs/animation.md` section 29 asks for a small declarative API with
delays, sequences, parallel groups and staggers. This is it. A timeline is
a tree of `Step`s, and a `Step` answers exactly one question:

    seek(elapsed) -> put the world in the state it should be in at
                     `elapsed` seconds from my start

Nothing here knows about widgets, terminals, or wall-clock time. A `Step`
is driven entirely by whoever calls `seek`, which is what makes a
composition testable by seeking it to three points and looking at what it
wrote (`tests/tui/test_timeline.py`), with no event loop involved.

## Why `seek` and not `advance`

Frames get dropped. `docs/animation.md` section 4 is explicit that
animations must be based on elapsed time rather than frame count and that
no frame is guaranteed to render. A step that accumulated deltas would
drift; a step that is *told the time* cannot. It also makes `finish()`
trivial and exact: `seek(duration)`, the same code path a perfectly timed
final frame would have taken. That is the whole reason an interrupted
animation cannot leave stale visual state.

`seek` accepts elapsed values outside `[0, duration]`. Before its start a
step renders its initial state, after its end its final one; that is what
lets `Sequence` seek every child every frame without special cases.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from collections.abc import Sequence as SequenceABC
from typing import Final

from syzygy.tui.animation.easing import Easing, ease_out_cubic, lerp

__all__ = [
    "Call",
    "Delay",
    "Parallel",
    "Sequence",
    "Step",
    "Tween",
    "stagger",
]


class Step(ABC):
    """One node of a timeline."""

    #: Seconds this step occupies. Zero is legal (`Call`), and a step of
    #: zero duration renders its final state on the first seek.
    duration: float = 0.0

    @abstractmethod
    def seek(self, elapsed: float) -> None:
        """Render this step's state at `elapsed` seconds from its start."""

    def finish(self) -> None:
        """Jump to the final state, exactly as the last frame would."""
        self.seek(self.duration)

    def reset(self) -> None:
        """Forget one-shot state, so the step can be played again.

        Only `Call` has any; the containers forward it. Used by looping
        animations (`processing-start`), which are the only thing that
        replays a timeline.
        """
        return None


class Tween(Step):
    """Interpolate a value and hand it to `apply`.

    `apply` receives the *eased* progress, not the raw fraction, and is
    free to overshoot past 1 (see `ease_out_back`). Interpolating between
    two floats is the common case and `Tween.between` builds it; anything
    else - a colour, an offset, an index into a glyph table - is a closure
    that maps progress to whatever it needs.
    """

    def __init__(
        self,
        apply: Callable[[float], None],
        *,
        duration: float,
        easing: Easing = ease_out_cubic,
    ) -> None:
        self._apply = apply
        self.duration = max(0.0, duration)
        self._easing = easing

    @classmethod
    def between(
        cls,
        setter: Callable[[float], None],
        *,
        start: float,
        end: float,
        duration: float,
        easing: Easing = ease_out_cubic,
    ) -> Tween:
        return cls(
            lambda progress: setter(lerp(start, end, progress)),
            duration=duration,
            easing=easing,
        )

    def seek(self, elapsed: float) -> None:
        if self.duration <= 0.0:
            self._apply(self._easing(1.0))
            return
        self._apply(self._easing(elapsed / self.duration))


class Delay(Step):
    """Occupies time and does nothing. The spacing in a sequence."""

    def __init__(self, duration: float) -> None:
        self.duration = max(0.0, duration)

    def seek(self, elapsed: float) -> None:
        return None


class Call(Step):
    """Run a callback once, when the timeline reaches this point.

    Fires on the first seek at or past its start, so it fires whether the
    timeline was played frame by frame, seeked past in one jump by a
    dropped frame, or finished outright by `Animator.run` with motion
    off. That last case is the reason this exists: a screen that arranges
    the *end* of a reveal in a `Call` gets it with animations disabled
    too, at the cost of nothing.
    """

    def __init__(self, callback: Callable[[], None]) -> None:
        self._callback = callback
        self._fired = False

    @property
    def fired(self) -> bool:
        return self._fired

    def seek(self, elapsed: float) -> None:
        if self._fired or elapsed < 0.0:
            return
        self._fired = True
        self._callback()

    def reset(self) -> None:
        self._fired = False


class Sequence(Step):
    """Children one after another (`docs/animation.md` section 29)."""

    def __init__(self, steps: Iterable[Step]) -> None:
        self._steps: Final[tuple[Step, ...]] = tuple(steps)
        self.duration = sum(step.duration for step in self._steps)

    def seek(self, elapsed: float) -> None:
        offset = 0.0
        for step in self._steps:
            # Unclamped on purpose: a child whose turn has not come sees a
            # negative elapsed and renders its initial state, and one
            # already past sees more than its duration and renders its
            # final state. Clamping here would fire every `Call` in the
            # sequence on the first frame.
            step.seek(elapsed - offset)
            offset += step.duration

    def finish(self) -> None:
        """Finish each child in turn, rather than seeking to `duration`.

        `duration` is `sum(...)` while `seek` accumulates the same numbers
        one at a time, and the two do not always agree in the last bit:
        0.45 + 0.4 + 0.35 + 0.2 sums to 1.4 and accumulates to
        1.4000000000000001. Seeking to `duration` then handed the final
        child an elapsed of -1e-16, which `Call` reads as "not my turn
        yet" - so a skipped or interrupted sequence silently dropped
        whatever was arranged to happen at its end.

        That is not a rounding nicety. `Call` at the end of a timeline is
        how a screen arranges the *result* of an animation (the opening
        sequence routes from one), and `Handle.finish` is what a keypress
        and motion `off` both go through. Finishing children directly is
        exact by construction, and is what "land on the final state"
        meant all along.
        """
        for step in self._steps:
            step.finish()

    def reset(self) -> None:
        for step in self._steps:
            step.reset()


class Parallel(Step):
    """Children at once, ending when the longest of them does."""

    def __init__(self, steps: Iterable[Step]) -> None:
        self._steps: Final[tuple[Step, ...]] = tuple(steps)
        self.duration = max((step.duration for step in self._steps), default=0.0)

    def seek(self, elapsed: float) -> None:
        for step in self._steps:
            step.seek(elapsed)

    def finish(self) -> None:
        # Same reason as `Sequence.finish`: the group's duration is the
        # longest child's, and seeking a shorter child past its end is
        # fine - but a `stagger` nests sequences in here, and those have
        # to be finished exactly.
        for step in self._steps:
            step.finish()

    def reset(self) -> None:
        for step in self._steps:
            step.reset()


def stagger(steps: SequenceABC[Step], interval: float) -> Step:
    """The same animation across related objects, offset in time.

    `docs/animation.md` section 11 wants 20-60 ms between items and a
    total short enough that nobody feels obliged to watch it finish. The
    interval is the caller's; the "short enough" is the caller's too, and
    the honest way to keep it is to stagger three things rather than
    thirty.
    """
    return Parallel(
        Sequence([Delay(index * interval), step]) for index, step in enumerate(steps)
    )
