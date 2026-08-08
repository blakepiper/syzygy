"""The archive (DESIGN.md section 15) - list view only for now.

Milestone 5 needs somewhere to reopen a past reading from; the reading
detail, card/suit frequencies, and transit filters are Milestone 8
(`TASKS.md` M8.2). Reopening is a pure read: a past reading is rendered
from stored data, never recalculated and never re-interpreted.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Footer, Label, ListItem, ListView, Static

from syzygy.domain.reading import Reading, ReadingStatus
from syzygy.sortes.deck import get_card
from syzygy.storage.readings import list_readings
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
    BINDINGS = [("escape", "back", "back"), ("q", "quit", "quit")]

    def compose(self) -> ComposeResult:
        yield TitleBar("ARCHIVE")
        yield Static("", id="archive-summary", classes="muted")
        yield ListView(id="archive-list")
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

    def action_back(self) -> None:
        if len(self.app.screen_stack) > 1:
            self.app.pop_screen()
