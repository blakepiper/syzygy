"""The archive (docs/old/DESIGN.md section 15): list, reopen, and card/suit
frequency counts.

Reading detail reuses `ReadingScreen` with `interpret=False` - reopening a
past reading is a pure read, rendered from stored data, never recalculated
and never re-interpreted (docs/old/DESIGN.md section 15.1). The frequency view is
descriptive counts only (`readings.card_frequency`/`suit_frequency`) - no
LLM trend analysis and no implied statistical significance, per
docs/old/DESIGN.md section 15.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Footer, ListView, Static

from syzygy.domain.oracle import OracleConsultation, OracleStatus
from syzygy.domain.reading import Reading, ReadingStatus
from syzygy.sortes.deck import get_card
from syzygy.storage.oracle import list_consultations
from syzygy.storage.readings import card_frequency, list_readings, suit_frequency
from syzygy.tui.screens.base import SyzygyScreen, TitleBar
from syzygy.tui.widgets.marked_list import MarkedListItem


class ReadingListItem(MarkedListItem):
    def __init__(self, reading: Reading) -> None:
        if reading.card_draw is not None:
            card = get_card(reading.card_draw.card_id)
            card_label = card.full_name
        else:
            card_label = "—"
        status = "" if reading.status == ReadingStatus.COMPLETE else f"  [{reading.status.value}]"
        super().__init__(f"{reading.consultation_local_date}   {card_label}{status}")
        self.reading = reading


class OracleListItem(MarkedListItem):
    def __init__(self, consultation: OracleConsultation) -> None:
        card_label = (
            get_card(consultation.card_draw.card_id).full_name
            if consultation.card_draw is not None
            else "—"
        )
        status = (
            ""
            if consultation.status is OracleStatus.COMPLETE
            else f" [{consultation.status.value}]"
        )
        question = consultation.question.normalized_text
        if len(question) > 42:
            question = question[:39] + "…"
        super().__init__(
            f"{consultation.question.consultation_local_date}   ORACLE   "
            f"{question} — {card_label}{status}"
        )
        self.consultation = consultation


class ArchiveScreen(SyzygyScreen):
    BINDINGS = [
        ("escape", "back", "back"),
        ("f", "toggle_frequency", "counts"),
    ]

    def compose(self) -> ComposeResult:
        yield TitleBar("ARCHIVE")
        yield Static("", id="archive-summary", classes="muted")
        yield ListView(id="archive-list")
        yield VerticalScroll(
            Static("", id="archive-frequency"), id="archive-frequency-panel", classes="hidden"
        )
        yield Footer()

    def on_mount(self) -> None:
        profile = self.syzygy.profile
        if profile is None:
            return
        readings = list_readings(self.syzygy.services.conn, profile.id)
        consultations = list_consultations(self.syzygy.services.conn, profile.id)
        listing = self.query_one("#archive-list", ListView)
        entries: list[tuple[str, MarkedListItem]] = [
            (reading.consultation_utc_timestamp.isoformat(), ReadingListItem(reading))
            for reading in readings
        ]
        entries.extend(
            (consultation.question.asked_at_utc.isoformat(), OracleListItem(consultation))
            for consultation in consultations
        )
        for _, item in sorted(entries, key=lambda entry: entry[0], reverse=True):
            listing.append(item)
        self.query_one("#archive-summary", Static).update(
            f"Readings {len(readings)}  ·  Oracle consultations {len(consultations)}"
            if entries
            else "No readings yet. No Oracle consultations yet."
        )
        if entries:
            listing.index = 0
        listing.focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if isinstance(item, ReadingListItem):
            from syzygy.tui.screens.reading import ReadingScreen

            self.app.push_screen(ReadingScreen(item.reading, interpret=False))
        elif isinstance(item, OracleListItem):
            from syzygy.tui.screens.oracle_result import OracleResultScreen

            self.app.push_screen(OracleResultScreen(item.consultation, interpret=False))

    def action_toggle_frequency(self) -> None:
        listing = self.query_one("#archive-list", ListView)
        panel = self.query_one("#archive-frequency-panel", VerticalScroll)
        if "hidden" in panel.classes:
            self._render_frequency(self.query_one("#archive-frequency", Static))
            listing.add_class("hidden")
            panel.remove_class("hidden")
            panel.focus()
        else:
            panel.add_class("hidden")
            listing.remove_class("hidden")
            listing.focus()

    def _render_frequency(self, counts: Static) -> None:
        profile = self.syzygy.profile
        if profile is None:
            counts.update("No profile is selected.")
            return
        conn = self.syzygy.services.conn
        cards = card_frequency(conn, profile.id)
        suits = suit_frequency(conn, profile.id)

        if not cards:
            counts.update("No readings yet - nothing to count.")
            return

        lines = ["Card counts (descriptive only - not a statistical claim)", ""]
        for card_id, n in cards.items():
            lines.append(f"  {get_card(card_id).full_name:<24} {n}")
        lines.extend(["", "By suit / major arcana", ""])
        for label, n in suits.items():
            lines.append(f"  {label.capitalize():<24} {n}")
        counts.update("\n".join(lines))

    def action_back(self) -> None:
        panel = self.query_one("#archive-frequency-panel", VerticalScroll)
        if "hidden" not in panel.classes:
            self.action_toggle_frequency()
            return
        if len(self.app.screen_stack) > 1:
            self.app.pop_screen()
