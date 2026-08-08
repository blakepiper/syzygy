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
        #: True once *this* screen has a provider call in flight. A stored
        #: `INTERPRETING` status is not the same thing (M11.4): it can be
        #: left behind by a process that died mid-call, and the difference
        #: decides whether the spinner is telling the truth.
        self._interpreting = False

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

    def _is_interrupted(self) -> bool:
        """A stored `INTERPRETING` with no call of ours in flight.

        The only way to reach this is a process that stopped between
        `begin_interpreting` and the provider's reply - quitting during a
        slow call, a crash, a closed terminal. The row is legal (the state
        machine allows `INTERPRETING -> COMPLETE/INTERPRETATION_FAILED`)
        but nothing will ever advance it on its own, and it is the
        canonical reading for that date, so without a way out it is a dead
        end for the rest of the day (M11.4).
        """
        return self.reading.status == ReadingStatus.INTERPRETING and not self._interpreting

    def _may_retry(self) -> bool:
        if not self._may_interpret or self._interpreting:
            # Nothing to retry while a retry is already running - offering
            # it would invite a second, concurrent provider call.
            return False
        return self.reading.status == ReadingStatus.INTERPRETATION_FAILED or self._is_interrupted()

    def _show(self, view: ReadingView | None = None) -> None:
        panel = self.query_one("#reading-panel", ReadingPanel)
        panel.show(
            self.reading,
            view or panel.view,
            interrupted=self._is_interrupted(),
            in_flight=self._interpreting,
        )
        result = self.reading.interpretation
        title = self.query_one("#reading-title", Static)
        if self._interpreting:
            # Checked first: a retry is in flight *before* the stored
            # status has moved off INTERPRETATION_FAILED, and the screen
            # must show the work rather than the state it is leaving.
            title.update("THE ALIGNMENT IS FIXED. INTERPRETING…")
        elif result is not None:
            title.update(result.alignment_title)
        elif self.reading.status == ReadingStatus.INTERPRETATION_FAILED:
            title.update("THE ALIGNMENT IS FIXED.")
        elif self._is_interrupted():
            # Never claim to be working when nothing is.
            title.update("THE ALIGNMENT IS FIXED. INTERPRETATION WAS INTERRUPTED.")
        else:
            title.update("THE ALIGNMENT IS FIXED. INTERPRETING…")
        self._update_keys_hint()

    def _update_keys_hint(self) -> None:
        # Retry (and quit) are discoverable the same way in every state,
        # not just embedded in the failed-state panel body (M10.3c).
        keys = "[1] ESOTERIC   [2] CONVENTIONAL   [I] INPUTS"
        if self._may_retry():
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
        self._interpreting = True
        self._wait_timer = self.set_interval(0.2, self._tick_wait)
        self._show()  # the spinner is now telling the truth
        self._interpret()

    def _end_interpretation(self) -> None:
        self._interpreting = False
        if self._wait_timer is not None:
            self._wait_timer.stop()
            self._wait_timer = None

    @work(exclusive=True, group="interpret")
    async def _interpret(self) -> None:
        services = self.syzygy.services
        try:
            reading = await interpret_reading(
                services.conn, self.reading, services.clock, services.provider
            )
        except Exception:
            # `interpret_reading` swallows provider failures itself, so
            # anything reaching here is a storage or state-machine error
            # (e.g. a stale worker from a previous screen already wrote a
            # result). Re-read rather than guessing: the row is the truth.
            self._end_interpretation()
            from syzygy.storage import readings as readings_store

            latest = readings_store.get_by_id(services.conn, self.reading.id)
            if latest is not None:
                self.reading = latest
            self._show()
            return
        self.reading = reading
        self._end_interpretation()
        self._show()

    def action_retry(self) -> None:
        # A correct no-op (nothing to retry) still needs a visible response
        # - otherwise a stray "r" press is indistinguishable from a broken
        # binding (M10.3b).
        if not self._may_retry():
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
