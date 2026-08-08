"""The reading screen: the fixed alignment, and what was made of it.

Interpretation runs in an exclusive worker so that the interface keeps
animating while a model is working and a stale in-flight call is cancelled
if the user retries. Failure here is not an application error - the card
and the astrology are already committed, so the screen offers a retry
against the same stored context and never re-enters the Wheel
(DESIGN.md section 23).
"""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.timer import Timer
from textual.widgets import Footer, Static

from syzygy.domain.reading import Reading, ReadingStatus
from syzygy.sortes.deck import get_card
from syzygy.storage.reading_service import interpret_reading
from syzygy.tui.screens.base import SyzygyScreen, TitleBar
from syzygy.tui.widgets.reading_panel import ReadingPanel, ReadingView
from syzygy.tui.widgets.tarot_card import TarotCardWidget
from syzygy.tui.widgets.transit_badge import TransitBadge

_WAIT_FRAMES = ("◐", "◓", "◑", "◒")


class ReadingScreen(SyzygyScreen):
    BINDINGS = [
        ("1", "view_esoteric", "esoteric"),
        ("2", "view_conventional", "conventional"),
        ("i", "view_inputs", "inputs"),
        # Bound for both cases (M10.3a): Textual reports a shifted letter
        # as its own key ("R"), distinct from "r" - a real terminal with
        # Caps Lock on, or a Shift held slightly late, sent exactly that
        # and made retry look broken despite the binding being "correct".
        ("r,R", "retry", "retry"),
        ("escape", "back", "back"),
    ]

    _wait_timer: Timer | None = None

    def __init__(self, reading: Reading, *, interpret: bool = True) -> None:
        super().__init__()
        self.reading = reading
        #: Archive views open a stored reading read-only; only the live
        #: daily flow may start or retry interpretation.
        self._may_interpret = interpret
        self._wait_frame = 0

    def compose(self) -> ComposeResult:
        yield TitleBar(self.reading.consultation_local_date)
        with Vertical(id="reading-header"):
            yield Static("", id="reading-title", classes="lede")
            with Horizontal(id="reading-summary"):
                yield TarotCardWidget(glyphs=self.syzygy.glyphs, id="reading-card")
                with Vertical(id="reading-transits"):
                    pass
        yield ReadingPanel(glyphs=self.syzygy.glyphs, id="reading-panel")
        yield Static("", id="reading-keys", classes="keys", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        if self.reading.card_draw is not None:
            self.query_one("#reading-card", TarotCardWidget).set_card(
                get_card(self.reading.card_draw.card_id)
            )
        context = self.reading.interpretation_context
        if context is not None:
            container = self.query_one("#reading-transits", Vertical)
            for transit in context.significant_transits[:4]:
                container.mount(TransitBadge(transit, glyphs=self.syzygy.glyphs))

        self._show()
        if self._may_interpret and self.reading.status not in (
            ReadingStatus.COMPLETE,
            ReadingStatus.INTERPRETING,
        ):
            self._begin_interpretation()

    # -- rendering --------------------------------------------------------

    def _show(self, view: ReadingView | None = None) -> None:
        panel = self.query_one("#reading-panel", ReadingPanel)
        panel.show(self.reading, view or panel.view)
        result = self.reading.interpretation
        title = self.query_one("#reading-title", Static)
        if result is not None:
            title.update(result.alignment_title)
        elif self.reading.status == ReadingStatus.INTERPRETATION_FAILED:
            title.update("THE ALIGNMENT IS FIXED.")
        else:
            title.update("THE ALIGNMENT IS FIXED. INTERPRETING…")
        self._update_keys_hint()

    def _update_keys_hint(self) -> None:
        # Retry (and quit) are discoverable the same way in every state,
        # not just embedded in the failed-state panel body (M10.3c).
        keys = "[1] ESOTERIC   [2] CONVENTIONAL   [I] INPUTS"
        if self._may_interpret and self.reading.status == ReadingStatus.INTERPRETATION_FAILED:
            keys += "   [R] RETRY"
        keys += "   [Q] QUIT"
        self.query_one("#reading-keys", Static).update(keys)

    def _tick_wait(self) -> None:
        self._wait_frame = (self._wait_frame + 1) % len(_WAIT_FRAMES)
        self.query_one("#reading-title", Static).update(
            f"THE ALIGNMENT IS FIXED. INTERPRETING… {_WAIT_FRAMES[self._wait_frame]}"
        )

    # -- interpretation ---------------------------------------------------

    def _begin_interpretation(self) -> None:
        self._wait_timer = self.set_interval(0.2, self._tick_wait)
        self._interpret()

    @work(exclusive=True, group="interpret")
    async def _interpret(self) -> None:
        services = self.syzygy.services
        reading = await interpret_reading(
            services.conn, self.reading, services.clock, services.provider
        )
        self.reading = reading
        if self._wait_timer is not None:
            self._wait_timer.stop()
            self._wait_timer = None
        self._show()

    def action_retry(self) -> None:
        # A correct no-op (nothing to retry) still needs a visible response
        # - otherwise a stray "r" press is indistinguishable from a broken
        # binding (M10.3b).
        if not self._may_interpret or self.reading.status != ReadingStatus.INTERPRETATION_FAILED:
            self.app.bell()
            return
        self._begin_interpretation()

    # -- views ------------------------------------------------------------

    def action_view_esoteric(self) -> None:
        self._show(ReadingView.ESOTERIC)

    def action_view_conventional(self) -> None:
        self._show(ReadingView.CONVENTIONAL)

    def action_view_inputs(self) -> None:
        self._show(ReadingView.INPUTS)

    def action_back(self) -> None:
        if len(self.app.screen_stack) > 1:
            self.app.pop_screen()
