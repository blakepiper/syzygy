"""The daily home screen (DESIGN.md section 6.3).

Shows the state of the alignment before chance enters it: SELF resolved
from the saved chart, COSMOS resolved by calculating today's sky, CHANCE
still open. If today's reading already exists the primary action becomes
opening it - the Wheel is unreachable for the rest of the day, because
there is exactly one canonical reading per profile per local date and no
path here that could redraw one.
"""

from __future__ import annotations

from datetime import datetime

from textual import work
from textual.app import ComposeResult
from textual.containers import Center, Horizontal, Vertical
from textual.widgets import Button, Footer, Static

from syzygy.domain.astrology import RankedTransit, sign_for_longitude
from syzygy.domain.reading import Reading, ReadingStatus
from syzygy.storage.reading_service import rank_current_transits
from syzygy.tui.screens.base import SyzygyScreen, TitleBar
from syzygy.tui.widgets.alignment import AlignmentWidget
from syzygy.tui.widgets.glyph import Glyph, format_degrees
from syzygy.tui.widgets.transit_badge import TransitBadge

TURN_THE_WHEEL = "TURN THE WHEEL"
OPEN_TODAYS_READING = "OPEN TODAY'S READING"


class HomeScreen(SyzygyScreen):
    BINDINGS = [
        ("enter", "primary", "continue"),
        ("c", "chart", "chart"),
        ("a", "archive", "archive"),
        ("p", "profiles", "profiles"),
        ("q", "quit", "quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._reading: Reading | None = None

    def compose(self) -> ComposeResult:
        yield TitleBar(id="home-title")
        yield AlignmentWidget(id="home-alignment")
        with Vertical(id="home-body"):
            yield Static("", id="home-name", classes="lede")
            with Horizontal(id="home-anchors"):
                yield Glyph("☉", "Sun", id="anchor-sun")
                yield Glyph("☽", "Moon", id="anchor-moon")
                yield Glyph("↑", "Ascendant", id="anchor-asc")
            yield Static("", id="home-sky", classes="muted")
            with Horizontal(id="home-transits"):
                pass
            yield Static("", id="home-status", classes="muted")
        with Center():
            yield Button(TURN_THE_WHEEL, id="primary-action", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        self._render_self()
        self._refresh_reading_state()
        self._load_sky()

    def on_screen_resume(self) -> None:
        # Coming back from the wheel/reveal/reading flow: today's reading
        # may now exist, which changes the primary action.
        super().on_screen_resume()
        self._refresh_reading_state()

    # -- SELF -------------------------------------------------------------

    def _render_self(self) -> None:
        profile = self.syzygy.profile
        if profile is None:
            return
        local_now: datetime = self.syzygy.services.clock.now_utc().astimezone()
        self.query_one("#home-title", TitleBar).set_right_text(
            local_now.strftime("%d %b %Y").upper()
        )
        self.query_one("#home-name", Static).update(profile.display_name)

        natal = profile.natal_chart
        placements = {placement.body: placement for placement in natal.placements}
        glyphs = self.syzygy.glyphs
        for widget_id, body in (("#anchor-sun", "Sun"), ("#anchor-moon", "Moon")):
            placement = placements.get(body)
            anchor = self.query_one(widget_id, Glyph)
            if placement is None:
                anchor.update(f"{glyphs.body(body)} {body}")
                continue
            anchor.update(
                f"{glyphs.body(body)} {body:<6} {glyphs.sign(placement.sign)} "
                f"{placement.sign:<12}{format_degrees(placement.longitude)}"
            )
        ascendant_sign = sign_for_longitude(natal.ascendant_longitude)
        self.query_one("#anchor-asc", Glyph).update(
            f"{glyphs.body('Ascendant')} Asc    {glyphs.sign(ascendant_sign)} "
            f"{ascendant_sign:<12}{format_degrees(natal.ascendant_longitude)}"
        )
        self.query_one("#home-alignment", AlignmentWidget).self_resolved = True

    # -- COSMOS -----------------------------------------------------------

    @work(thread=True, exclusive=True, group="sky")
    def _load_sky(self) -> None:
        """Today's sky, for display only.

        The snapshot that gets *stored* on a reading is calculated at the
        moment of the draw by `syzygy.storage.reading_service`; this is a
        preview so the home screen can say something true about the day
        before the Wheel is turned.
        """
        profile = self.syzygy.profile
        if profile is None:
            return
        services = self.syzygy.services
        try:
            _, ranked = rank_current_transits(profile, services.astrology, services.clock.now_utc())
        except Exception as exc:  # DESIGN.md section 23: never continue silently
            self.app.call_from_thread(self._sky_failed, f"{type(exc).__name__}: {exc}")
            return
        self.app.call_from_thread(self._sky_resolved, ranked)

    def _sky_resolved(self, ranked: list[RankedTransit]) -> None:
        if not self.is_mounted:  # the user navigated away mid-calculation
            return
        self.query_one("#home-alignment", AlignmentWidget).cosmos_resolved = True
        self.query_one("#home-sky", Static).update("Current sky resolved.")
        container = self.query_one("#home-transits", Horizontal)
        container.remove_children()
        for transit in ranked[:3]:
            container.mount(TransitBadge(transit, glyphs=self.syzygy.glyphs))

    def _sky_failed(self, message: str) -> None:
        if not self.is_mounted:
            return
        # Do not continue to a draw if Self/Cosmos cannot be calculated.
        self.query_one("#home-sky", Static).update(f"Sky calculation failed - {message}")
        self.query_one("#primary-action", Button).disabled = True

    # -- CHANCE -----------------------------------------------------------

    def _refresh_reading_state(self) -> None:
        profile = self.syzygy.profile
        if profile is None:
            return
        self._reading = self.syzygy.todays_reading()
        button = self.query_one("#primary-action", Button)
        status = self.query_one("#home-status", Static)
        alignment = self.query_one("#home-alignment", AlignmentWidget)

        if self._reading is not None and self._reading.card_draw is not None:
            button.label = OPEN_TODAYS_READING
            alignment.chance_resolved = True
            if self._reading.status == ReadingStatus.COMPLETE:
                status.update("Today's reading is complete.")
            else:
                status.update("Today's card is drawn. Interpretation is unfinished.")
        else:
            button.label = TURN_THE_WHEEL
            alignment.chance_resolved = False
            status.update("Chance has not yet entered the alignment.")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "primary-action":
            self.action_primary()

    def action_primary(self) -> None:
        if self.syzygy.profile is None:
            return
        if self._reading is not None and self._reading.card_draw is not None:
            from syzygy.tui.screens.reading import ReadingScreen

            self.app.push_screen(ReadingScreen(self._reading))
            return
        from syzygy.tui.screens.wheel import WheelScreen

        self.app.push_screen(WheelScreen())

    # -- navigation -------------------------------------------------------

    def action_chart(self) -> None:
        self.app.push_screen("chart")

    def action_archive(self) -> None:
        self.app.push_screen("archive")

    def action_profiles(self) -> None:
        self.app.push_screen("profile_select")

    def refresh_reading(self) -> None:
        """Re-read today's reading from storage (used after a draw)."""
        self._refresh_reading_state()
