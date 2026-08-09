"""`syzygy dev animate` - every animation, on demand (M17.2e).

The manual check that no headless test can make. A pilot can prove a
timeline was *started* and that it lands on the right final state; it
cannot tell you whether 340 ms of opacity ramp is visible on a real
terminal over SSH, whether a decode pass reads as decoding or as noise, or
whether the opening sequence is too long the fifth time you see it. That
is an eye's job, and this is the screen it needs.

Development-only, gated on `SYZYGY_DEV` at the command, and deliberately
not reachable from the application: it is a bench, not a feature.

It runs its own `App` rather than `SyzygyApp` because it needs none of the
collaborators - no database, no astrology engine, no provider. The pump
wiring is shared through `AnimationDriver`, so what is demonstrated here
is the same scheduling the real application uses and not a second
implementation of it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, ListView, Static

from syzygy.tui.animation.driver import AnimationDriver
from syzygy.tui.animation.events import SemanticEvent
from syzygy.tui.animation.motion import (
    MotionSettings,
    next_level,
    resolve_motion,
)
from syzygy.tui.widgets.brand import Logo, Mascot
from syzygy.tui.widgets.marked_list import MarkedListItem
from syzygy.tui.widgets.waiting import WaitingIndicator

#: Every entry is "run this and return whatever it returns" - the demo
#: never inspects the `Handle`, and typing it as one would mean the two
#: kinds of entry could not sit in the same list.
Play = Callable[[], Any]


class DemoItem(MarkedListItem):
    def __init__(self, label: str, play: Play) -> None:
        super().__init__(label)
        self.play = play


class AnimationDemoApp(App[None]):
    """A bench for the animation vocabulary, at the current motion level."""

    CSS_PATH = "../syzygy.tcss"
    TITLE = "SYZYGY · ANIMATION BENCH"

    BINDINGS = [
        ("q", "quit", "quit"),
        ("f2", "cycle_motion", "motion"),
        ("space", "replay", "replay"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.animation_driver = AnimationDriver(self, resolve_motion())
        self.animations = self.animation_driver.animations
        self._last: Play | None = None

    def compose(self) -> ComposeResult:
        yield Static("", id="demo-title", classes="title-bar")
        with Horizontal(id="demo-columns"):
            yield ListView(id="demo-list")
            with Vertical(id="demo-stage"):
                yield Static("", id="demo-mark", classes="startup-mark")
                yield Logo(id="demo-logo")
                yield Static("THE SUBJECT", id="demo-target", classes="lede")
                yield Static("", id="demo-heading", classes="section-heading")
                yield Static("", id="demo-particles", classes="particles")
                yield WaitingIndicator(
                    note="the card and the cast are committed and will not change",
                    id="demo-waiting",
                )
                yield Mascot(id="demo-mascot")
        yield Static("", id="demo-message", classes="muted", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self._render_title()
        listing = self.query_one("#demo-list", ListView)
        for label, play in self._entries():
            listing.append(DemoItem(label, play))
        listing.index = 0
        listing.focus()

    # -- the catalogue ------------------------------------------------------

    def _entries(self) -> list[tuple[str, Play]]:
        target = self.query_one("#demo-target", Static)
        heading = self.query_one("#demo-heading", Static)
        particles = self.query_one("#demo-particles", Static)
        mark = self.query_one("#demo-mark", Static)
        logo = self.query_one("#demo-logo", Logo)
        mascot = self.query_one("#demo-mascot", Mascot)
        stage = self.query_one("#demo-stage", Vertical)
        animations = self.animations

        def play_event(event: SemanticEvent) -> Play:
            return lambda: animations.trigger(event, target)

        entries: list[tuple[str, Play]] = [
            (f"event · {event.value}", play_event(event)) for event in SemanticEvent
        ]
        entries += [
            ("choreography · startup", lambda: animations.startup(mark, logo, mascot, self._done)),
            (
                "choreography · enter-screen",
                lambda: animations.enter_screen(stage, [target, heading, particles]),
            ),
            ("choreography · self-selected", lambda: animations.self_selected(target, self._done)),
            ("choreography · turn-wheel", lambda: animations.turn_wheel(target, self._done)),
            (
                "choreography · draw-complete",
                lambda: animations.draw_complete(particles, self._done),
            ),
            (
                "choreography · reveal-reading",
                lambda: animations.reveal_reading(target, heading, "THE ALIGNMENT HOLDS", stage),
            ),
            (
                "choreography · ritual-reveal",
                lambda: animations.ritual_reveal(
                    lambda: self._say("card"),
                    lambda: self._say("transits"),
                    lambda: self._say("aligned"),
                    self._done,
                ),
            ),
            (
                "choreography · enter-staggered",
                lambda: animations.enter_staggered([target, heading, particles]),
            ),
            (
                "choreography · decode-heading",
                lambda: animations.decode_heading(heading, "SELF · COSMOS · CHANCE"),
            ),
            (
                "choreography · transient-value",
                lambda: animations.transient_value(target, self._done),
            ),
            # The only entry that runs until something stops it, which is
            # the thing to look at: it has to stay legible for a minute
            # without becoming what the screen is about.
            ("choreography · awaiting", self._play_awaiting),
        ]
        return entries

    # -- driving it ---------------------------------------------------------

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if isinstance(item, DemoItem):
            self._play(item.play)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        for item in event.list_view.query(MarkedListItem):
            item.set_marked(item is event.item)

    def action_replay(self) -> None:
        if self._last is not None:
            self._play(self._last)

    def _play(self, play: Play) -> None:
        self._last = play
        self.animations.animator.finish_all()
        self._reset_stage()
        play()

    def _play_awaiting(self) -> Any:
        indicator = self.query_one("#demo-waiting", WaitingIndicator)
        indicator.display = True
        return self.animations.awaiting(indicator)

    def _reset_stage(self) -> None:
        for widget in self.query("#demo-stage > *"):
            widget.styles.opacity = 1.0
            widget.styles.offset = (0, 0)
        self.query_one("#demo-target", Static).update("THE SUBJECT")
        self.query_one("#demo-message", Static).update("")
        # `_play` finishes every running timeline first, so the sweep is
        # already stopped by the time this hides it.
        self.query_one("#demo-waiting", WaitingIndicator).display = False

    def _say(self, message: str) -> None:
        self.query_one("#demo-message", Static).update(message)

    def _done(self) -> None:
        self._say("completion callback fired")

    def action_cycle_motion(self) -> None:
        """Cycle the level *for this process only* - a bench must never
        rewrite the settings of the application it is a bench for."""
        current = self.animations.motion
        self.animations.animator.finish_all()
        self.animations.animator.motion = MotionSettings(
            level=next_level(current.level), speed=current.speed
        )
        self._render_title()

    def _render_title(self) -> None:
        motion = self.animations.motion
        self.query_one("#demo-title", Static).update(
            f"ANIMATION BENCH     motion: {motion.level.value}  speed: {motion.speed:g}"
            f"     [ENTER] play   [SPACE] replay   [F2] motion   [Q] quit"
        )
