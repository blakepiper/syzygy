"""The guided local-model wizard (M16.9).

One routed screen over `syzygy.local_models.orchestrator.LocalSetupSession`.
Everything this file knows how to do is *render* a step and *hand a
decision back*; it contains no platform detection, no HTTP, no subprocess
management, and no policy about what is safe to install. That all lives in
`syzygy.local_models`, which is why the same flow drives `syzygy model
setup-local` with no Textual involved.

Three rules the layout obeys, from M16.9b and M16.9e:

* **One primary action per step**, plus Back and Cancel. The primary
  action is always the first button and is always reachable by ENTER.
* **Long work runs in a Textual worker.** The event loop keeps pumping, so
  animation, input, and the theme are never blocked - and every long step
  reports progress, because a frozen screen is indistinguishable from a
  crash.
* **Nothing is conveyed by colour alone.** Every state that is coloured is
  also worded: "Ready", "Not compatible", "Needs 11.9 GB, 7.4 GB
  available".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Footer, Label, ListItem, ListView, ProgressBar, Static

from syzygy.tui.screens.base import SyzygyScreen, TitleBar

if TYPE_CHECKING:
    from syzygy.local_models.contracts import ModelArtifact, SetupFailure
    from syzygy.local_models.orchestrator import LocalSetupSession

#: The plain-language explanation M16's terminology section requires,
#: shown before any jargon and before anything is downloaded.
INTRO_TEXT = (
    "Syzygy can run the model that writes your readings on this computer, "
    "instead of sending them to a company's servers.\n\n"
    "Two things get downloaded, once:\n\n"
    "  · the MODEL - a large language file, a few gigabytes;\n"
    "  · the RUNNER - a small program that loads the model and answers "
    "Syzygy locally.\n\n"
    "After that, everything stays here: your chart, your card, and the "
    "words written about them never leave this machine.\n\n"
    "How good and how fast it is depends on this computer's memory and "
    "graphics. Syzygy will look, tell you what it found, and show you "
    "exactly what it proposes to download before anything happens.\n\n"
    "You can stop at any point. The ritual still works without a model - "
    "it just uses demonstration text instead of a real interpretation."
)


@dataclass
class _Progress:
    """What the current long step is doing, for the progress line."""

    label: str
    done: int = 0
    total: int | None = None
    determinate: bool = False


class ArtifactItem(ListItem):
    def __init__(self, artifact: ModelArtifact, label: str, *, selectable: bool) -> None:
        super().__init__(Label(label, markup=False))
        self.artifact_id = artifact.id
        self.selectable = selectable
        if not selectable:
            # Disabled *and* worded: the label already says why.
            self.disabled = True


class LocalSetupScreen(SyzygyScreen):
    """`[M] → Set up a local model for me`."""

    BINDINGS = [
        ("escape", "back", "back"),
        ("d", "copy_diagnostics", "diagnostics"),
        ("t", "toggle_technical", "technical details"),
    ]

    def __init__(self, session: LocalSetupSession | None = None) -> None:
        super().__init__()
        self._session = session
        self._progress: _Progress | None = None
        self._cancelled = False
        self._show_technical = False
        self._message = ""

    # -- composition ---------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield TitleBar("LOCAL MODEL")
        with VerticalScroll(id="setup-body"):
            yield Static("", id="setup-step", classes="section-heading")
            yield Static("", id="setup-lede", classes="lede")
            yield Static("", id="setup-detail", markup=False)
            with Vertical(id="setup-progress", classes="hidden"):
                yield Static("", id="setup-progress-label", classes="muted")
                yield ProgressBar(id="setup-progress-bar", show_eta=False)
            yield ListView(id="setup-choices", classes="hidden")
            yield Static("", id="setup-technical", classes="muted hidden", markup=False)
        # Outside the scroll region: the action row and the status line must
        # never fall below the fold, at any supported terminal size (M16.9e).
        yield Static("", id="setup-message", classes="muted", markup=False)
        with Horizontal(id="setup-actions", classes="button-row"):
            yield Button("CONTINUE", id="setup-primary", variant="success")
            yield Button("BACK", id="setup-back")
            yield Button("CANCEL", id="setup-cancel")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh()

    # -- session -------------------------------------------------------------

    @property
    def session(self) -> LocalSetupSession:
        if self._session is None:
            from syzygy.config import default_app_paths
            from syzygy.local_models.orchestrator import LocalSetupSession
            from syzygy.local_models.paths import LocalModelPaths

            paths = default_app_paths()
            self._session = LocalSetupSession(
                paths=LocalModelPaths.from_app_paths(paths),
                settings_path=self.syzygy.services.settings_path or paths.settings_path,
            )
        return self._session

    # -- rendering -----------------------------------------------------------

    def _refresh(self) -> None:
        from syzygy.local_models.state import STATE_LABELS, SetupState

        session = self.session
        state = session.state
        self.query_one("#setup-step", Static).update(STATE_LABELS[state])
        self.query_one("#setup-message", Static).update(self._message)
        self._refresh_progress()

        renderer = {
            SetupState.INTRO: self._render_intro,
            SetupState.INVENTORY: self._render_inventory,
            SetupState.DISCOVERY: self._render_discovery,
            SetupState.RECOMMEND: self._render_recommend,
            SetupState.CONSENT: self._render_consent,
            SetupState.RUNTIME: self._render_working,
            SetupState.MODEL: self._render_working,
            SetupState.START: self._render_working,
            SetupState.VERIFY: self._render_working,
            SetupState.COMPLETE: self._render_complete,
            SetupState.FAILED: self._render_failed,
            SetupState.CANCELLED: self._render_cancelled,
        }[state]
        renderer()

    def _set(self, lede: str, detail: str = "") -> None:
        self.query_one("#setup-lede", Static).update(lede)
        self.query_one("#setup-detail", Static).update(detail)

    def _buttons(self, primary: str | None, *, back: bool = True, cancel: bool = True) -> None:
        primary_button = self.query_one("#setup-primary", Button)
        primary_button.display = primary is not None
        if primary is not None:
            primary_button.label = primary
        self.query_one("#setup-back", Button).display = back
        self.query_one("#setup-cancel", Button).display = cancel

    def _choices(self, rows: list[ArtifactItem] | None) -> None:
        listing = self.query_one("#setup-choices", ListView)
        listing.clear()
        if not rows:
            listing.add_class("hidden")
            return
        listing.remove_class("hidden")
        for row in rows:
            listing.append(row)
        listing.index = 0

    def _technical(self, text: str) -> None:
        panel = self.query_one("#setup-technical", Static)
        panel.update(text)
        panel.set_class(not (self._show_technical and bool(text)), "hidden")

    def _refresh_progress(self) -> None:
        container = self.query_one("#setup-progress")
        if self._progress is None:
            container.add_class("hidden")
            return
        container.remove_class("hidden")
        label = self.query_one("#setup-progress-label", Static)
        bar = self.query_one("#setup-progress-bar", ProgressBar)

        if self._progress.determinate and self._progress.total:
            from syzygy.local_models.diagnostics import format_bytes

            bar.display = True
            bar.update(total=self._progress.total, progress=self._progress.done)
            share = 100 * self._progress.done / self._progress.total
            label.update(
                f"{self._progress.label}  {format_bytes(self._progress.done)}"
                f" of {format_bytes(self._progress.total)}  ({share:.0f}%)"
            )
            return

        # Indeterminate. With motion reduced or off, an animated bar is
        # replaced by a plain sentence that still says work is happening
        # (M16.9e) - never a spinner nobody asked for.
        from syzygy.tui.animation.motion import MotionLevel

        animated = self.syzygy.animations.motion.level is MotionLevel.FULL
        bar.display = animated
        if animated:
            bar.update(total=None)
        label.update(f"{self._progress.label} …")

    # -- steps ---------------------------------------------------------------

    def _render_intro(self) -> None:
        self._set("What this does", INTRO_TEXT)
        self._choices(None)
        self._technical("")
        self._buttons("CHECK THIS COMPUTER", back=False)

    def _render_inventory(self) -> None:
        assessment = self.session.assessment
        if assessment is None:
            self._set("Looking at this computer…", "")
            self._buttons(None, back=False)
            return
        self._set(assessment.headline, assessment.detail)
        self._technical(
            "\n".join(f"{label}: {value}" for label, value in assessment.facts)
            + "\n\n[T] hides this again. [D] copies it, with usernames, paths, and\n"
            "hostnames removed."
        )
        self._choices(None)
        self._buttons("LOOK FOR WHAT I ALREADY HAVE")

    def _render_discovery(self) -> None:
        report = self.session.discovery
        if report is None:
            self._set("Looking for a model runner you already have…", "")
            self._buttons(None)
            return

        endpoint = report.usable_endpoint
        binary = report.usable_binary
        if endpoint is not None:
            self._set(
                "Something compatible is already running here.",
                f"{endpoint.candidate.locator}\n"
                f"Model: {', '.join(endpoint.model_ids) or 'unnamed'}\n\n"
                "Syzygy can use it as it is - nothing will be downloaded or "
                "installed. It will run one short check first, to be sure it can "
                "write a reading in the exact shape Syzygy needs.",
            )
            self._buttons("USE THIS SERVER")
        elif binary is not None:
            self._set(
                "A model runner is already installed.",
                f"{binary.candidate.locator}\n{binary.next_action}\n\n"
                "Syzygy will use it as it is and won't modify it. It still needs a "
                "model file to load.",
            )
            self._buttons("CHOOSE A MODEL")
        else:
            self._set(
                "Nothing usable is set up yet.",
                "That's normal. Syzygy will suggest a model that suits this "
                "computer, and show you exactly what it proposes to download "
                "before anything happens.",
            )
            self._buttons("CHOOSE A MODEL")

        rows = [
            f"{item.candidate.locator} — {item.compatibility.value}: {item.next_action}"
            for item in (*report.endpoints, *report.binaries)
        ]
        self._technical("\n".join(rows) or "Nothing found.")
        self._choices(None)

    def _render_recommend(self) -> None:
        from syzygy.local_models.contracts import FitVerdict
        from syzygy.local_models.diagnostics import format_bytes

        recommendation = self.session.recommendation
        if recommendation is None:
            self._set("Working out what suits this computer…")
            self._buttons(None)
            return
        if recommendation.artifact is None:
            self._set("No model Syzygy offers will run here.", recommendation.rationale)
            self._choices(None)
            self._buttons(None)
            return

        chosen = self.session.chosen or recommendation.artifact
        pairs = [(recommendation.artifact, recommendation.fit), *recommendation.alternatives]
        rows: list[ArtifactItem] = []
        for artifact, fit in sorted(pairs, key=lambda pair: pair[0].size_bytes):
            if fit is None:
                continue
            selectable = fit.verdict is not FitVerdict.INSUFFICIENT_DISK
            marker = "▸ " if artifact.id == chosen.id else "  "
            tier = (artifact.tier.value.replace("_", " ") if artifact.tier else "other").upper()
            speed = _speed_words(fit)
            state = "" if selectable else "  — NOT ENOUGH DISK SPACE"
            rows.append(
                ArtifactItem(
                    artifact,
                    f"{marker}{tier}: {artifact.display_name}\n"
                    f"    download {format_bytes(artifact.size_bytes)}"
                    f" · memory about {format_bytes(fit.required_memory_bytes)}"
                    f" · {speed}\n"
                    f"    {fit.reason}{state}",
                    selectable=selectable,
                )
            )
        self._choices(rows)
        self._set(
            f"Recommended: {recommendation.artifact.display_name}",
            f"Why this model? {recommendation.rationale}\n\n"
            f"Confidence: {recommendation.confidence}. Everything stays on this "
            "computer once it's downloaded.\n\n"
            "Pick a different one with the arrow keys and ENTER, or continue with "
            "the recommendation.",
        )
        self._technical(_technical_details(chosen))
        self._buttons("REVIEW WHAT WILL HAPPEN")

    def _render_consent(self) -> None:
        from syzygy.local_models.diagnostics import format_bytes

        receipt = self.session.consent_receipt
        if receipt is None:
            self._set("Preparing…")
            self._buttons(None)
            return

        lines = ["Syzygy will:"]
        lines += [f"  {index + 1}. {action}" for index, action in enumerate(receipt.actions)]
        lines.append("")
        lines.append("It will contact:")
        lines += [f"  · {url}\n      ({why})" for url, why in receipt.network_contacts] or [
            "  · nothing - everything needed is already here"
        ]
        lines.append("")
        lines.append("It will write:")
        lines += [f"  · {path}  ({format_bytes(size)})" for path, size in receipt.files_written]
        lines.append("")
        lines.append(f"Total download: {format_bytes(receipt.total_download_bytes)}")
        lines.append(f"Disk used when finished: {format_bytes(receipt.total_disk_bytes)}")
        lines.append(f"Network exposure: {receipt.local_port_note}")
        if receipt.license_id:
            lines.append("")
            lines.append(f"Licence: {receipt.license_id} — {receipt.license_url}")
            lines.append("Continuing accepts those terms for this model.")

        self._set("Nothing has been downloaded yet.", "\n".join(lines))
        self._choices(None)
        self._technical(_technical_details(self.session.chosen))
        self._buttons("YES, DO THIS")

    def _render_working(self) -> None:
        from syzygy.local_models.state import STATE_LABELS

        self._set(STATE_LABELS[self.session.state], "")
        self._choices(None)
        self._buttons(None, back=False)

    def _render_complete(self) -> None:
        settings = self.session.summary()
        model = settings.model.path if settings.model else "an existing server"
        self._set(
            "Ready. Readings will use the local model from now on.",
            f"Model: {model}\n\n"
            "Syzygy starts the model when it needs it and stops it when you quit - "
            "there's nothing to run yourself.\n\n"
            "The first reading of a session takes a little longer, because the "
            "model has to be loaded into memory.",
        )
        self._choices(None)
        self._buttons("DONE", back=False, cancel=False)

    def _render_failed(self) -> None:
        failure = self.session.failure
        if failure is None:
            self._set("Setup didn't finish.")
            self._buttons("TRY AGAIN")
            return
        self._set(failure.message, _recovery_text(failure))
        self._technical(failure.detail or "No further detail.")
        self._choices(None)
        self._buttons("TRY AGAIN" if failure.retryable else None)

    def _render_cancelled(self) -> None:
        self._set(
            "Setup cancelled. Nothing was switched over.",
            "Anything already downloaded has been kept, so starting again won't "
            "re-download it. Readings continue to use whatever was active before.",
        )
        self._choices(None)
        self._buttons("START AGAIN", back=False, cancel=False)

    # -- actions -------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "setup-primary":
            self._advance()
        elif event.button.id == "setup-back":
            self.action_back()
        elif event.button.id == "setup-cancel":
            self._cancel()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if isinstance(item, ArtifactItem) and item.selectable:
            self.session.choose(item.artifact_id)
            self._refresh()

    def _advance(self) -> None:
        from syzygy.local_models.state import SetupState

        state = self.session.state
        if state is SetupState.INTRO:
            self._start_inventory()
        elif state is SetupState.INVENTORY:
            self._start_discovery()
        elif state is SetupState.DISCOVERY:
            self._after_discovery()
        elif state is SetupState.RECOMMEND:
            self._prepare_consent()
        elif state is SetupState.CONSENT:
            self._begin_acquisition()
        elif state in (SetupState.COMPLETE, SetupState.CANCELLED):
            self._leave()
        elif state is SetupState.FAILED:
            self._retry()

    def _cancel(self) -> None:
        self._cancelled = True
        self.session.cancel()
        self._progress = None
        self._message = ""
        self._refresh()

    def action_back(self) -> None:
        from syzygy.local_models.state import SetupState

        state = self.session.state
        previous = {
            SetupState.INVENTORY: SetupState.INTRO,
            SetupState.DISCOVERY: SetupState.INVENTORY,
            SetupState.RECOMMEND: SetupState.DISCOVERY,
            SetupState.CONSENT: SetupState.RECOMMEND,
        }.get(state)
        if previous is None:
            self._leave()
            return
        self.session.move_to(previous)
        self._refresh()

    def _leave(self) -> None:
        if len(self.app.screen_stack) > 1:
            self.app.pop_screen()

    def action_toggle_technical(self) -> None:
        self._show_technical = not self._show_technical
        self._refresh()

    def action_copy_diagnostics(self) -> None:
        """Put the redacted report where the user can paste it.

        Also written to a file: a terminal's clipboard integration is not
        guaranteed, and a path that definitely exists beats a copy that
        may silently not have happened.
        """
        report = self.session.diagnostics()
        try:
            self.app.copy_to_clipboard(report)
        except Exception:  # noqa: BLE001 - clipboard support is optional
            pass
        target = self.session.paths.logs_dir / "diagnostics.txt"
        try:
            self.session.paths.ensure_exists()
            target.write_text(report, encoding="utf-8")
            self._message = f"Diagnostics copied, and written to {target}."
        except OSError as exc:
            self._message = f"Diagnostics copied. Could not write a file: {exc}"
        self._refresh()

    def _retry(self) -> None:
        from syzygy.local_models.state import SetupState

        self._cancelled = False
        self.session.move_to(SetupState.INTRO)
        self._refresh()

    # -- workers -------------------------------------------------------------

    def _begin(self, label: str) -> None:
        self._progress = _Progress(label=label)
        self._message = ""
        self._refresh()

    @work(thread=True, exclusive=True, group="local-setup")
    def _start_inventory(self) -> None:
        self.app.call_from_thread(self._begin, "Checking memory, disk, and graphics")
        try:
            self.session.run_inventory()
        except Exception as exc:  # noqa: BLE001 - never crash the wizard
            self.app.call_from_thread(self._step_failed, exc)
            return
        self.app.call_from_thread(self._step_finished)

    @work(thread=True, exclusive=True, group="local-setup")
    def _start_discovery(self) -> None:
        self.app.call_from_thread(self._begin, "Checking this computer's own ports")
        try:
            self.session.run_discovery()
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(self._step_failed, exc)
            return
        self.app.call_from_thread(self._step_finished)

    def _after_discovery(self) -> None:
        report = self.session.discovery
        if report is not None and report.usable_endpoint is not None:
            self.session.use_existing_endpoint(report.usable_endpoint)
            self._start_verification()
            return
        self.session.build_recommendation()
        self._refresh()

    def _prepare_consent(self) -> None:
        from syzygy.local_models.orchestrator import SetupStepError

        try:
            self.session.prepare_consent()
        except SetupStepError as exc:
            self.session.fail(exc.failure)
        self._refresh()

    def _begin_acquisition(self) -> None:
        self.session.accept_terms()
        self._cancelled = False
        self._run_acquisition()

    @work(thread=True, exclusive=True, group="local-setup")
    def _run_acquisition(self) -> None:
        """Install, download, start, verify - each with its own
        cancellation boundary (M16.9d): cancelling the model download does
        not undo an already-installed runner."""
        from syzygy.local_models.download import DownloadCancelled
        from syzygy.local_models.orchestrator import SetupStepError

        try:
            self.app.call_from_thread(self._begin, "Downloading the model runner")
            self.session.install_runtime(
                on_progress=self._on_progress, cancel=lambda: self._cancelled
            )

            self.app.call_from_thread(self._begin, "Downloading the model")
            self.session.fetch_model(
                on_progress=self._on_progress, cancel=lambda: self._cancelled
            )

            self.app.call_from_thread(self._begin, "Starting the model")
            self.session.start_server(
                on_phase=self._on_phase, cancel=lambda: self._cancelled
            )

            self.app.call_from_thread(self._begin, "Checking it can write a reading")
            self.session.verify_and_activate()
        except DownloadCancelled:
            self.app.call_from_thread(self._cancel)
            return
        except SetupStepError as exc:
            self.app.call_from_thread(self.session.fail, exc.failure)
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(self._step_failed, exc)
            return
        self.app.call_from_thread(self._step_finished)

    @work(thread=True, exclusive=True, group="local-setup")
    def _start_verification(self) -> None:
        self.app.call_from_thread(self._begin, "Checking it can write a reading")
        try:
            self.session.verify_and_activate()
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(self._step_failed, exc)
            return
        self.app.call_from_thread(self._step_finished)

    def _on_progress(self, done: int, total: int | None) -> None:
        self.app.call_from_thread(self._update_progress, done, total)

    def _on_phase(self, phase, text: str) -> None:
        self.app.call_from_thread(self._begin, text.rstrip("… "))

    def _update_progress(self, done: int, total: int | None) -> None:
        if self._progress is None or not self.is_mounted:
            return
        self._progress.done = done
        self._progress.total = total
        self._progress.determinate = total is not None
        self._refresh_progress()

    def _step_finished(self) -> None:
        self._progress = None
        if self.is_mounted:
            self._refresh()

    def _step_failed(self, exc: BaseException) -> None:
        from syzygy.local_models.contracts import FailureKind, RecoveryAction, SetupFailure
        from syzygy.local_models.diagnostics import redact

        self._progress = None
        self.session.fail(
            SetupFailure(
                kind=FailureKind.PROCESS_CRASHED,
                message="Something went wrong during setup.",
                detail=redact(f"{type(exc).__name__}: {exc}"),
                actions=(RecoveryAction.RETRY, RecoveryAction.COPY_DIAGNOSTICS),
            )
        )
        if self.is_mounted:
            self._refresh()


# -- copy helpers ------------------------------------------------------------


def _speed_words(fit) -> str:
    from syzygy.local_models.contracts import Backend, FitVerdict

    if fit.verdict is FitVerdict.INSUFFICIENT_MEMORY:
        return "too large for this computer"
    if fit.backend is Backend.CPU:
        return "slow (processor only)"
    if fit.verdict is FitVerdict.TIGHT:
        return "workable, not fast"
    return "fast"


def _technical_details(artifact: ModelArtifact | None) -> str:
    """The jargon, behind `[T]` - never on the happy path (M16.9c)."""
    if artifact is None:
        return ""
    from syzygy.local_models.fit import SYZYGY_CONTEXT_TOKENS

    return (
        f"artifact       {artifact.id}\n"
        f"repository     {artifact.repository}\n"
        f"revision       {artifact.revision}\n"
        f"file           {artifact.filename}\n"
        f"sha256         {artifact.sha256}\n"
        f"quantization   {artifact.quantization} ({artifact.parameter_class})\n"
        f"format         GGUF, served by llama.cpp over its OpenAI-compatible API\n"
        f"context        {SYZYGY_CONTEXT_TOKENS} tokens, "
        f"{artifact.max_output_tokens} max output\n"
        f"min runtime    llama.cpp b{artifact.min_runtime_build}\n"
        f"support        {artifact.support_status.value}\n"
        f"kv cache       {artifact.memory_profile.kv_cache_bytes} bytes "
        f"({artifact.memory_profile.kv_cache_provenance.value})\n"
        f"overhead       {artifact.memory_profile.runtime_overhead_bytes} bytes "
        f"({artifact.memory_profile.runtime_overhead_provenance.value})\n"
        f"profile source {artifact.memory_profile.source}"
    )


def _recovery_text(failure: SetupFailure) -> str:
    from syzygy.local_models.contracts import RecoveryAction

    words = {
        RecoveryAction.RETRY: "[ENTER] try again",
        RecoveryAction.CHOOSE_SMALLER: "[ESC] go back and choose a smaller model",
        RecoveryAction.USE_EXISTING_SERVER: (
            "run a model server yourself and use Advanced / existing server"
        ),
        RecoveryAction.COPY_DIAGNOSTICS: "[D] copy diagnostics",
        RecoveryAction.SKIP_FOR_NOW: "[ESC] leave it for now - the ritual still works",
        RecoveryAction.OPEN_LICENSE: "read the licence linked above",
        RecoveryAction.FREE_DISK_SPACE: "free some disk space, then try again",
        RecoveryAction.REPAIR: "use Repair local model from the model screen",
    }
    lines = [words[action] for action in failure.actions if action in words]
    body = "\n".join(f"  · {line}" for line in lines)
    return (
        f"{body}\n\nYour readings are unaffected: nothing was switched over, and "
        "any card already drawn is untouched.\n\n[T] shows the technical detail."
    )
