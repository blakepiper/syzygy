"""Semantic animation vocabulary consumed by screens and widgets."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from enum import StrEnum

from textual.widget import Widget
from textual.widgets import Static

from syzygy.tui.animation.animator import Animator, Handle
from syzygy.tui.animation.primitives import (
    decode,
    flash,
    glyph_morph,
    pulse,
    reveal,
    shake,
    typewriter,
)
from syzygy.tui.animation.timeline import Call, Delay, Parallel, stagger
from syzygy.tui.animation.timeline import Sequence as TimelineSequence


class SemanticEvent(StrEnum):
    ENTER = "enter"
    EXIT = "exit"
    FOCUS = "focus"
    SUCCESS = "success"
    ERROR = "error"
    PROCESSING_START = "processing-start"
    PROCESSING_STOP = "processing-stop"
    VALUE_CHANGE = "value-change"


class Animations:
    """Maps meaningful state changes to one consistent visual language."""

    def __init__(self, animator: Animator) -> None:
        self.animator = animator

    @property
    def motion(self):  # type intentionally inferred as MotionSettings
        return self.animator.motion

    def trigger(self, event: SemanticEvent | str, target: Widget) -> Handle:
        event = SemanticEvent(event)
        channel = (event.value, target.id or id(target))
        if event is SemanticEvent.ENTER:
            step = reveal(target)
        elif event is SemanticEvent.EXIT:
            step = pulse(target, 0.12)
        elif event is SemanticEvent.FOCUS:
            step = pulse(target, 0.1)
        elif event is SemanticEvent.SUCCESS:
            step = Parallel([pulse(target, 0.24), flash(target, "-anim-success", 0.1)])
        elif event is SemanticEvent.ERROR:
            effects = [flash(target, "-anim-error", 0.1)]
            if self.motion.allows_shake:
                effects.append(shake(target))
            step = Parallel(effects)
        elif event is SemanticEvent.PROCESSING_START:
            step = pulse(target, 0.7)
            return self.animator.run(step, channel=channel, loop=True)
        elif event is SemanticEvent.VALUE_CHANGE:
            step = pulse(target, 0.12)
        else:
            self.animator.cancel((SemanticEvent.PROCESSING_START.value, target.id or id(target)))
            step = pulse(target, 0.1)
        return self.animator.run(step, channel=channel)

    def transient_value(
        self, target: Widget, settle: Callable[[], None], duration: float = 0.6
    ) -> Handle:
        return self.animator.run(
            TimelineSequence([pulse(target, 0.12), Delay(duration), Call(settle)]),
            channel=(SemanticEvent.VALUE_CHANGE.value, target.id or id(target)),
        )

    def startup(self, mark: Static, logo: Widget, complete: Callable[[], None]) -> Handle:
        logo.styles.opacity = 0.0
        step = TimelineSequence(
            [
                glyph_morph(mark, ("·", "·  ✦  ·", "S · Z · G", "S Y Z Y G Y"), 0.3),
                Parallel([reveal(logo, 0.28), pulse(mark, 0.2)]),
                Call(lambda: mark.update("")),
                Call(complete),
            ]
        )
        return self.animator.run(step, channel="startup")

    def self_selected(self, target: Widget, complete: Callable[[], None]) -> Handle:
        return self.animator.run(
            TimelineSequence([pulse(target, 0.18), Call(complete)]), channel="self-selected"
        )

    def resolve_self(self, anchors: Sequence[Widget], alignment: Widget) -> Handle:
        steps = [reveal(anchor, 0.16) for anchor in anchors]
        return self.animator.run(
            TimelineSequence(
                [stagger(steps, 0.035), Call(lambda: setattr(alignment, "self_resolved", True))]
            ),
            channel="resolve-self",
        )

    def turn_wheel(self, target: Widget, complete: Callable[[], None]) -> Handle:
        """Acknowledge the action; arrival on the Wheel carries the motion."""
        self.trigger(SemanticEvent.FOCUS, target)
        return self.animator.run(
            Call(complete),
            channel="turn-wheel",
        )

    def draw_complete(self, particles: Static, complete: Callable[[], None]) -> Handle:
        frames = ("·       ·", "  ✦  ·  +  ", "✦  +  ✧  ⋆", "")
        effect = (
            glyph_morph(particles, frames, 0.42)
            if self.motion.allows_particles
            else Delay(0.08)
        )
        return self.animator.run(
            TimelineSequence([effect, Call(lambda: particles.update("")), Call(complete)]),
            channel="draw-complete",
        )

    def reveal_reading(
        self,
        card: Widget,
        headline: Static,
        headline_text: str,
        panel: Widget,
    ) -> Handle:
        return self.animator.run(
            TimelineSequence(
                [pulse(card, 0.16), typewriter(headline, headline_text), reveal(panel, 0.2)]
            ),
            channel="reading-reveal",
        )

    def ritual_reveal(
        self,
        stage_card: Callable[[], None],
        stage_transits: Callable[[], None],
        stage_done: Callable[[], None],
        complete: Callable[[], None],
    ) -> Handle:
        return self.animator.run(
            TimelineSequence(
                [
                    Delay(0.18),
                    Call(stage_card),
                    Delay(0.3),
                    Call(stage_transits),
                    Delay(0.28),
                    Call(stage_done),
                    Delay(0.45),
                    Call(complete),
                ]
            ),
            channel="ritual-reveal",
        )

    def enter_staggered(self, targets: Sequence[Widget]) -> Handle:
        return self.animator.run(
            stagger([reveal(target, 0.15) for target in targets], 0.04),
            channel="staggered-enter",
        )

    def decode_heading(self, target: Static, text: str) -> Handle:
        return self.animator.run(decode(target, text), channel=("decode", target.id))
