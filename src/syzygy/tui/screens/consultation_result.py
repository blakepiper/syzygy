"""The Oracle's result: one card standing in one hexagram (ADR 0008).

Reveal order is deliberately *not* narration order. The card is revealed
first — it is the wheel's payoff and the application's visual identity —
with the six lines building upward beneath it, while the prose reads
ground-first, the way the contract composes it. Both objects were
committed before this screen existed; nothing here can redraw, recast, or
separate them.

The same screen reopens the two superseded rites (`oracle-v1` cards
without a cast, `iching-v1` casts without a card). Those are read-only
history: they are labelled as the single-object rite they were, and no
retry path exists for them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Static

from syzygy.domain.consultation import Consultation, ConsultationStatus
from syzygy.domain.iching import Hexagram, IChingCast, IChingLineValue
from syzygy.domain.iching_consultation import IChingConsultation
from syzygy.domain.interpretation import InterpretationContext, OracleResult
from syzygy.domain.knowledge import RetrievedCitation
from syzygy.domain.oracle import OracleConsultation, OracleQuestion
from syzygy.iching.book import get_hexagram
from syzygy.interpretation.providers.fixture import FixtureProvider
from syzygy.sortes.deck import get_card
from syzygy.storage import consultations
from syzygy.storage.consultation_service import interpret_consultation
from syzygy.tui import palette
from syzygy.tui.screens.base import SyzygyScreen, TitleBar
from syzygy.tui.widgets.reading_panel import NO_PASSAGES_ACTION, NO_PASSAGES_NOTE
from syzygy.tui.widgets.tarot_card import TarotCardWidget

#: A cast is conventionally *made* bottom upward and *displayed* top line
#: first. Both orders matter here: the reveal animates the first, the
#: layout renders the second.
LINE_GLYPHS: dict[IChingLineValue, str] = {
    IChingLineValue.OLD_YIN: "━━  ━━  ×",
    IChingLineValue.YOUNG_YANG: "━━━━━━",
    IChingLineValue.YOUNG_YIN: "━━  ━━",
    IChingLineValue.OLD_YANG: "━━━━━━  ○",
}

AnyConsultation = Consultation | OracleConsultation | IChingConsultation


class ConsultationView(StrEnum):
    ANSWER = "answer"
    ESOTERIC = "esoteric"
    CONVENTIONAL = "conventional"
    INPUTS = "inputs"


def movement_note(cast: IChingCast, resulting: Hexagram | None = None) -> str:
    """One line saying whether anything is moving, always present.

    Stillness is an answer (ADR 0008 section 6), so the settled case gets
    a sentence of its own rather than an empty row where the changing
    lines would have been.
    """
    if not cast.changing_lines:
        return "nothing is moving — the ground is settled"
    positions = ", ".join(map(str, cast.changing_lines))
    plural = "s" if len(cast.changing_lines) != 1 else ""
    note = f"moving at line{plural} {positions}"
    if resulting is not None:
        note += f"\n→ {resulting.unicode} {resulting.number}. {resulting.name}"
    return note


@dataclass
class _Record:
    """One archive record of any of the three rites, normalized.

    Everything the screen renders comes off this object, so the legacy
    kinds cost the screen a construction branch rather than a branch in
    every method.
    """

    consultation: AnyConsultation
    question: OracleQuestion
    status_value: str
    card_id: str | None = None
    cast: IChingCast | None = None
    context: InterpretationContext | None = None
    citations: list[RetrievedCitation] = field(default_factory=list)
    result: OracleResult | None = None
    provider_id: str | None = None
    model_id: str | None = None
    legacy_note: str | None = None

    @property
    def is_legacy(self) -> bool:
        return self.legacy_note is not None

    @property
    def primary_hexagram(self) -> Hexagram | None:
        return get_hexagram(self.cast.primary_hexagram_number) if self.cast else None

    @property
    def resulting_hexagram(self) -> Hexagram | None:
        if self.cast is None or not self.cast.changing_lines:
            return None
        return get_hexagram(self.cast.resulting_hexagram_number)


def _describe(consultation: AnyConsultation) -> _Record:
    if isinstance(consultation, Consultation):
        return _Record(
            consultation=consultation,
            question=consultation.question,
            status_value=consultation.status.value,
            card_id=consultation.card_draw.card_id if consultation.card_draw else None,
            cast=consultation.cast,
            context=consultation.interpretation_context,
            citations=list(consultation.retrieved_citations),
            result=consultation.result,
            provider_id=consultation.provider_id,
            model_id=consultation.model_id,
        )
    if isinstance(consultation, OracleConsultation):
        return _Record(
            consultation=consultation,
            question=consultation.question,
            status_value=consultation.status.value,
            card_id=consultation.card_draw.card_id if consultation.card_draw else None,
            context=consultation.interpretation_context,
            citations=list(consultation.retrieved_citations),
            result=consultation.result,
            provider_id=consultation.provider_id,
            model_id=consultation.model_id,
            legacy_note="HISTORICAL RITE — a card alone, with no cast",
        )
    return _Record(
        consultation=consultation,
        question=consultation.question,
        status_value=consultation.status.value,
        cast=consultation.cast,
        context=consultation.interpretation_context,
        result=consultation.result,
        provider_id=consultation.provider_id,
        model_id=consultation.model_id,
        legacy_note="HISTORICAL RITE — a cast alone, with no card",
    )


class ConsultationResultScreen(SyzygyScreen):
    #: The screen owns its own reveal (`reveal_consultation`); the default
    #: region entry would animate the card and the lines twice.
    SCREEN_TRANSITIONS = False

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

    def __init__(self, consultation: AnyConsultation, *, interpret: bool = True) -> None:
        super().__init__()
        self.consultation = consultation
        self.record = _describe(consultation)
        # A legacy record can never be advanced, whatever the caller asks
        # for (ADR 0008 section 7).
        self._may_interpret = interpret and not self.record.is_legacy
        self._interpreting = False
        self._view = ConsultationView.ANSWER

    # -- composition ------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield TitleBar(self.record.question.consultation_local_date)
        with Horizontal(id="consultation-columns"):
            with Vertical(id="consultation-aside"):
                yield TarotCardWidget(glyphs=self.syzygy.glyphs, id="consultation-card")
                with Vertical(id="consultation-cast"):
                    yield Static("", id="consultation-hexagram", classes="lede")
                    with Vertical(id="consultation-lines"):
                        pass
                    yield Static("", id="consultation-movement", classes="muted")
            with Vertical(id="consultation-main"):
                if self.record.legacy_note is not None:
                    yield Static(self.record.legacy_note, id="consultation-legacy")
                yield Static(
                    "THE CONSULTATION IS FIXED.", id="consultation-title", classes="lede"
                )
                yield Static(
                    f"“{self.record.question.text}”",
                    id="consultation-question",
                    classes="muted",
                )
                yield VerticalScroll(
                    Static("", id="consultation-body"), id="consultation-panel"
                )
        yield Static("", id="consultation-keys", classes="keys", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self._render_chance()
        self._show()
        if self._may_interpret and self.record.status_value not in (
            ConsultationStatus.COMPLETE.value,
            ConsultationStatus.INTERPRETING.value,
        ):
            self._begin_interpretation()

    def _render_chance(self) -> None:
        """Put both objects on screen, then reveal card-first, lines upward."""
        card_widget = self.query_one("#consultation-card", TarotCardWidget)
        if self.record.card_id is not None:
            card_widget.set_card(get_card(self.record.card_id))

        cast = self.record.cast
        primary = self.record.primary_hexagram
        heading = self.query_one("#consultation-hexagram", Static)
        movement = self.query_one("#consultation-movement", Static)
        if cast is None or primary is None:
            heading.update("no cast — this rite predates the two-object Oracle")
            movement.update("")
            return

        # The ground names itself on one line; where it is going belongs
        # with the movement note, which is the row that answers "is
        # anything moving at all?" - the aside is narrow, and one long
        # wrapping label answers neither question cleanly.
        heading.update(f"{primary.unicode}  {primary.number}. {primary.name}")
        movement.update(movement_note(cast, self.record.resulting_hexagram))

        container = self.query_one("#consultation-lines", Vertical)
        # Mounted top line first, which is how a hexagram is read; the
        # reveal walks the same widgets in the order a cast is made.
        bottom_up: list[Static] = []
        for line in reversed(cast.lines):
            widget = Static(LINE_GLYPHS[line], classes="cast-line")
            container.mount(widget)
            bottom_up.insert(0, widget)
        self.syzygy.animations.reveal_consultation(card_widget, bottom_up, self._revealed)

    def _revealed(self) -> None:
        """The reveal is presentation only; nothing about it is load-bearing."""

    # -- state ------------------------------------------------------------

    def _interrupted(self) -> bool:
        return (
            self.record.status_value == ConsultationStatus.INTERPRETING.value
            and not self._interpreting
        )

    def _may_retry(self) -> bool:
        return (
            self._may_interpret
            and not self._interpreting
            and (
                self.record.status_value
                == ConsultationStatus.INTERPRETATION_FAILED.value
                or self._interrupted()
            )
        )

    def _show(self) -> None:
        result = self.record.result
        text = Text()
        heading = f"bold {palette.ACCENT}"
        body = palette.BONE
        muted = palette.MUTED
        if result is None and self._interpreting:
            text.append("INTERPRETATION IN PROGRESS…\n", style=muted)
        elif result is None:
            # The rite survives a failed interpretation: the question, the
            # card, and the cast are all still on screen beside this.
            text.append("THE CONSULTATION IS FIXED.\n", style=heading)
            text.append(
                "The card and the cast are committed and will not change.\n", style=muted
            )
            text.append(
                "INTERPRETATION WAS INTERRUPTED.\n"
                if self._interrupted()
                else "INTERPRETATION IS UNAVAILABLE.\n",
                style=f"bold {palette.EMBER}",
            )
            if self._may_interpret:
                text.append(
                    "\n[R] Retry  [F] use offline fixture  [M] configure model\n", style=body
                )
        elif self._view is ConsultationView.ANSWER:
            text.append("RESPONSE\n\n", style=heading)
            text.append(result.question_response, style=body)
        elif self._view is ConsultationView.ESOTERIC:
            text.append("ESOTERIC\n\n", style=heading)
            text.append(f"{result.esoteric.summary}\n\n{result.esoteric.body}", style=body)
        elif self._view is ConsultationView.CONVENTIONAL:
            text.append("CONVENTIONAL\n\n", style=heading)
            text.append(
                f"{result.conventional.summary}\n\n{result.conventional.body}\n", style=body
            )
            if result.conventional.watch_for:
                text.append("\nWATCH FOR\n", style=heading)
                for item in result.conventional.watch_for:
                    text.append(f"• {item}\n", style=body)
            text.append("\nREFLECT\n", style=heading)
            text.append(result.conventional.reflection, style=body)
        else:
            self._append_inputs(text, heading, body, muted)
        self.query_one("#consultation-body", Static).update(text)
        self.query_one("#consultation-title", Static).update(
            result.alignment_title if result is not None else "THE CONSULTATION IS FIXED."
        )
        keys = "[A] ANSWER   [1] ESOTERIC   [2] CONVENTIONAL   [I] INPUTS"
        if self._may_retry():
            keys += "   [R] RETRY   [F] FIXTURE   [M] MODEL"
        self.query_one("#consultation-keys", Static).update(keys + "   [Q] QUIT")

    def _append_inputs(self, text: Text, heading: str, body: str, muted: str) -> None:
        record = self.record
        context = record.context
        text.append("INPUTS\n\n", style=heading)
        if context is None:
            text.append("No interpretation context was committed.\n", style=muted)
            return
        text.append("QUESTION (USER TEXT)\n", style=heading)
        text.append(f"  {record.question.text}\n", style=body)

        primary = record.primary_hexagram
        if record.cast is not None and primary is not None:
            cast = record.cast
            text.append("\nTHE GROUND (FIXED, BOTTOM LINE FIRST)\n", style=heading)
            text.append(
                f"  values: {' '.join(str(int(line)) for line in cast.lines)}\n", style=body
            )
            text.append(
                f"  hexagram: {primary.number}. {primary.name} {primary.unicode}\n", style=body
            )
            text.append(f"  {movement_note(cast)}\n", style=body)
            resulting = record.resulting_hexagram
            if resulting is not None:
                text.append(
                    f"  resulting: {resulting.number}. {resulting.name} "
                    f"{resulting.unicode}\n",
                    style=body,
                )
            text.append("\nLEGGE 1882 CITATIONS\n", style=heading)
            text.append(
                f"  Judgment pp. {primary.citation.text_pages}; "
                f"Image pp. {primary.citation.image_pages}\n",
                style=body,
            )
            if resulting is not None:
                text.append(
                    f"  resulting Judgment pp. {resulting.citation.text_pages}; "
                    f"Image pp. {resulting.citation.image_pages}\n",
                    style=body,
                )

        if context.card is not None:
            text.append("\nTHE FIGURE (FIXED, UPRIGHT)\n", style=heading)
            text.append(f"  {context.card.full_name} ({context.card.id})\n", style=body)
            # M18's two lists, unchanged: what was sent, then where the
            # card is discussed. A citation-only chunk never reaches a
            # provider and appears only in the second list.
            text.append("\nPASSAGES SENT TO THE MODEL\n", style=heading)
            if context.knowledge_chunks:
                for chunk in context.knowledge_chunks:
                    text.append(
                        f"  {chunk.title} (pages {chunk.page_start}-{chunk.page_end})\n",
                        style=body,
                    )
            else:
                text.append(
                    f"  none.\n  {NO_PASSAGES_NOTE}\n  {NO_PASSAGES_ACTION}\n", style=muted
                )
            text.append("\nWHERE THIS CARD IS DISCUSSED\n", style=heading)
            if record.citations:
                for citation in record.citations:
                    text.append(f"  {citation.reference}\n", style=body)
            else:
                text.append("  no citations were recorded.\n", style=muted)

        text.append("\nPROVENANCE\n", style=heading)
        text.append(f"  provider: {record.provider_id or '—'}\n", style=body)
        text.append(f"  model: {record.model_id or '—'}\n", style=body)
        text.append(f"  prompt version: {context.prompt_version}\n", style=body)
        if record.is_legacy:
            text.append(
                "  this record predates the two-object Oracle and cannot be re-run\n",
                style=muted,
            )

    # -- interpretation ---------------------------------------------------

    def _begin_interpretation(self, provider=None) -> None:
        self._interpreting = True
        self._show()
        self._interpret(provider)

    @work(exclusive=True, group="consultation-interpret")
    async def _interpret(self, provider=None) -> None:
        services = self.syzygy.services
        selected_provider = provider or services.provider
        consultation = self.consultation
        assert isinstance(consultation, Consultation)
        try:
            self.consultation = await interpret_consultation(
                services.conn, consultation, services.clock, selected_provider
            )
        except Exception:
            latest = consultations.get_by_id(services.conn, consultation.id)
            if latest is not None:
                self.consultation = latest
        self.record = _describe(self.consultation)
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

    # -- views ------------------------------------------------------------

    def action_view_answer(self) -> None:
        self._view = ConsultationView.ANSWER
        self._show()

    def action_view_esoteric(self) -> None:
        self._view = ConsultationView.ESOTERIC
        self._show()

    def action_view_conventional(self) -> None:
        self._view = ConsultationView.CONVENTIONAL
        self._show()

    def action_view_inputs(self) -> None:
        self._view = ConsultationView.INPUTS
        self._show()

    def action_back(self) -> None:
        self.app.pop_screen()
