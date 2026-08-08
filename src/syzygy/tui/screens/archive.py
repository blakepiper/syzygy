"""The archive (DESIGN.md section 15): list, reopen, and card/suit
frequency counts.

Reading detail reuses `ReadingScreen` with `interpret=False` - reopening a
past reading is a pure read, rendered from stored data, never recalculated
and never re-interpreted (DESIGN.md section 15.1). The frequency view is
descriptive counts only (`readings.card_frequency`/`suit_frequency`) - no
LLM trend analysis and no implied statistical significance, per
DESIGN.md section 15.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Footer, Label, ListItem, ListView, Static

from syzygy.domain.reading import Reading, ReadingStatus
from syzygy.sortes.deck import get_card
from syzygy.storage.readings import card_frequency, list_readings, suit_frequency
from syzygy.tui.screens.base import SyzygyScreen, TitleBar


class ReadingListItem(ListItem):
    def __init__(self, reading: Reading) -> None:
        if reading.card_draw is not None:
            card = get_card(reading.card_draw.card_id)
            card_label = card.full_name
        else:
            card_label = "—"
        status = "" if reading.status == ReadingStatus.COMPLETE else f"  [{reading.status.value}]"
        super().__init__(Label(f"{reading.consultation_local_date}   {card_label}{status}"))
        self.reading = reading


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
        listing = self.query_one("#archive-list", ListView)
        for reading in readings:
            listing.append(ReadingListItem(reading))
        self.query_one("#archive-summary", Static).update(
            f"Readings {len(readings)}" if readings else "No readings yet."
        )
        if readings:
            listing.index = 0
        listing.focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if isinstance(item, ReadingListItem):
            from syzygy.tui.screens.reading import ReadingScreen

            self.app.push_screen(ReadingScreen(item.reading, interpret=False))

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
