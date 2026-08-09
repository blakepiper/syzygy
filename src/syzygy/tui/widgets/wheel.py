"""The Wheel: the interaction that turns chaos into one fixed card.

This widget is presentation and entropy *collection* only. It does not
know how many cards exist, does not sample anything, and cannot pick a
card - it records interaction events into an injected
`EntropyCollector` and posts messages upward (ARCHITECTURE_HANDOFF.md
section 31, DESIGN.md section 7.1). The screen above it hands the
collector to `syzygy.sortes.draw.draw_card` on release. Keeping selection
out of here is what makes the draw testable without a terminal, and what
guarantees the Wheel can never become a themed "Randomize" button.

Rendering uses Textual's Line API (`render_line` -> `Strip`) rather than a
Rich renderable, because the rim is a per-cell polar-coordinate plot that
changes every frame; `Widget.styles.animate` is for tweening CSS
properties (the card reveal), not for frame-by-frame glyph motion.
"""

from __future__ import annotations

import math
import time

from rich.segment import Segment
from rich.style import Style
from textual import events
from textual.message import Message
from textual.reactive import reactive
from textual.strip import Strip
from textual.timer import Timer
from textual.widget import Widget

from syzygy.sortes.entropy import EntropyCollector
from syzygy.tui import palette
from syzygy.tui.widgets.glyph import GlyphSet, default_glyphs

#: Radians/second the rim keeps turning at with no input at all - the
#: Wheel is never fully still until it is released.
IDLE_SPEED = 0.35

#: Radians/second added by one impulse, and the per-second decay applied
#: to whatever the user has built up beyond `IDLE_SPEED`.
IMPULSE_KICK = 1.6
MOMENTUM_DECAY = 0.55

#: Momentum at which the rim is considered fully lit, for `energy`.
FULL_ENERGY = 6.0

#: Impulses required before `ENTER` will release the draw. Ritual pacing,
#: not a security property - the digest is seeded with OS randomness
#: whether the user presses anything at all (`syzygy.sortes.entropy`).
MIN_IMPULSES = 3

FRAME_INTERVAL = 1 / 24

_RIM_DIM = Style(color=palette.DIM)
_RIM_LIT = Style(color=palette.ACCENT)
_RIM_HOT = Style(color=palette.EMBER, bold=True)
#: The sign names under the rim glyphs (M12.4). Dimmer than the glyph
#: itself so the symbol stays the thing the eye lands on.
_RIM_LABEL = Style(color=palette.MUTED)
_RIM_LABEL_HOT = Style(color=palette.OXIDE, bold=True)
_HUB = Style(color=palette.LUNAR)
_HUB_RELEASED = Style(color=palette.EMBER, bold=True)
_POINTER = Style(color=palette.BONE, bold=True)


class WheelImpulse(Message):
    """The user pushed the Wheel (SPACE, or any unbound key)."""

    def __init__(self, impulses: int) -> None:
        super().__init__()
        self.impulses = impulses


class WheelDisturbance(Message):
    """The user perturbed the Wheel's direction/phase (LEFT/RIGHT)."""

    def __init__(self, direction: int) -> None:
        super().__init__()
        self.direction = direction


class WheelRelease(Message):
    """The user released the Wheel. The draw happens above this widget."""


class WheelNotReady(Message):
    """`ENTER` before the Wheel has been turned enough to release."""

    def __init__(self, impulses: int, required: int) -> None:
        super().__init__()
        self.impulses = impulses
        self.required = required


class WheelWidget(Widget, can_focus=True):
    """A turning rim of zodiacal glyphs, driven by keyboard impulses."""

    DEFAULT_CSS = """
    WheelWidget {
        width: 1fr;
        height: 1fr;
        min-height: 9;
    }
    """

    phase: reactive[float] = reactive(0.0)
    momentum: reactive[float] = reactive(IDLE_SPEED)
    impulses: reactive[int] = reactive(0)
    released: reactive[bool] = reactive(False)

    def __init__(
        self,
        collector: EntropyCollector,
        *,
        glyphs: GlyphSet | None = None,
        min_impulses: int = MIN_IMPULSES,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._collector = collector
        self._glyphs = glyphs or default_glyphs()
        self.min_impulses = min_impulses
        self._direction = 1
        self._last_tick_ns = time.monotonic_ns()
        self._frame_timer: Timer | None = None

    @property
    def is_ready(self) -> bool:
        """Whether `ENTER` will release the draw."""
        return self.impulses >= self.min_impulses

    @property
    def energy(self) -> float:
        """Turned-ness in `[0, 1]`, for readiness indicators."""
        return min(1.0, self.momentum / FULL_ENERGY)

    def on_mount(self) -> None:
        self._last_tick_ns = time.monotonic_ns()
        animations = getattr(self.app, "animations", None)
        if animations is None or animations.motion.allows_continuous:
            self._frame_timer = self.set_interval(FRAME_INTERVAL, self._tick)
        self.focus()

    def _tick(self) -> None:
        now_ns = time.monotonic_ns()
        elapsed = (now_ns - self._last_tick_ns) / 1e9
        self._last_tick_ns = now_ns

        if self.released:
            # Coast to a halt: the alignment is fixed, the motion is not.
            self.momentum = max(0.0, self.momentum - 4.0 * elapsed)
            if self.momentum <= 0.0 and self._frame_timer is not None:
                self._frame_timer.pause()
        else:
            excess = max(0.0, self.momentum - IDLE_SPEED)
            self.momentum = IDLE_SPEED + excess * (MOMENTUM_DECAY**elapsed)
        self.phase += self._direction * self.momentum * elapsed
        self.refresh()

    # -- interaction -----------------------------------------------------
    #
    # Every branch below does the same two things in the same order:
    # record the event's timing into the entropy collector, then tell the
    # screen what happened. Nothing here inspects the deck.

    def impulse(self) -> None:
        self._collector.record("impulse")
        self.impulses += 1
        self.momentum += IMPULSE_KICK
        self.post_message(WheelImpulse(self.impulses))

    def disturb(self, direction: int) -> None:
        self._collector.record("disturbance")
        self._direction = direction
        self.phase += direction * 0.4
        self.post_message(WheelDisturbance(direction))

    def release(self) -> None:
        if self.released:
            return
        self._collector.record("release")
        if not self.is_ready:
            self.post_message(WheelNotReady(self.impulses, self.min_impulses))
            return
        self.released = True
        self.post_message(WheelRelease())

    def on_key(self, event: events.Key) -> None:
        if self.released:
            return
        if event.key == "space":
            event.stop()
            self.impulse()
        elif event.key == "left":
            event.stop()
            self.disturb(-1)
        elif event.key == "right":
            event.stop()
            self.disturb(1)
        elif event.key == "enter":
            event.stop()
            self.release()
        elif event.key == "q":
            # Quit (`SyzygyApp.BINDINGS`, M10.2) must keep working here
            # too - left unstopped so it bubbles to the app's binding
            # instead of being consumed as entropy. The pool is always
            # OS-random-primary (DESIGN.md section 7.2), so losing one
            # key's contribution changes nothing about unbiased selection.
            return
        elif event.is_printable:
            # DESIGN.md section 7.1: other key presses may contribute
            # entropy. Named keys (escape, tab, ...) are left alone so the
            # screen's own bindings keep working.
            event.stop()
            self.impulse()

    # -- rendering -------------------------------------------------------

    def render_line(self, y: int) -> Strip:
        width, height = self.size.width, self.size.height
        if width <= 0 or height <= 0:
            return Strip.blank(width)

        cells: list[tuple[str, Style]] = [(" ", Style())] * width
        center_x = (width - 1) / 2
        center_y = (height - 1) / 2
        # Terminal cells are about twice as tall as they are wide, so the
        # horizontal axis is plotted at twice the radius to keep the rim
        # round rather than an ellipse.
        radius = max(2.0, min(center_y - 1, (center_x - 2) / 2))

        def place(x: int, char: str, style: Style) -> None:
            if 0 <= x < width:
                cells[x] = (char, style)

        def place_text(center: int, text: str, style: Style) -> None:
            """Write `text` centred on column `center`."""
            start = center - (len(text) - 1) // 2
            for offset, char in enumerate(text):
                place(start + offset, char, style)

        # The rim itself: every cell within half a row of the circle.
        for x in range(width):
            dx = (x - center_x) / 2
            dy = y - center_y
            distance = math.hypot(dx, dy)
            if abs(distance - radius) <= 0.5:
                place(x, "·", _RIM_DIM)

        # The turning glyphs, evenly spaced around the rim.
        #
        # A terminal cannot scale a glyph, so a sign is made *larger*
        # (M12.4) by giving it more cells: a bracketed cartouche instead of
        # a lone character, and its three-letter name on the row below when
        # the rim is big enough. Both are gated on the arc actually
        # available between neighbours - at small sizes they would collide,
        # and a single character is better than an illegible pile.
        rim = self._glyphs.rim
        labels = self._glyphs.rim_labels
        # Horizontal arc between adjacent signs. The horizontal axis is
        # plotted at twice the radius, so the widest gap is that stretch
        # times the angular step.
        arc_cells = 2 * radius * (2 * math.pi / len(rim))
        cartouche = arc_cells >= 6
        labelled = cartouche and arc_cells >= 9 and radius >= 6

        lit = _RIM_HOT if self.energy > 0.55 else _RIM_LIT
        for index, glyph in enumerate(rim):
            angle = self.phase + index * (2 * math.pi / len(rim))
            glyph_y = round(center_y + radius * math.sin(angle))
            glyph_x = round(center_x + 2 * radius * math.cos(angle))
            if glyph_y == y:
                place_text(glyph_x, f"({glyph})" if cartouche else glyph, lit)
            elif labelled and glyph_y + 1 == y and index < len(labels):
                # The name sits inside the rim, below its glyph.
                label_style = _RIM_LABEL_HOT if self.energy > 0.55 else _RIM_LABEL
                place_text(glyph_x, labels[index], label_style)

        # A fixed pointer at twelve o'clock: the rim moves, this does not.
        if y == round(center_y - radius) - 1 and y >= 0:
            place(round(center_x), "▼", _POINTER)

        # The hub. Three points converging is the app's whole thesis
        # (DESIGN.md section 35), so the centre is a mark, not a hole.
        if y == round(center_y):
            hub_style = _HUB_RELEASED if self.released else _HUB
            place(round(center_x), "◉" if self.released else "◇", hub_style)

        segments: list[Segment] = []
        run_text = cells[0][0]
        run_style = cells[0][1]
        for char, style in cells[1:]:
            if style == run_style:
                run_text += char
            else:
                segments.append(Segment(run_text, run_style))
                run_text, run_style = char, style
        segments.append(Segment(run_text, run_style))
        return Strip(segments, width)
