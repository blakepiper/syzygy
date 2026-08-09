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
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Footer, ListView, Static

from syzygy.domain.iching_consultation import IChingConsultation, IChingStatus
from syzygy.domain.oracle import OracleConsultation, OracleStatus
from syzygy.domain.reading import Reading, ReadingStatus
from syzygy.iching.book import get_hexagram
from syzygy.sortes.deck import get_card
from syzygy.storage.iching import (
    delete_consultation as delete_iching_consultation,
)
from syzygy.storage.iching import list_consultations as list_iching_consultations
from syzygy.storage.oracle import delete_consultation as delete_oracle_consultation
from syzygy.storage.oracle import list_consultations
from syzygy.storage.readings import (
    card_frequency,
    delete_from_archive,
    list_readings,
    suit_frequency,
)
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


class IChingListItem(MarkedListItem):
    def __init__(self, consultation: IChingConsultation) -> None:
        hexagram = (
            get_hexagram(consultation.cast.primary_hexagram_number)
            if consultation.cast is not None
            else None
        )
        cast_label = f"{hexagram.unicode} {hexagram.name}" if hexagram is not None else "—"
        status = (
            ""
            if consultation.status is IChingStatus.COMPLETE
            else f" [{consultation.status.value}]"
        )
        question = consultation.question.normalized_text
        if len(question) > 42:
            question = question[:39] + "…"
        super().__init__(
            f"{consultation.question.consultation_local_date}   I CHING   "
            f"{question} — {cast_label}{status}"
        )
        self.consultation = consultation


class ArchiveScreen(SyzygyScreen):
    BINDINGS = [
        ("escape", "back", "back"),
        ("f", "toggle_frequency", "counts"),
        ("d", "delete_entry", "delete"),
    ]

    _pending_delete: ReadingListItem | OracleListItem | IChingListItem | None = None

    def compose(self) -> ComposeResult:
        yield TitleBar("ARCHIVE")
        with Vertical(id="archive-body"):
            yield Static("", id="archive-summary", classes="muted")
            yield ListView(id="archive-list")
            yield VerticalScroll(
                Static("", id="archive-frequency"),
                id="archive-frequency-panel",
                classes="hidden",
            )
        with Vertical(id="archive-delete-confirm", classes="hidden"):
            yield Static("DELETE ARCHIVE ENTRY", classes="section-heading")
            yield Static("", id="archive-delete-body", markup=False)
            yield Static("", id="archive-delete-error", classes="error")
            with Horizontal(classes="button-row"):
                yield Button("DELETE", id="archive-delete-confirm-button", variant="error")
                yield Button("CANCEL", id="archive-delete-cancel")
        yield Footer()

    def on_mount(self) -> None:
        self._reload()

    def _reload(self) -> None:
        profile = self.syzygy.profile
        if profile is None:
            return
        readings = list_readings(self.syzygy.services.conn, profile.id)
        consultations = list_consultations(self.syzygy.services.conn, profile.id)
        iching_consultations = list_iching_consultations(
            self.syzygy.services.conn, profile.id
        )
        listing = self.query_one("#archive-list", ListView)
        listing.clear()
        entries: list[tuple[str, MarkedListItem]] = [
            (reading.consultation_utc_timestamp.isoformat(), ReadingListItem(reading))
            for reading in readings
        ]
        entries.extend(
            (consultation.question.asked_at_utc.isoformat(), OracleListItem(consultation))
            for consultation in consultations
        )
        entries.extend(
            (consultation.question.asked_at_utc.isoformat(), IChingListItem(consultation))
            for consultation in iching_consultations
        )
        for _, item in sorted(entries, key=lambda entry: entry[0], reverse=True):
            listing.append(item)
        self.query_one("#archive-summary", Static).update(
            f"Readings {len(readings)}  ·  Thoth {len(consultations)}  ·  "
            f"I Ching {len(iching_consultations)}"
            if entries
            else "No readings yet. No Oracle consultations yet."
        )
        if entries:
            listing.index = 0
        listing.focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if not self.query_one("#archive-delete-confirm").has_class("hidden"):
            return
        item = event.item
        if isinstance(item, ReadingListItem):
            from syzygy.tui.screens.reading import ReadingScreen

            self.app.push_screen(ReadingScreen(item.reading, interpret=False))
        elif isinstance(item, OracleListItem):
            from syzygy.tui.screens.oracle_result import OracleResultScreen

            self.app.push_screen(OracleResultScreen(item.consultation, interpret=False))
        elif isinstance(item, IChingListItem):
            from syzygy.tui.screens.iching_result import IChingResultScreen

            self.app.push_screen(IChingResultScreen(item.consultation, interpret=False))

    def action_toggle_frequency(self) -> None:
        if not self.query_one("#archive-delete-confirm").has_class("hidden"):
            return
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

    def action_delete_entry(self) -> None:
        """Ask before deleting the highlighted archive record."""
        confirmation = self.query_one("#archive-delete-confirm")
        if not confirmation.has_class("hidden"):
            return
        frequency = self.query_one("#archive-frequency-panel", VerticalScroll)
        if not frequency.has_class("hidden"):
            self.app.bell()
            return
        item = self.query_one("#archive-list", ListView).highlighted_child
        if not isinstance(item, (ReadingListItem, OracleListItem, IChingListItem)):
            self.app.bell()
            return

        self._pending_delete = item
        if isinstance(item, ReadingListItem):
            record = item.reading
            detail = f"daily reading for {record.consultation_local_date}"
            consequence = (
                "That date will remain used; deleting this entry does not permit "
                "another draw."
            )
        elif isinstance(item, OracleListItem):
            question = self._confirmation_question(
                item.consultation.question.normalized_text
            )
            detail = f'Thoth Oracle question “{question}”'
            consequence = "Its fixed card and interpretation will be permanently removed."
        else:
            question = self._confirmation_question(
                item.consultation.question.normalized_text
            )
            detail = f'I Ching question “{question}”'
            consequence = "Its fixed cast and interpretation will be permanently removed."
        self.query_one("#archive-delete-body", Static).update(
            f"Delete this {detail}?\n\n{consequence}\nThis cannot be undone."
        )
        self.query_one("#archive-delete-error", Static).update("")
        self.query_one("#archive-body").add_class("hidden")
        confirmation.remove_class("hidden")
        # A reflexive Enter cancels; destructive confirmation requires a
        # deliberate focus move or click.
        self.query_one("#archive-delete-cancel", Button).focus()

    @staticmethod
    def _confirmation_question(question: str) -> str:
        return question if len(question) <= 100 else question[:97] + "…"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "archive-delete-confirm-button":
            self._confirm_delete()
        elif event.button.id == "archive-delete-cancel":
            self._cancel_delete()

    def _cancel_delete(self) -> None:
        self._pending_delete = None
        self.query_one("#archive-delete-confirm").add_class("hidden")
        self.query_one("#archive-body").remove_class("hidden")
        self.query_one("#archive-list", ListView).focus()

    def _confirm_delete(self) -> None:
        item = self._pending_delete
        profile = self.syzygy.profile
        if item is None or profile is None:
            return
        conn = self.syzygy.services.conn
        try:
            if isinstance(item, ReadingListItem):
                deleted = delete_from_archive(
                    conn,
                    item.reading.id,
                    profile_id=profile.id,
                    deleted_at=self.syzygy.services.clock.now_utc(),
                )
            elif isinstance(item, OracleListItem):
                deleted = delete_oracle_consultation(
                    conn, item.consultation.id, profile_id=profile.id
                )
            else:
                deleted = delete_iching_consultation(
                    conn, item.consultation.id, profile_id=profile.id
                )
            if not deleted:
                raise ValueError("the selected entry no longer exists")
        except Exception as exc:  # docs/old/DESIGN.md section 23: visible failures
            self.query_one("#archive-delete-error", Static).update(
                f"Could not delete this entry - {type(exc).__name__}: {exc}"
            )
            return

        self._pending_delete = None
        self.query_one("#archive-delete-confirm").add_class("hidden")
        self.query_one("#archive-body").remove_class("hidden")
        self._reload()

    def action_back(self) -> None:
        if not self.query_one("#archive-delete-confirm").has_class("hidden"):
            self._cancel_delete()
            return
        panel = self.query_one("#archive-frequency-panel", VerticalScroll)
        if "hidden" not in panel.classes:
            self.action_toggle_frequency()
            return
        if len(self.app.screen_stack) > 1:
            self.app.pop_screen()
