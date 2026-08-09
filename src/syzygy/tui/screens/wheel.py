"""Turning the Wheel (docs/old/DESIGN.md section 7).

The screen owns one `EntropyCollector` for one draw attempt, hands it to
the widget to record interaction timing into, and on release passes it to
`syzygy.storage.reading_service.draw_todays_reading` - which draws the
card and commits it to storage before anything is shown or interpreted
(docs/old/DESIGN.md section 7.4). There is no branch here that draws twice, and no
way back to this screen once a card exists for today.
"""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import Center, Vertical
from textual.widgets import Footer, Static

from syzygy.domain.reading import Reading
from syzygy.sortes.entropy import EntropyCollector
from syzygy.storage.reading_service import draw_todays_reading
from syzygy.tui.screens.base import SyzygyScreen, TitleBar
from syzygy.tui.widgets.wheel import (
    WheelDisturbance,
    WheelImpulse,
    WheelNotReady,
    WheelRelease,
    WheelWidget,
)


class WheelScreen(SyzygyScreen):
    #: The Wheel animates itself continuously and already triggers its
    #: own entry; a staggered region reveal on top of that is noise.
    SCREEN_TRANSITIONS = False

    BINDINGS = [("escape", "abandon", "step away")]

    def __init__(self) -> None:
        super().__init__()
        # One collector per draw attempt. Default `os_random` - production
        # code must never inject a fixed source here (AGENTS.md).
        self._collector = EntropyCollector()
        self._releasing = False

    def compose(self) -> ComposeResult:
        yield TitleBar("THE WHEEL")
        with Vertical(id="wheel-body"):
            with Center():
                yield Static("Give the wheel motion.", id="wheel-lede", classes="lede")
            yield WheelWidget(self._collector, glyphs=self.syzygy.glyphs, id="wheel")
            yield Static("", id="wheel-particles", classes="particles")
            with Center():
                yield Static("", id="wheel-status", classes="muted")
            with Center():
                yield Static(
                    "SPACE impulse     ← → disturb     ENTER release     Q quit",
                    id="wheel-keys",
                    classes="keys",
                )
        yield Footer()

    def on_mount(self) -> None:
        self._update_status()
        wheel = self.query_one("#wheel", WheelWidget)
        wheel.focus()
        self.syzygy.animations.trigger("enter", wheel)

    def _update_status(self, message: str | None = None) -> None:
        wheel = self.query_one("#wheel", WheelWidget)
        if message is None:
            remaining = max(0, wheel.min_impulses - wheel.impulses)
            message = (
                f"{wheel.impulses} impulses — {remaining} more before release"
                if remaining
                else f"{wheel.impulses} impulses — ready. ENTER releases."
            )
        self.query_one("#wheel-status", Static).update(message)

    # -- wheel events -----------------------------------------------------

    def on_wheel_impulse(self, _event: WheelImpulse) -> None:
        self._update_status()

    def on_wheel_disturbance(self, event: WheelDisturbance) -> None:
        direction = "widdershins" if event.direction < 0 else "deosil"
        self._update_status(f"phase disturbed {direction}")
        self.syzygy.animations.transient_value(
            self.query_one("#wheel-status", Static), self._update_status
        )

    def on_wheel_not_ready(self, event: WheelNotReady) -> None:
        self._update_status(
            f"the wheel is not turning enough — {event.required - event.impulses} more"
        )
        self.syzygy.animations.trigger("error", self.query_one("#wheel-status", Static))

    def on_wheel_release(self, _event: WheelRelease) -> None:
        if self._releasing:
            return
        self._releasing = True
        self.query_one("#wheel-lede", Static).update("THE WHEEL RELEASES.")
        self._update_status("chance enters the alignment…")
        self._draw()

    # -- the draw ---------------------------------------------------------

    @work(thread=True, exclusive=True, group="draw")
    def _draw(self) -> None:
        """Draw and commit today's card, then calculate and commit its
        context. Runs off the event loop so the Wheel keeps turning while
        the ephemeris work happens.
        """
        profile = self.syzygy.profile
        if profile is None:
            return
        services = self.syzygy.services
        try:
            reading = draw_todays_reading(
                services.conn,
                profile,
                services.clock,
                services.astrology,
                self._collector,
            )
        except Exception as exc:
            self.app.call_from_thread(self._draw_failed, f"{type(exc).__name__}: {exc}")
            return
        self.app.call_from_thread(self._drawn, reading)

    def _drawn(self, reading: Reading) -> None:
        from syzygy.tui.screens.reveal import RevealScreen

        # The fixed result is already committed. The Level-3 emphasis is
        # rendered on the destination screen so navigation never waits.
        self.app.switch_screen(RevealScreen(reading))

    def _draw_failed(self, message: str) -> None:
        if not self.is_mounted:
            return
        self._releasing = False
        self.query_one("#wheel-lede", Static).update("THE DRAW COULD NOT BE COMPLETED.")
        self._update_status(message)
        self.syzygy.animations.trigger("error", self.query_one("#wheel-status", Static))

    def action_abandon(self) -> None:
        if self._releasing:
            return  # the card may already be committed; there is no way back
        self.app.pop_screen()
