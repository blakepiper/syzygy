"""Source material: what is installed, and how to install the rest (M18.1c).

Reached with `[K]` from home. Before this screen, the only route to
source passages was `syzygy knowledge ingest <pdf>` in `docs/`, which
made "no passages were sent" a dead end for anyone who never reads the
CLI reference - and that was the whole of the complaint M18 exists to
answer.

Two things this screen must not become. It **never downloads a book**:
Syzygy ships an index of where each card is discussed and nothing of what
those pages say (ADR 0003), and the user supplying their own copy is the
arrangement, not a limitation to route around. And it **refuses a file
whose hash is not a known edition** - every citation's page range is one
specific edition's pagination, so ingesting a different scan under the
same source would silently point every "pages 106-110" in the
application somewhere else. `syzygy knowledge ingest` stays available for
anyone who knows their copy differs and accepts that.

Domain logic stays out of here: state comes from
`syzygy.knowledge.status`, verification from
`syzygy.knowledge.ingest.verify_known_source_file`, and the work itself
from `syzygy.knowledge.ingest.ingest` on a Textual thread worker.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Footer, Input, Static

from syzygy.knowledge.status import (
    SourceState,
    SourceStatus,
    set_source_note_dismissed,
    source_statuses,
)
from syzygy.tui.screens.base import FormScroll, SyzygyScreen, TitleBar

if TYPE_CHECKING:
    # Type only: `syzygy.knowledge.ingest` imports pymupdf at module load,
    # and opening the interface must not pay for a PDF library nobody has
    # asked it to use yet.
    from syzygy.knowledge.ingest import IngestResult

#: What the three states read as in a list of sources. Citation-only is
#: phrased as the mode it is, never as a failure (M18.1d).
_STATE_LABELS = {
    SourceState.ABSENT: "not present",
    SourceState.CITATIONS_ONLY: "citations only",
    SourceState.FULL_TEXT: "full text — passages reach readings",
    SourceState.BROKEN: "needs attention",
}

INTRO = (
    "Syzygy ships an index of where each of the 78 cards is discussed in three\n"
    "books, and none of their text — those books are still under copyright.\n"
    "Point this screen at your own copy of one and its passages become part of\n"
    "your readings. Nothing is ever downloaded here."
)


class SourceMaterialScreen(SyzygyScreen):
    BINDINGS = [
        ("escape", "back", "back"),
        ("r", "refresh", "refresh"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._busy = False

    def compose(self) -> ComposeResult:
        yield TitleBar("SOURCE MATERIAL")
        with FormScroll(id="source-body"):
            yield Static(INTRO, classes="muted")
            yield Static("", id="source-list", markup=False)
            yield Static("INGEST A PDF", classes="section-heading")
            yield Static("", id="source-expected", classes="muted", markup=False)
            yield Static("PATH TO YOUR COPY", classes="field-label")
            yield Input(placeholder="~/books/book_of_thoth.pdf", id="source-path")
            with Horizontal(classes="button-row"):
                yield Button("INGEST", id="source-ingest", variant="success")
                yield Button("REFRESH", id="source-refresh")
                # Where home's note is switched off (M18.1d). It lives
                # here rather than as a second key on home because a
                # citation-only install is a supported state, and the
                # place to decide you have heard about it is the screen
                # that explains it.
                yield Button("HIDE THE HOME NOTE", id="source-dismiss")
        # Outside the scroll region: this is the line that says whether
        # anything happened, and it must not sit below the fold.
        yield Static("", id="source-message", classes="muted", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self._render_status()

    def on_screen_resume(self) -> None:
        super().on_screen_resume()
        self._render_status()

    # -- status ---------------------------------------------------------------

    def _render_status(self) -> None:
        statuses = source_statuses(self.syzygy.services.conn)
        self.query_one("#source-list", Static).update(_status_block(statuses))
        self.query_one("#source-expected", Static).update(
            "Auto-detected from the filename:\n"
            + "\n".join(f"  {status.expected_filename}" for status in statuses)
        )

    def action_refresh(self) -> None:
        self._render_status()

    # -- ingestion ------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "source-ingest":
            self._start_ingest()
        elif event.button.id == "source-refresh":
            self._render_status()
        elif event.button.id == "source-dismiss":
            self._dismiss_home_note()

    def _dismiss_home_note(self) -> None:
        settings_path = self.syzygy.services.settings_path
        message = self.query_one("#source-message", Static)
        if settings_path is None:
            message.update("This install has no settings file to remember that in.")
            return
        set_source_note_dismissed(settings_path, True)
        message.set_classes("muted")
        message.update("Home will stop mentioning this. Source material is always [K].")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._start_ingest()

    def _start_ingest(self) -> None:
        if self._busy:
            return
        raw = self.query_one("#source-path", Input).value.strip()
        message = self.query_one("#source-message", Static)
        if not raw:
            message.update("Type the path to a PDF you already have.")
            return
        path = Path(raw).expanduser()
        if not path.is_file():
            message.update(f"No such file: {path}")
            return
        self._busy = True
        self.query_one("#source-ingest", Button).disabled = True
        message.update(f"Checking {path.name}…")
        self._ingest_worker(path)

    @work(thread=True, exclusive=True, group="knowledge-ingest")
    def _ingest_worker(self, path: Path) -> None:
        """Verify, then ingest. Both are blocking and the second can take
        the better part of a minute on a 300-page scan, which is why this
        is a thread worker and why it reports phases as it goes."""
        from syzygy.clock import SystemClock
        from syzygy.knowledge.ingest import (
            SourceFileMismatchError,
            UnknownSourceTypeError,
            ingest,
            verify_known_source_file,
        )

        def progress(phase: str) -> None:
            self.app.call_from_thread(self._progress, f"{path.name}: {phase}…")

        try:
            source_type, _ = verify_known_source_file(path)
        except (UnknownSourceTypeError, SourceFileMismatchError) as exc:
            self.app.call_from_thread(self._ingest_failed, str(exc))
            return

        try:
            result = ingest(
                self.syzygy.services.conn,
                path,
                now=SystemClock().now_utc(),
                source_type=source_type,
                on_progress=progress,
            )
        except Exception as exc:  # noqa: BLE001 - a bad PDF must not crash the screen
            self.app.call_from_thread(
                self._ingest_failed, f"{type(exc).__name__}: {exc}"
            )
            return
        self.app.call_from_thread(self._ingest_finished, result)

    def _progress(self, text: str) -> None:
        if not self.is_mounted:
            return
        self.query_one("#source-message", Static).update(text)

    def _ingest_failed(self, reason: str) -> None:
        if not self.is_mounted:
            return
        self._finish_busy()
        message = self.query_one("#source-message", Static)
        message.set_classes("error")
        message.update(reason)
        self.syzygy.animations.trigger("error", message)

    def _ingest_finished(self, result: IngestResult) -> None:
        if not self.is_mounted:
            return
        self._finish_busy()
        message = self.query_one("#source-message", Static)
        message.set_classes("ok")
        if result.skipped:
            message.update(f"{result.source_type} was already ingested — nothing changed.")
        else:
            message.update(
                f"{result.source_type}: {result.chunk_count} passages across "
                f"{result.card_count} cards. Readings from now on carry them."
            )
        self._render_status()

    def _finish_busy(self) -> None:
        self._busy = False
        self.query_one("#source-ingest", Button).disabled = False

    def action_back(self) -> None:
        if len(self.app.screen_stack) > 1:
            self.app.pop_screen()


def _status_block(statuses: list[SourceStatus]) -> str:
    lines = []
    for status in statuses:
        tier = "canonical" if status.tier == 0 else "supplementary"
        line = f"  {status.title}  ({tier})\n    {_STATE_LABELS[status.state]}"
        if status.chunk_count:
            line += f", {status.chunk_count} chunks over {status.card_count} cards"
        if status.detail:
            line += f"\n    {status.detail}"
        lines.append(line)
    return "\n".join(lines)
