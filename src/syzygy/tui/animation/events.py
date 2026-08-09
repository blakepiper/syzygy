"""Semantic animation vocabulary consumed by screens and widgets.

## On the durations here

`docs/animation.md` section 5 puts routine navigation under 300 ms, and
that is the right number for a compositing GUI. A terminal is not one:
`FRAME_INTERVAL` is 33 ms, so a 200 ms transition is six frames and a
120 ms one is four - in practice, at the sizes and colours Syzygy uses,
short enough to be missed entirely. M17.2c raised entry to roughly
350-600 ms for exactly that reason, which reads as a *composite* Level 3
event assembled from Level 2 pieces rather than as a slow Level 2 one.

The other half of M17.2c is what the effect *is*. Opacity alone is a poor
signal on a terminal whose palette blends badly, so the entry that
matters - a screen arriving - carries a staged glyph reveal on the title
as well, which survives any terminal that can print at all.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from enum import StrEnum
from typing import Final

from textual.widget import Widget
from textual.widgets import Static

from syzygy.tui.animation.animator import Animator, Handle
from syzygy.tui.animation.primitives import (
    brighten,
    decode,
    dim,
    flash,
    glyph_morph,
    pulse,
    reveal,
    shake,
    typewriter,
)
from syzygy.tui.animation.timeline import Call, Delay, Parallel, Step, stagger
from syzygy.tui.animation.timeline import Sequence as TimelineSequence

#: One channel for the whole application, not one per screen: exactly one
#: screen is entering at any moment, so a new entry should *retarget* the
#: previous one (`animator`'s module docstring) rather than race it.
SCREEN_ENTER_CHANNEL: Final = "screen-enter"

#: How long a region takes to arrive, and the gap between successive
#: regions. Three or four regions at 70 ms apart puts the whole entry at
#: roughly half a second - long enough to read as a movement, short enough
#: that nobody feels obliged to watch it (`docs/animation.md` section 11).
ENTRY_DURATION: Final = 0.34
ENTRY_STAGGER: Final = 0.07
TITLE_DECODE_DURATION: Final = 0.42

#: Leaving is deliberately quicker than arriving, and never blocks the
#: navigation it accompanies (M17.2b).
EXIT_DURATION: Final = 0.16
EXIT_OPACITY: Final = 0.4


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
            step = reveal(target, ENTRY_DURATION)
        elif event is SemanticEvent.EXIT:
            # Dims and *stays* dimmed: the final state of leaving is being
            # gone. Whatever brings the widget back is responsible for
            # brightening it, which for a screen is `enter_screen`.
            step = dim(target, to=EXIT_OPACITY, duration=EXIT_DURATION)
        elif event is SemanticEvent.FOCUS:
            step = pulse(target, 0.18)
        elif event is SemanticEvent.SUCCESS:
            step = Parallel([pulse(target, 0.36), flash(target, "-anim-success", 0.2)])
        elif event is SemanticEvent.ERROR:
            effects = [flash(target, "-anim-error", 0.2)]
            if self.motion.allows_shake:
                effects.append(shake(target))
            step = Parallel(effects)
        elif event is SemanticEvent.PROCESSING_START:
            step = pulse(target, 0.7)
            return self.animator.run(step, channel=channel, loop=True)
        elif event is SemanticEvent.VALUE_CHANGE:
            step = pulse(target, 0.2)
        else:
            self.animator.cancel((SemanticEvent.PROCESSING_START.value, target.id or id(target)))
            step = pulse(target, 0.18)
        return self.animator.run(step, channel=channel)

    def enter_screen(
        self,
        screen: Widget,
        regions: Sequence[Widget],
        title: Static | None = None,
        title_text: str = "",
    ) -> Handle:
        """A screen arriving: its regions stagger in, its title decodes.

        `screen` itself is brightened as well, because leaving dimmed it
        and a screen that is returned to must not stay half-faded - that
        is the stale-visual-state failure `Handle.finish` exists to
        prevent, one level up.
        """
        for region in regions:
            region.styles.opacity = 0.0
        steps: list[Step] = [
            brighten(screen, EXIT_DURATION),
            stagger([reveal(region, ENTRY_DURATION) for region in regions], ENTRY_STAGGER),
        ]
        if title is not None and title_text:
            steps.append(decode(title, title_text, TITLE_DECODE_DURATION))
        return self.animator.run(Parallel(steps), channel=SCREEN_ENTER_CHANNEL)

    def transient_value(
        self, target: Widget, settle: Callable[[], None], duration: float = 0.6
    ) -> Handle:
        return self.animator.run(
            TimelineSequence([pulse(target, 0.12), Delay(duration), Call(settle)]),
            channel=(SemanticEvent.VALUE_CHANGE.value, target.id or id(target)),
        )

    def startup(
        self,
        mark: Static,
        logo: Widget,
        mascot: Widget | None,
        complete: Callable[[], None],
    ) -> Handle:
        """The opening sequence, on every launch (M17.1).

        Budgeted rather than scaled: `full` is about 1.4 s, `reduced` is a
        genuinely shorter *sequence* - two beats instead of four - which
        lands at about 0.5 s once `MotionSettings.time_scale` has been
        applied, and `off` finishes synchronously and routes with no frame
        drawn at all. Scaling the full sequence would have given `reduced`
        0.77 s of the same four beats, which is not what "shortened" means.

        Whatever the level, `complete` runs exactly once and is what
        decides where the launch lands - so a dropped frame, a keypress,
        or motion `off` all arrive at the same screen.

        The mark never spells the name. It used to resolve to
        `S Y Z Y G Y`, one row above a logo whose art is that same word -
        so the opening said "syzygy" twice, in two typefaces, at once. The
        mark's job is the gathering *before* the logo arrives; it stays
        glyphs and clears when the wordmark takes over.
        """
        logo.styles.opacity = 0.0
        if mascot is not None:
            mascot.styles.opacity = 0.0

        if self.motion.allows_large_motion:
            beats: list[Step] = [
                glyph_morph(mark, ("·", "·  ✦  ·", "·  ✦  ⋆  ✦  ·", "✦  ⋆  ✧  ⋆  ✦"), 0.45),
                Parallel([reveal(logo, 0.4), pulse(mark, 0.3)]),
                reveal(mascot, 0.35) if mascot is not None else Delay(0.35),
                Delay(0.2),
            ]
        else:
            reveals: list[Step] = [reveal(logo, 0.3)]
            if mascot is not None:
                reveals.append(reveal(mascot, 0.3))
            beats = [
                glyph_morph(mark, ("·", "✦  ⋆  ✧  ⋆  ✦"), 0.3),
                Parallel(reveals),
                Delay(0.3),
            ]

        step = TimelineSequence(
            [*beats, Call(lambda: mark.update("")), Call(complete)]
        )
        return self.animator.run(step, channel="startup")

    def self_selected(self, target: Widget, complete: Callable[[], None]) -> Handle:
        return self.animator.run(
            TimelineSequence([pulse(target, 0.18), Call(complete)]), channel="self-selected"
        )

    def resolve_self(self, anchors: Sequence[Widget], alignment: Widget) -> Handle:
        steps = [reveal(anchor, 0.3) for anchor in anchors]
        return self.animator.run(
            TimelineSequence(
                [stagger(steps, 0.06), Call(lambda: setattr(alignment, "self_resolved", True))]
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

    def reveal_consultation(
        self,
        card: Widget,
        lines_bottom_up: Sequence[Widget],
        complete: Callable[[], None],
    ) -> Handle:
        """The Oracle's reveal: the card, then six lines building upward.

        Reveal order is not narration order (M22.4b). The card is the
        wheel's payoff and the app's visual identity, so it lands first;
        the ground assembles under it the way a cast is actually made,
        bottom line to top. Both objects were committed before this ran -
        the motion reports a finished fact, it does not decide one.
        """
        for line in lines_bottom_up:
            line.styles.opacity = 0.0
        return self.animator.run(
            TimelineSequence(
                [
                    pulse(card, 0.16),
                    stagger([reveal(line, 0.22) for line in lines_bottom_up], 0.09),
                    Call(complete),
                ]
            ),
            channel="consultation-reveal",
        )

    def enter_staggered(self, targets: Sequence[Widget]) -> Handle:
        return self.animator.run(
            stagger([reveal(target, 0.3) for target in targets], 0.06),
            channel="staggered-enter",
        )

    def decode_heading(self, target: Static, text: str) -> Handle:
        return self.animator.run(decode(target, text), channel=("decode", target.id))
