"""Live and archived rendering of a fixed Oracle consultation."""

from __future__ import annotations

from enum import StrEnum

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Static

from syzygy.domain.oracle import OracleConsultation, OracleStatus
from syzygy.interpretation.providers.fixture import FixtureProvider
from syzygy.sortes.deck import get_card
from syzygy.storage import oracle
from syzygy.storage.oracle_service import interpret_oracle
from syzygy.tui import palette
from syzygy.tui.screens.base import SyzygyScreen, TitleBar
from syzygy.tui.widgets.reading_panel import NO_PASSAGES_ACTION, NO_PASSAGES_NOTE
from syzygy.tui.widgets.tarot_card import TarotCardWidget
from syzygy.tui.widgets.transit_badge import TransitBadge, format_transit


class OracleView(StrEnum):
    ANSWER = "answer"
    ESOTERIC = "esoteric"
    CONVENTIONAL = "conventional"
    INPUTS = "inputs"


class OracleResultScreen(SyzygyScreen):
    BINDINGS = [
        ("a", "view_answer", "answer"),
        ("1", "view_esoteric", "esoteric"),
        ("2", "view_conventional", "conventional"),
        ("i", "view_inputs", "inputs"),
        ("r,R", "retry", "retry"),
        ("f,F", "fixture", "fixture"),
        ("m", "model", "model"),
        ("escape", "back", "back"),
    ]

    def __init__(self, consultation: OracleConsultation, *, interpret: bool = True) -> None:
        super().__init__()
        self.consultation = consultation
        self._may_interpret = interpret
        self._interpreting = False
        self._view = OracleView.ANSWER

    def compose(self) -> ComposeResult:
        yield TitleBar(self.consultation.question.consultation_local_date)
        with Horizontal(id="oracle-result-columns"):
            with Vertical(id="oracle-result-aside"):
                yield TarotCardWidget(glyphs=self.syzygy.glyphs, id="oracle-result-card")
                with Vertical(id="oracle-result-transits"):
                    pass
            with Vertical(id="oracle-result-main"):
                yield Static("THE ALIGNMENT IS FIXED.", id="oracle-result-title", classes="lede")
                yield Static(
                    f"“{self.consultation.question.text}”",
                    id="oracle-result-question",
                    classes="muted",
                )
                yield VerticalScroll(Static("", id="oracle-result-body"), id="oracle-result-panel")
        yield Static("", id="oracle-result-keys", classes="keys", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        if self.consultation.card_draw is not None:
            self.query_one("#oracle-result-card", TarotCardWidget).set_card(
                get_card(self.consultation.card_draw.card_id)
            )
        context = self.consultation.interpretation_context
        if context is not None:
            transits = self.query_one("#oracle-result-transits", Vertical)
            for transit in context.significant_transits[:4]:
                transits.mount(TransitBadge(transit, glyphs=self.syzygy.glyphs))
        self._show()
        if self._may_interpret and self.consultation.status not in (
            OracleStatus.COMPLETE,
            OracleStatus.INTERPRETING,
        ):
            self._begin_interpretation()

    def _interrupted(self) -> bool:
        return self.consultation.status is OracleStatus.INTERPRETING and not self._interpreting

    def _may_retry(self) -> bool:
        return self._may_interpret and not self._interpreting and (
            self.consultation.status is OracleStatus.INTERPRETATION_FAILED
            or self._interrupted()
        )

    def _show(self) -> None:
        result = self.consultation.result
        text = Text()
        heading = f"bold {palette.ACCENT}"
        body = palette.BONE
        muted = palette.MUTED
        if result is None and self._interpreting:
            text.append("INTERPRETATION IN PROGRESS…\n", style=muted)
        elif result is None:
            text.append("THE ALIGNMENT IS FIXED.\n", style=heading)
            text.append(
                "INTERPRETATION WAS INTERRUPTED.\n"
                if self._interrupted()
                else "INTERPRETATION IS UNAVAILABLE.\n",
                style=f"bold {palette.EMBER}",
            )
            if self._may_interpret:
                text.append(
                    "\n[R] Retry  [F] use offline fixture  [M] configure model\n",
                    style=body,
                )
        elif self._view is OracleView.ANSWER:
            text.append("RESPONSE\n\n", style=heading)
            text.append(result.question_response, style=body)
        elif self._view is OracleView.ESOTERIC:
            text.append("ESOTERIC\n\n", style=heading)
            text.append(f"{result.esoteric.summary}\n\n{result.esoteric.body}", style=body)
        elif self._view is OracleView.CONVENTIONAL:
            text.append("CONVENTIONAL\n\n", style=heading)
            text.append(
                f"{result.conventional.summary}\n\n{result.conventional.body}\n",
                style=body,
            )
            if result.conventional.watch_for:
                text.append("\nWATCH FOR\n", style=heading)
                for item in result.conventional.watch_for:
                    text.append(f"• {item}\n", style=body)
            text.append("\nREFLECT\n", style=heading)
            text.append(result.conventional.reflection, style=body)
        else:
            self._append_inputs(text, heading, body, muted)
        self.query_one("#oracle-result-body", Static).update(text)
        title = result.alignment_title if result is not None else "THE ALIGNMENT IS FIXED."
        self.query_one("#oracle-result-title", Static).update(title)
        keys = "[A] ANSWER   [1] ESOTERIC   [2] CONVENTIONAL   [I] INPUTS"
        if self._may_retry():
            keys += "   [R] RETRY   [F] FIXTURE   [M] MODEL"
        keys += "   [Q] QUIT"
        self.query_one("#oracle-result-keys", Static).update(keys)

    def _append_inputs(self, text: Text, heading: str, body: str, muted: str) -> None:
        context = self.consultation.interpretation_context
        text.append("INPUTS\n\n", style=heading)
        if context is None or context.card is None:
            text.append("No interpretation context was committed.\n", style=muted)
            return
        text.append("QUESTION (USER TEXT)\n", style=heading)
        text.append(f"  {self.consultation.question.text}\n", style=body)
        text.append("\nCARD (FIXED, UPRIGHT)\n", style=heading)
        text.append(f"  {context.card.full_name} ({context.card.id})\n", style=body)
        text.append("\nSELECTED TRANSITS\n", style=heading)
        if context.significant_transits:
            for transit in context.significant_transits:
                text.append(f"  #{transit.rank} {format_transit(transit, self.syzygy.glyphs)}\n")
        else:
            text.append("  none in orb\n", style=muted)
        text.append("\nPASSAGES SENT TO THE MODEL\n", style=heading)
        if context.knowledge_chunks:
            for chunk in context.knowledge_chunks:
                text.append(f"  {chunk.title} (pages {chunk.page_start}-{chunk.page_end})\n")
        else:
            text.append(f"  none.\n  {NO_PASSAGES_NOTE}\n  {NO_PASSAGES_ACTION}\n", style=muted)
        text.append("\nWHERE THIS CARD IS DISCUSSED\n", style=heading)
        if self.consultation.retrieved_citations:
            for citation in self.consultation.retrieved_citations:
                text.append(f"  {citation.reference}\n", style=body)
        else:
            text.append("  no citations were recorded.\n", style=muted)
        text.append("\nPROVENANCE\n", style=heading)
        text.append(f"  provider: {self.consultation.provider_id or '—'}\n", style=body)
        text.append(f"  model: {self.consultation.model_id or '—'}\n", style=body)
        text.append(f"  prompt version: {context.prompt_version}\n", style=body)

    def _begin_interpretation(self, provider=None) -> None:
        self._interpreting = True
        self._show()
        self._interpret(provider)

    @work(exclusive=True, group="oracle-interpret")
    async def _interpret(self, provider=None) -> None:
        services = self.syzygy.services
        selected_provider = provider or services.provider
        try:
            self.consultation = await interpret_oracle(
                services.conn, self.consultation, services.clock, selected_provider
            )
        except Exception:
            latest = oracle.get_by_id(services.conn, self.consultation.id)
            if latest is not None:
                self.consultation = latest
        self._interpreting = False
        self._show()

    def action_retry(self) -> None:
        if self._may_retry():
            self._begin_interpretation()
        else:
            self.app.bell()

    def action_fixture(self) -> None:
        if self._may_retry():
            self._begin_interpretation(FixtureProvider())
        else:
            self.app.bell()

    def action_model(self) -> None:
        self.app.push_screen("model_setup")

    def action_view_answer(self) -> None:
        self._view = OracleView.ANSWER
        self._show()

    def action_view_esoteric(self) -> None:
        self._view = OracleView.ESOTERIC
        self._show()

    def action_view_conventional(self) -> None:
        self._view = OracleView.CONVENTIONAL
        self._show()

    def action_view_inputs(self) -> None:
        self._view = OracleView.INPUTS
        self._show()

    def action_back(self) -> None:
        self.app.pop_screen()
