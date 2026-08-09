"""What the interface does while a model is thinking.

A provider call is the one part of the ritual with no bound on how long
it takes: a hosted model answers in seconds, a local one may spend a
minute loading weights before it emits a token. `docs/animation.md`
section 16 asks for more than a generic spinner in exactly that situation
- a moving highlight, glyph cycling, a dot sequence - and for the result
to stay quiet enough not to dominate the screen it sits on.

So this is three rows and no widget chrome:

    ·  ·  ✦  ⋆  ✧  ⋆  ✦  ·  ·        a core sweeping through a dim field
    INTERPRETING ···                  the dot sequence
    the card and the cast are fixed   the reassurance, and elapsed time

The glyph vocabulary is the application's own (`·  ✦  ⋆  ✧`, the same
motes the opening sequence and the draw use), and the sweep is cosine, so
it slows at the turns instead of snapping back - a linear bounce reads as
a machine, and this is the screen where the user is waiting on one.

Two things this must never do. It must not claim the *chance* is still
being decided: the card and the cast were committed before any provider
was called, and the note says so. And it must not pretend to be progress
- there is no fraction to report, so nothing here fills, counts down, or
implies a proportion. The elapsed seconds are a fact, not an estimate.

The widget is passive: `set_phase` renders one frame and nothing here
owns a timer. `syzygy.tui.animation.events.Animations.awaiting` drives it
off the one application animator, which is what makes it obey the motion
level, stop when the screen does, and cost no timer at all when idle.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from typing import Final

from rich.style import Style
from rich.text import Text
from textual.widgets import Static

from syzygy.tui import palette

__all__ = [
    "ELAPSED_AFTER",
    "FIELD_CELLS",
    "MIN_FIELD_CELLS",
    "STILL_PHASE",
    "WaitingIndicator",
    "waiting_frame",
]

#: Cells in the sweep at full width, and the floor it shrinks to on a
#: `-compact` terminal. Odd, so the still frame has a true centre.
FIELD_CELLS: Final = 21
MIN_FIELD_CELLS: Final = 9

#: The phase motion `off` renders: the core at the centre of its travel.
#: A still frame of a sweep should look like the middle of one, not like
#: an animation caught at the left edge.
STILL_PHASE: Final = 0.25

#: Seconds before the elapsed counter appears. Under this, a number is
#: noise; past it, "is this thing still alive?" is a real question and a
#: rising count is the cheapest possible answer.
ELAPSED_AFTER: Final = 5.0

#: Glyphs by distance from the moving core, then the resting field.
_CORE_GLYPHS: Final = ("✧", "⋆", "✦")
_FIELD_GLYPH: Final = "·"

_CORE = Style(color=palette.ACCENT, bold=True)
_NEAR = Style(color=palette.BONE)
_FAR = Style(color=palette.MUTED)
_FIELD = Style(color=palette.DIM)
_LABEL = Style(color=palette.BONE, bold=True)
_NOTE = Style(color=palette.MUTED)


def waiting_frame(
    phase: float,
    *,
    label: str,
    note: str = "",
    cells: int = FIELD_CELLS,
    elapsed: float | None = None,
) -> Text:
    """One frame of the indicator, as a pure function of `phase`.

    `phase` runs 0 → 1 over one full there-and-back sweep. Everything the
    frame shows is derived from it, so a test can look at any moment of
    the animation without a terminal, a clock, or an event loop.
    """
    cells = max(3, cells)
    # There and back over one cycle, slowest at the two turns.
    travel = (cells - 1) * (1.0 - math.cos(2.0 * math.pi * phase)) / 2.0

    frame = Text()
    for index in range(cells):
        if index:
            frame.append(" ")
        distance = abs(index - travel)
        if distance < 0.5:
            frame.append(_CORE_GLYPHS[0], style=_CORE)
        elif distance < 1.5:
            frame.append(_CORE_GLYPHS[1], style=_NEAR)
        elif distance < 2.5:
            frame.append(_CORE_GLYPHS[2], style=_FAR)
        else:
            frame.append(_FIELD_GLYPH, style=_FIELD)

    # Four dot states per sweep - about half a second each at the cycle
    # `Animations.awaiting` uses, which reads as deliberate rather than
    # frantic.
    dots = _FIELD_GLYPH * (int(phase * 4.0) % 4)
    frame.append("\n")
    frame.append(label, style=_LABEL)
    if dots:
        frame.append(f" {dots}", style=_NOTE)
    if elapsed is not None and elapsed >= ELAPSED_AFTER:
        frame.append(f"   {int(elapsed)}s", style=_NOTE)
    if note:
        frame.append("\n")
        frame.append(note, style=_NOTE)
    return frame


class WaitingIndicator(Static):
    """The indicator as a widget: one frame per `set_phase`, no timer."""

    DEFAULT_CSS = """
    WaitingIndicator {
        height: auto;
        width: 1fr;
        padding: 1 0;
        text-align: center;
    }
    """

    def __init__(
        self,
        *,
        label: str = "INTERPRETING",
        note: str = "",
        monotonic: Callable[[], float] = time.monotonic,
        id: str | None = None,
    ) -> None:
        super().__init__("", id=id)
        self.label = label
        self.note = note
        self._monotonic = monotonic
        self._phase = 0.0
        self._started: float | None = None
        # Hidden until something is actually being waited for. A screen
        # that never calls `begin` shows nothing and reserves no rows.
        self.display = False

    @property
    def elapsed(self) -> float | None:
        """Seconds since `begin`, or `None` if it has not been called."""
        if self._started is None:
            return None
        return max(0.0, self._monotonic() - self._started)

    def begin(self) -> None:
        """Start a wait: reset the clock and render the first frame."""
        self._started = self._monotonic()
        self.set_phase(0.0)

    def set_phase(self, phase: float) -> None:
        """Render one frame. Harmless before mounting and after removal.

        The animator holds a reference, not a place in the widget tree, so
        the last frame of a cancelled loop can arrive after the screen it
        belonged to has gone. Rendering into nothing is not an error worth
        raising - or worth computing.
        """
        self._phase = phase
        if self.is_mounted:
            self.update(self.frame())

    def set_still(self) -> None:
        """The single frame motion `off` gets (`docs/animation.md` 34)."""
        self.set_phase(STILL_PHASE)

    def frame(self) -> Text:
        return waiting_frame(
            self._phase,
            label=self.label,
            note=self.note,
            cells=self.field_cells(),
            elapsed=self.elapsed,
        )

    def field_cells(self) -> int:
        """How many cells fit, in the tier the screen is actually in.

        Measured rather than classed: this widget is a fixed-width figure
        inside a column whose width the layout tier only partly decides,
        and a sweep wider than its column wraps into two rows of rubble.
        """
        width = self.size.width
        if width <= 0:
            return FIELD_CELLS
        # Two columns per cell: the glyph and the space after it.
        available = (width - 2) // 2
        cells = max(MIN_FIELD_CELLS, min(FIELD_CELLS, available))
        return cells if cells % 2 else cells - 1
