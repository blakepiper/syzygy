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

from syzygy.dev import DEV_MODE_ENV_VAR, dev_mode_enabled, discard_todays_reading
from syzygy.domain.astrology import RankedTransit, sign_for_longitude
from syzygy.domain.reading import Reading, ReadingStatus
from syzygy.storage.reading_service import rank_current_transits
from syzygy.tui.screens.base import SyzygyScreen, TitleBar
from syzygy.tui.screens.model_setup import ProviderStatus, load_status
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
        ("m", "model", "model"),
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
            yield Static("", id="home-model-status", classes="muted", markup=False)
            yield Static("", id="home-dev", classes="error", markup=False)
        with Center():
            yield Button(TURN_THE_WHEEL, id="primary-action", variant="primary")
        with Vertical(id="home-reroll-confirm", classes="hidden"):
            yield Static("", id="reroll-body", classes="error", markup=False)
            with Horizontal(classes="button-row"):
                yield Button("DISCARD & REDRAW", id="reroll-confirm", variant="error")
                yield Button("CANCEL", id="reroll-cancel")
        yield Footer()

    def on_mount(self) -> None:
        self._render_self()
        self._refresh_reading_state()
        self._load_sky()
        self._load_model_status()
        self._enable_dev_affordances()

    # -- dev-only reroll (M11.6) -------------------------------------------

    def _enable_dev_affordances(self) -> None:
        """Bind the reroll key only when `SYZYGY_DEV` is set.

        Bound at runtime rather than declared in `BINDINGS` so that with
        the switch off the binding genuinely does not exist: the key does
        nothing and the footer never advertises it. A normal user cannot
        reach a destructive action by accident.
        """
        if not dev_mode_enabled():
            return
        self._bindings.bind("x", "dev_reroll", "DEV: reroll")
        self.query_one("#home-dev", Static).update(
            f"DEV MODE ({DEV_MODE_ENV_VAR} is set)  ·  [X] discard today's reading and redraw"
        )

    def action_dev_reroll(self) -> None:
        if not dev_mode_enabled() or self.syzygy.profile is None:
            return
        if self._reading is None:
            self.query_one("#home-status", Static).update(
                "Nothing to reroll - today's card has not been drawn yet."
            )
            self.app.bell()
            return
        card = self._reading.card_draw.card_id if self._reading.card_draw else "no card"
        self.query_one("#reroll-body", Static).update(
            f"DEV: discard today's reading ({card}) and draw a new one?\n"
            f"The existing card and its interpretation are destroyed. "
            f"This is a development affordance, not part of the ritual."
        )
        self.query_one("#home-reroll-confirm").remove_class("hidden")
        # CANCEL holds focus - this throws away a real reading.
        self.query_one("#reroll-cancel", Button).focus()

    def _close_reroll_confirm(self) -> None:
        self.query_one("#home-reroll-confirm").add_class("hidden")
        self.query_one("#primary-action", Button).focus()

    def _do_reroll(self) -> None:
        profile = self.syzygy.profile
        if profile is None or not dev_mode_enabled():
            return
        services = self.syzygy.services
        local_date = services.clock.now_utc().astimezone().date().isoformat()
        discard_todays_reading(services.conn, profile.id, local_date)
        self._close_reroll_confirm()
        self._refresh_reading_state()
        self.query_one("#home-status", Static).update(
            "DEV: today's reading was discarded. Turn the wheel for a new card."
        )

    def on_screen_resume(self) -> None:
        # Coming back from the wheel/reveal/reading flow: today's reading
        # may now exist, which changes the primary action. Coming back
        # from model setup (M10.4), the active provider may have changed.
        super().on_screen_resume()
        self._refresh_reading_state()
        self._load_model_status()

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

    # -- model provider status (M10.4) -------------------------------------

    @work(thread=True, exclusive=True, group="model-status")
    def _load_model_status(self) -> None:
        try:
            status = load_status()
        except ImportError:
            # The `providers` extra isn't installed - fixture is the only
            # provider that can possibly be active, so say nothing more.
            self.app.call_from_thread(self._model_status_resolved, None)
            return
        self.app.call_from_thread(self._model_status_resolved, status)

    def _model_status_resolved(self, status: ProviderStatus | None) -> None:
        if not self.is_mounted or status is None:
            return
        label = status.active_provider_id
        if status.active_model_id:
            label += f" ({status.active_model_id})"
        text = f"Model: {label}"
        if status.fallback_reason:
            text += f" - falling back to fixture: {status.fallback_reason}"
        text += "  ·  [M] configure"
        self.query_one("#home-model-status", Static).update(text)

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
        elif event.button.id == "reroll-cancel":
            self._close_reroll_confirm()
        elif event.button.id == "reroll-confirm":
            self._do_reroll()

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

    def action_model(self) -> None:
        self.app.push_screen("model_setup")

    def refresh_reading(self) -> None:
        """Re-read today's reading from storage (used after a draw)."""
        self._refresh_reading_state()
