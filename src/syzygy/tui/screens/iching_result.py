"""Live and archived rendering of a fixed I Ching consultation."""

from __future__ import annotations

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Static

from syzygy.domain.iching import IChingLineValue
from syzygy.domain.iching_consultation import IChingConsultation, IChingStatus
from syzygy.interpretation.providers.fixture import FixtureProvider
from syzygy.storage import iching
from syzygy.storage.iching_service import interpret_iching
from syzygy.tui import palette
from syzygy.tui.screens.base import SyzygyScreen, TitleBar
from syzygy.tui.screens.oracle_result import OracleView
from syzygy.tui.widgets.transit_badge import TransitBadge, format_transit


def format_cast(consultation: IChingConsultation) -> str:
    cast = consultation.cast
    context = consultation.interpretation_context
    if cast is None:
        return "THE CAST IS NOT AVAILABLE"
    primary = context.primary_hexagram if context is not None else None
    heading = (
        f"{primary.unicode}  {primary.number}. {primary.name}"
        if primary is not None
        else f"HEXAGRAM {cast.primary_hexagram_number}"
    )
    line_glyphs = {
        IChingLineValue.OLD_YIN: "━━  ━━  ×",
        IChingLineValue.YOUNG_YANG: "━━━━━━",
        IChingLineValue.YOUNG_YIN: "━━  ━━",
        IChingLineValue.OLD_YANG: "━━━━━━  ○",
    }
    # A hexagram is conventionally displayed top line first.
    return "\n".join([heading, "", *(line_glyphs[line] for line in reversed(cast.lines))])


class IChingResultScreen(SyzygyScreen):
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

    def __init__(self, consultation: IChingConsultation, *, interpret: bool = True) -> None:
        super().__init__()
        self.consultation = consultation
        self._may_interpret = interpret
        self._interpreting = False
        self._view = OracleView.ANSWER

    def compose(self) -> ComposeResult:
        yield TitleBar(self.consultation.question.consultation_local_date)
        with Horizontal(id="iching-result-columns"):
            with Vertical(id="iching-result-aside"):
                yield Static(format_cast(self.consultation), id="iching-result-cast")
                with Vertical(id="iching-result-transits"):
                    pass
            with Vertical(id="iching-result-main"):
                yield Static("THE CAST IS FIXED.", id="iching-result-title", classes="lede")
                yield Static(
                    f"“{self.consultation.question.text}”",
                    id="iching-result-question",
                    classes="muted",
                )
                yield VerticalScroll(
                    Static("", id="iching-result-body"), id="iching-result-panel"
                )
        yield Static("", id="iching-result-keys", classes="keys", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        context = self.consultation.interpretation_context
        if context is not None:
            transits = self.query_one("#iching-result-transits", Vertical)
            for transit in context.significant_transits[:4]:
                transits.mount(TransitBadge(transit, glyphs=self.syzygy.glyphs))
        self._show()
        if self._may_interpret and self.consultation.status not in (
            IChingStatus.COMPLETE,
            IChingStatus.INTERPRETING,
        ):
            self._begin_interpretation()

    def _interrupted(self) -> bool:
        return self.consultation.status is IChingStatus.INTERPRETING and not self._interpreting

    def _may_retry(self) -> bool:
        return self._may_interpret and not self._interpreting and (
            self.consultation.status is IChingStatus.INTERPRETATION_FAILED or self._interrupted()
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
            text.append("THE CAST IS FIXED.\n", style=heading)
            text.append(
                "INTERPRETATION WAS INTERRUPTED.\n"
                if self._interrupted()
                else "INTERPRETATION IS UNAVAILABLE.\n",
                style=f"bold {palette.EMBER}",
            )
            if self._may_interpret:
                text.append("\n[R] Retry  [F] use offline fixture  [M] configure model\n")
        elif self._view is OracleView.ANSWER:
            text.append("RESPONSE\n\n", style=heading)
            text.append(result.question_response, style=body)
        elif self._view is OracleView.ESOTERIC:
            text.append("ESOTERIC\n\n", style=heading)
            text.append(f"{result.esoteric.summary}\n\n{result.esoteric.body}", style=body)
        elif self._view is OracleView.CONVENTIONAL:
            text.append("CONVENTIONAL\n\n", style=heading)
            text.append(f"{result.conventional.summary}\n\n{result.conventional.body}\n")
            if result.conventional.watch_for:
                text.append("\nWATCH FOR\n", style=heading)
                for item in result.conventional.watch_for:
                    text.append(f"• {item}\n", style=body)
            text.append("\nREFLECT\n", style=heading)
            text.append(result.conventional.reflection, style=body)
        else:
            self._append_inputs(text, heading, body, muted)
        self.query_one("#iching-result-body", Static).update(text)
        self.query_one("#iching-result-title", Static).update(
            result.alignment_title if result is not None else "THE CAST IS FIXED."
        )
        keys = "[A] ANSWER   [1] ESOTERIC   [2] CONVENTIONAL   [I] INPUTS"
        if self._may_retry():
            keys += "   [R] RETRY   [F] FIXTURE   [M] MODEL"
        self.query_one("#iching-result-keys", Static).update(keys + "   [Q] QUIT")

    def _append_inputs(self, text: Text, heading: str, body: str, muted: str) -> None:
        context = self.consultation.interpretation_context
        cast = self.consultation.cast
        text.append("INPUTS\n\n", style=heading)
        if context is None or cast is None or context.primary_hexagram is None:
            text.append("No interpretation context was committed.\n", style=muted)
            return
        primary = context.primary_hexagram
        resulting = context.resulting_hexagram
        text.append("QUESTION (USER TEXT)\n", style=heading)
        text.append(f"  {self.consultation.question.text}\n", style=body)
        text.append("\nCAST (FIXED, BOTTOM LINE FIRST)\n", style=heading)
        text.append(f"  values: {' '.join(str(int(line)) for line in cast.lines)}\n", style=body)
        text.append(f"  primary: {primary.number}. {primary.name} {primary.unicode}\n", style=body)
        text.append(
            f"  changing lines: {', '.join(map(str, cast.changing_lines)) or 'none'}\n",
            style=body,
        )
        if cast.changing_lines and resulting is not None:
            text.append(
                f"  resulting: {resulting.number}. {resulting.name} {resulting.unicode}\n",
                style=body,
            )
        text.append("\nLEGGE 1882 CITATIONS\n", style=heading)
        text.append(
            f"  primary text pp. {primary.citation.text_pages}; "
            f"Image pp. {primary.citation.image_pages}\n",
            style=body,
        )
        if cast.changing_lines and resulting is not None:
            text.append(
                f"  resulting text pp. {resulting.citation.text_pages}; "
                f"Image pp. {resulting.citation.image_pages}\n",
                style=body,
            )
        text.append("\nSELECTED TRANSITS\n", style=heading)
        if context.significant_transits:
            for transit in context.significant_transits:
                text.append(f"  #{transit.rank} {format_transit(transit, self.syzygy.glyphs)}\n")
        else:
            text.append("  none in orb\n", style=muted)
        text.append("\nPROVENANCE\n", style=heading)
        text.append(f"  provider: {self.consultation.provider_id or '—'}\n", style=body)
        text.append(f"  model: {self.consultation.model_id or '—'}\n", style=body)
        text.append(f"  prompt version: {context.prompt_version}\n", style=body)

    def _begin_interpretation(self, provider=None) -> None:
        self._interpreting = True
        self._show()
        self._interpret(provider)

    @work(exclusive=True, group="iching-interpret")
    async def _interpret(self, provider=None) -> None:
        services = self.syzygy.services
        selected_provider = provider or services.provider
        try:
            self.consultation = await interpret_iching(
                services.conn, self.consultation, services.clock, selected_provider
            )
        except Exception:
            latest = iching.get_by_id(services.conn, self.consultation.id)
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
