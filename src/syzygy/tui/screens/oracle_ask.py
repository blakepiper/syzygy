"""Ask and commit an Oracle question before turning the wheel."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Horizontal, Vertical
from textual.widgets import Button, Footer, Input, Static

from syzygy.domain.iching_consultation import IChingConsultation
from syzygy.domain.oracle import MAX_QUESTION_LENGTH, OracleConsultation
from syzygy.sortes.entropy import EntropyCollector
from syzygy.storage.oracle_service import ask_question
from syzygy.tui.screens.base import SyzygyScreen, TitleBar


class OracleAskScreen(SyzygyScreen):
    BINDINGS = [("escape", "back", "back")]

    def __init__(self) -> None:
        super().__init__()
        # One collector follows this consultation through the question and
        # wheel. Production always uses the default OS-random source.
        self._collector = EntropyCollector()
        self._submitting = False

    def compose(self) -> ComposeResult:
        yield TitleBar("THE ORACLE")
        with Vertical(id="oracle-ask-body"):
            yield Static("Ask one question. Choose one oracle.", classes="lede")
            yield Static(
                "Your question is stored locally and sent only to your selected interpreter. "
                "You will turn the wheel once; the card or six-line cast remains fixed even "
                "if interpretation fails.",
                classes="muted",
            )
            yield Input(
                placeholder="What are you trying to see more clearly?",
                max_length=MAX_QUESTION_LENGTH,
                id="oracle-question",
            )
            yield Static(f"0 / {MAX_QUESTION_LENGTH}", id="oracle-budget", classes="muted")
            yield Static("", id="oracle-error", classes="error")
            with Center(), Horizontal(id="oracle-mode-buttons"):
                yield Button("THOTH CARD", id="oracle-submit", variant="primary")
                yield Button("I CHING", id="iching-submit")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#oracle-question", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "oracle-question":
            # Input owns its key events; its value-change message is the
            # reliable observation point. The event kind contains no text.
            self._collector.record("question-keystroke")
            self.query_one("#oracle-budget", Static).update(
                f"{len(event.value)} / {MAX_QUESTION_LENGTH}"
            )

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "oracle-submit":
            self._submit("tarot")
        elif event.button.id == "iching-submit":
            self._submit("iching")

    def _submit(self, mode: str = "tarot") -> None:
        if self._submitting or self.syzygy.profile is None:
            return
        question = self.query_one("#oracle-question", Input).value
        consultation: IChingConsultation | OracleConsultation
        try:
            if mode == "iching":
                from syzygy.storage.iching_service import ask_question as ask_iching

                consultation = ask_iching(
                    self.syzygy.services.conn,
                    self.syzygy.profile,
                    self.syzygy.services.clock,
                    question,
                )
            else:
                consultation = ask_question(
                    self.syzygy.services.conn,
                    self.syzygy.profile,
                    self.syzygy.services.clock,
                    question,
                )
        except ValueError as exc:
            self.query_one("#oracle-error", Static).update(str(exc))
            self.app.bell()
            return
        self._submitting = True
        from syzygy.tui.screens.wheel import WheelScreen

        self.app.push_screen(WheelScreen(consultation, collector=self._collector))

    def action_back(self) -> None:
        self.app.pop_screen()
