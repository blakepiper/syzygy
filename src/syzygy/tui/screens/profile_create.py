"""Profile creation: birth facts in, saved natal chart out.

Two phases, because DESIGN.md section 6.1 requires the user to review the
resolved birthplace values *before* the chart is calculated: the form,
then a confirmation panel. Entry is manual - geocoding is an optional
onboarding convenience (the `geocoding` extra), never part of calculation,
and manual latitude/longitude/timezone entry must work without it.

The chart itself is calculated exactly once here and then saved
(DESIGN.md section 6.2); nothing later recalculates it silently.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Footer, Input, Static

from syzygy.domain.astrology import BirthData
from syzygy.domain.profile import Profile
from syzygy.storage.profiles import insert_profile
from syzygy.tui.screens.base import SyzygyScreen, TitleBar

_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("display-name", "NAME", "Blake"),
    ("birth-date", "BIRTH DATE", "1990-08-07"),
    ("birth-time", "BIRTH TIME (LOCAL, 24H)", "14:22"),
    ("place-label", "BIRTHPLACE", "Alexandria, Virginia, USA"),
    ("latitude", "LATITUDE", "38.8048"),
    ("longitude", "LONGITUDE", "-77.0469"),
    ("timezone", "IANA TIMEZONE", "America/New_York"),
)


class ProfileCreateScreen(SyzygyScreen):
    """Collect birth data, confirm it, then calculate and store the chart."""

    BINDINGS = [("escape", "cancel", "cancel")]

    #: Collected and validated in the form phase, used in the confirm phase.
    _pending: tuple[str, BirthData] | None = None

    def compose(self) -> ComposeResult:
        yield TitleBar("CREATE PROFILE")
        with VerticalScroll(id="profile-form"):
            yield Static(
                "Exact birth time matters. Coordinates and timezone are entered\n"
                "directly - geocoding is optional and never part of the calculation.",
                classes="muted",
            )
            for field_id, label, placeholder in _FIELDS:
                yield Static(label, classes="field-label")
                yield Input(placeholder=placeholder, id=field_id)
            yield Static("", id="form-error", classes="error")
            yield Button("REVIEW", id="review", variant="primary")
        with Vertical(id="profile-confirm", classes="hidden"):
            yield Static("BIRTHPLACE", classes="section-heading")
            yield Static("", id="confirm-body")
            with Horizontal(classes="button-row"):
                yield Button("CONFIRM", id="confirm", variant="success")
                yield Button("EDIT", id="edit")
        yield Footer()

    # -- phase 1: the form ------------------------------------------------

    def _value(self, field_id: str) -> str:
        return self.query_one(f"#{field_id}", Input).value.strip()

    def _collect(self) -> tuple[str, BirthData] | str:
        """Return `(display_name, birth_data)`, or an error message."""
        display_name = self._value("display-name")
        if not display_name:
            return "A display name is required."

        raw_date = self._value("birth-date")
        try:
            local_date = datetime.strptime(raw_date, "%Y-%m-%d").date().isoformat()
        except ValueError:
            return f"Birth date {raw_date!r} is not an ISO date (YYYY-MM-DD)."

        raw_time = self._value("birth-time")
        parsed_time = None
        for time_format in ("%H:%M:%S", "%H:%M"):
            try:
                parsed_time = datetime.strptime(raw_time, time_format).time()
                break
            except ValueError:
                continue
        if parsed_time is None:
            return f"Birth time {raw_time!r} is not a 24-hour time (HH:MM)."

        try:
            latitude = float(self._value("latitude"))
            longitude = float(self._value("longitude"))
        except ValueError:
            return "Latitude and longitude must be decimal degrees."

        timezone = self._value("timezone")
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            return f"{timezone!r} is not an IANA timezone (e.g. America/New_York)."

        try:
            birth = BirthData(
                local_date=local_date,
                local_time=parsed_time.isoformat(),
                place_label=self._value("place-label") or "unspecified",
                latitude=latitude,
                longitude=longitude,
                timezone=timezone,
            )
        except ValueError as exc:  # pydantic range validation
            return str(exc)
        return display_name, birth

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "review":
            self._review()
        elif event.button.id == "edit":
            self._show_form()
        elif event.button.id == "confirm":
            self._confirm()

    def _review(self) -> None:
        collected = self._collect()
        error = self.query_one("#form-error", Static)
        if isinstance(collected, str):
            error.update(collected)
            return
        error.update("")
        self._pending = collected
        display_name, birth = collected
        north_south = "N" if birth.latitude >= 0 else "S"
        east_west = "E" if birth.longitude >= 0 else "W"
        self.query_one("#confirm-body", Static).update(
            f"Entered:\n"
            f"  {display_name}\n"
            f"  {birth.local_date} {birth.local_time}\n"
            f"  {birth.place_label}\n\n"
            f"Resolved:\n"
            f"  {abs(birth.latitude):.4f} {north_south}\n"
            f"  {abs(birth.longitude):.4f} {east_west}\n"
            f"  {birth.timezone}\n"
            f"  houses: {birth.house_system}"
        )
        self.query_one("#profile-form").add_class("hidden")
        self.query_one("#profile-confirm").remove_class("hidden")

    def _show_form(self) -> None:
        self.query_one("#profile-confirm").add_class("hidden")
        self.query_one("#profile-form").remove_class("hidden")

    # -- phase 2: calculation --------------------------------------------

    def _confirm(self) -> None:
        if self._pending is None:
            return
        display_name, birth = self._pending
        self.query_one("#confirm-body", Static).update("CALCULATING SELF…")
        self.query_one("#confirm", Button).disabled = True
        self.query_one("#edit", Button).disabled = True
        self._calculate(display_name, birth)

    @work(thread=True, exclusive=True)
    def _calculate(self, display_name: str, birth: BirthData) -> None:
        """Calculate and store the natal chart off the event loop, so the
        interface stays responsive during ephemeris work."""
        services = self.syzygy.services
        try:
            natal = services.astrology.calculate_natal(birth)
            now = services.clock.now_utc()
            profile = Profile(
                id=str(uuid.uuid4()),
                display_name=display_name,
                birth_data=birth,
                natal_chart=natal,
                created_at_utc=now,
                updated_at_utc=now,
            )
            insert_profile(services.conn, profile)
        except Exception as exc:  # calculation or storage failure
            self.app.call_from_thread(self._failed, f"{type(exc).__name__}: {exc}")
            return
        self.app.call_from_thread(self._created, profile)

    def _created(self, profile: Profile) -> None:
        self.syzygy.set_profile(profile)
        self.app.switch_screen("home")

    def _failed(self, message: str) -> None:
        if not self.is_mounted:
            return
        # DESIGN.md section 23: show the failing input, keep the data.
        self._show_form()
        self.query_one("#confirm", Button).disabled = False
        self.query_one("#edit", Button).disabled = False
        self.query_one("#form-error", Static).update(f"Chart calculation failed - {message}")

    def action_cancel(self) -> None:
        if len(self.app.screen_stack) > 1:
            self.app.pop_screen()
