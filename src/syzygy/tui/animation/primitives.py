"""Reusable animation primitives built from declarative timeline steps."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from textual.widget import Widget
from textual.widgets import Static

from syzygy.tui.animation.easing import ease_in_cubic, ease_in_out_quad, ease_out_cubic
from syzygy.tui.animation.timeline import Call, Parallel, Step, Tween
from syzygy.tui.animation.timeline import Sequence as TimelineSequence


def reveal(target: Widget, duration: float = 0.2) -> Step:
    return Tween.between(
        lambda value: setattr(target.styles, "opacity", value),
        start=0.0,
        end=1.0,
        duration=duration,
        easing=ease_out_cubic,
    )


def dim(target: Widget, *, to: float = 0.45, duration: float = 0.12) -> Step:
    return Tween.between(
        lambda value: setattr(target.styles, "opacity", value),
        start=float(target.styles.opacity),
        end=to,
        duration=duration,
        easing=ease_in_cubic,
    )


def brighten(target: Widget, duration: float = 0.18) -> Step:
    return Tween.between(
        lambda value: setattr(target.styles, "opacity", value),
        start=float(target.styles.opacity),
        end=1.0,
        duration=duration,
        easing=ease_out_cubic,
    )


def pulse(target: Widget, duration: float = 0.2) -> Step:
    half = duration / 2
    return TimelineSequence([dim(target, to=0.62, duration=half), brighten(target, half)])


def flash(target: Widget, class_name: str = "-anim-flash", duration: float = 0.1) -> Step:
    def add() -> None:
        target.add_class(class_name)

    def remove() -> None:
        target.remove_class(class_name)

    return TimelineSequence(
        [
            Call(add),
            Tween(lambda _: None, duration=duration),
            Call(remove),
        ]
    )


def shake(target: Widget, duration: float = 0.14) -> Step:
    def offset(progress: float) -> None:
        positions = (0, 1, -1, 1, 0)
        index = min(len(positions) - 1, int(progress * len(positions)))
        target.styles.offset = (positions[index], 0)

    return TimelineSequence(
        [
            Tween(offset, duration=duration, easing=ease_in_out_quad),
            Call(lambda: setattr(target.styles, "offset", (0, 0))),
        ]
    )


def glyph_morph(target: Static, frames: Sequence[str], duration: float = 0.25) -> Step:
    frames = tuple(frames) or ("",)

    def apply(progress: float) -> None:
        target.update(frames[min(len(frames) - 1, int(progress * len(frames)))])

    return Tween(apply, duration=duration, easing=ease_out_cubic)


def typewriter(target: Static, text: str, duration: float = 0.18) -> Step:
    """Reveal short text only; callers must never pass body copy."""
    return Tween(
        lambda progress: target.update(text[: round(len(text) * progress)]),
        duration=duration,
        easing=ease_out_cubic,
    )


def decode(target: Static, text: str, duration: float = 0.2) -> Step:
    noise = "·✦+×"

    def apply(progress: float) -> None:
        fixed = round(len(text) * progress)
        tail = "".join(
            noise[index % len(noise)] if char != " " else " "
            for index, char in enumerate(text[fixed:])
        )
        target.update(text[:fixed] + tail)

    return Tween(apply, duration=duration, easing=ease_out_cubic)


def with_final_state(step: Step, finalizer: Callable[[], None]) -> Step:
    return TimelineSequence([step, Call(finalizer)])


def reveal_and_brighten(target: Widget, duration: float = 0.22) -> Step:
    return Parallel([reveal(target, duration), brighten(target, duration)])
