"""In-TUI model provider setup (M10.4).

`syzygy model status|configure|use` (`syzygy.cli`) already do the real
work - this screen is TUI plumbing around that existing machinery
(`syzygy.interpretation.providers.selection`, `.api_keys`, `.llama_cpp`),
not new provider-selection or key-storage logic. Selecting a provider
calls `selection.build_provider`/`save_selection` exactly like `model
use`; storing a hosted provider's key calls `api_keys.store_api_key`
exactly like `model configure`.

Scoping note, kept visible in the UI copy: there is no "log in with your
ChatGPT/Claude subscription" flow here, and it isn't a gap to fix -
OpenAI and Anthropic don't expose their consumer subscription auth to
third-party apps at all. The only credential either accepts from an app
like Syzygy is a separate, separately-billed API key - this screen says
"API key", never "subscription".
"""

from __future__ import annotations

from dataclasses import dataclass

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Input, ListView, Static

from syzygy.tui.screens.base import FormScroll, SyzygyScreen, TitleBar
from syzygy.tui.widgets.marked_list import MarkedListItem

#: Hosted providers need a separately-billed API key (docs/old/DESIGN.md 13.2/13.3).
#: `llama_cpp` needs none, and `fixture` needs nothing at all.
_HOSTED_PROVIDER_LABELS = {"openai": "OpenAI", "anthropic": "Anthropic"}
_HOSTED_ENV_VARS = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}

#: Shown when `llama-server` isn't answering. "Not reachable" on its own
#: tells the user what is wrong but not what to do about it (M11.3c).
LLAMA_CPP_HELP = (
    "Start a local server, then probe again:\n"
    "    llama-server -m /path/to/model.gguf --port 8080\n"
    "Syzygy talks to its OpenAI-compatible /v1 route. Any endpoint that\n"
    "speaks that API works - point BASE URL at it."
)


@dataclass
class ProviderStatus:
    """What `_load_status` learns about the local environment - enough to
    render every row without any further I/O."""

    active_provider_id: str
    active_model_id: str | None
    fallback_reason: str | None
    llama_cpp_reachable: bool
    #: The base URL that was actually probed - the saved one if a
    #: `llama_cpp` selection has one, otherwise the localhost default.
    #: Rendered in the row so "not reachable" says *where* it looked.
    llama_cpp_base_url: str
    #: "keyring", "env", or `None` (no key found anywhere) - mirrors
    #: `syzygy model status`'s three-way distinction.
    openai_key_source: str | None
    anthropic_key_source: str | None
    #: One line about the managed local model, or `None` if none is set
    #: up. When `local_model_needs_repair` is set, the local row becomes a
    #: repair route rather than a setup one (M16.8d).
    local_model_summary: str | None = None
    local_model_needs_repair: bool = False


def _key_source(provider_id: str) -> str | None:
    import os

    from syzygy.interpretation.providers.api_keys import has_stored_api_key

    if has_stored_api_key(provider_id):
        return "keyring"
    if os.environ.get(_HOSTED_ENV_VARS[provider_id]):
        return "env"
    return None


def probe_llama_cpp(base_url: str) -> bool:
    """Blocking reachability check for `base_url` - callers must run this
    off the event loop. Wraps the same `llama_cpp.probe` coroutine
    `syzygy model status` uses; nothing here knows how to probe on its
    own.

    `llama_cpp.probe` already returns `False` for any `httpx.HTTPError`,
    but a base URL the user typed by hand can be malformed enough that
    httpx raises before any request happens. "Could not even try" is the
    same answer as "nothing there" for this screen's purposes, and it must
    not take the status load down with it.
    """
    import asyncio

    from syzygy.interpretation.providers import llama_cpp

    try:
        return asyncio.run(llama_cpp.probe(base_url))
    except Exception:
        return False


def default_llama_cpp_base_url() -> str:
    """The URL a `llama_cpp` selection would actually use: the saved
    `base_url` if there is one, otherwise the localhost default."""
    from syzygy.config import default_app_paths
    from syzygy.interpretation.providers.llama_cpp import DEFAULT_BASE_URL
    from syzygy.interpretation.providers.selection import LLAMA_CPP_PROVIDER_ID, load_selection

    selection = load_selection(default_app_paths().settings_path)
    if selection is not None and selection.provider_id == LLAMA_CPP_PROVIDER_ID:
        return selection.base_url or DEFAULT_BASE_URL
    return DEFAULT_BASE_URL


def local_model_state() -> tuple[str | None, bool]:
    """`(summary, needs_repair)` for the managed local model.

    Never raises: this runs on a status screen, and a local-model
    subsystem that cannot answer must not take the screen down with it.
    """
    try:
        from syzygy.config import default_app_paths
        from syzygy.local_models.catalog import load_catalog
        from syzygy.local_models.settings import load_local_model_settings
        from syzygy.local_models.verification import validate_managed_configuration

        settings_path = default_app_paths().settings_path
        settings = load_local_model_settings(settings_path)
        if settings.mode is None:
            return None, False

        health = validate_managed_configuration(
            settings_path, catalog_version=load_catalog().catalog_version
        )
        if health.healthy:
            model = settings.model.artifact_id if settings.model else None
            return f"Local model ready ({model or 'external server'}).", False
        return f"Local model needs repair: {health.reason}.", True
    except Exception as exc:  # noqa: BLE001
        return f"Local model status unavailable: {type(exc).__name__}: {exc}", True


def load_status() -> ProviderStatus:
    """Synchronous, blocking (keyring + a local HTTP probe) - callers must
    run this off the event loop."""
    from syzygy.config import default_app_paths
    from syzygy.interpretation.providers.selection import (
        FIXTURE_PROVIDER_ID,
        load_selection,
        resolve_selected_provider,
    )

    settings_path = default_app_paths().settings_path
    selection = load_selection(settings_path)
    if selection is None:
        active_provider_id, active_model_id, fallback_reason = FIXTURE_PROVIDER_ID, None, None
    else:
        _, fallback_reason = resolve_selected_provider(selection)
        active_provider_id, active_model_id = selection.provider_id, selection.model_id

    base_url = default_llama_cpp_base_url()
    local_summary, needs_repair = local_model_state()
    return ProviderStatus(
        active_provider_id=active_provider_id,
        active_model_id=active_model_id,
        fallback_reason=fallback_reason,
        llama_cpp_reachable=probe_llama_cpp(base_url),
        llama_cpp_base_url=base_url,
        openai_key_source=_key_source("openai"),
        anthropic_key_source=_key_source("anthropic"),
        local_model_summary=local_summary,
        local_model_needs_repair=needs_repair,
    )


class ProviderListItem(MarkedListItem):
    def __init__(self, provider_id: str, label: str) -> None:
        super().__init__(label)
        self.provider_id = provider_id


class ModelSetupScreen(SyzygyScreen):
    """List providers, show live status, select one. Hosted providers
    reveal a small key-entry form instead of selecting immediately."""

    BINDINGS = [
        ("escape", "back", "back"),
        ("p", "probe", "probe again"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._status: ProviderStatus | None = None
        self._key_form_provider_id: str | None = None
        self._llama_form_open = False
        self._llama_choice_open = False

    def compose(self) -> ComposeResult:
        yield TitleBar("MODEL")
        with FormScroll(id="model-body"):
            yield Static(
                "Readings use whichever provider is active. Fixture needs no\n"
                "setup and never leaves this machine. OpenAI and Anthropic need a\n"
                "separate, separately-billed API key - never a ChatGPT/Claude Pro\n"
                "login, which no third-party app can use.",
                classes="muted",
            )
            yield Static("", id="model-active", classes="muted")
            # M16.8d: a managed local model that no longer validates gets a
            # visible route back, not a stderr line nobody sees. Readings
            # have already fallen back to fixture by the time this shows.
            yield Static("", id="model-local-state", classes="hidden", markup=False)
            yield ListView(id="model-list")
            # M16.9a: choosing "local model" used to drop the user straight
            # into a base-URL field, which is a question only somebody who
            # already runs a server can answer. The row now asks which of
            # the two situations they are in first.
            with Vertical(id="llama-choice", classes="hidden"):
                yield Static("LOCAL MODEL", classes="section-heading")
                yield Static(
                    "A local model runs on this computer, so your chart, your card,\n"
                    "and the words written about them never leave it.",
                    classes="muted",
                )
                with Horizontal(classes="button-row"):
                    yield Button(
                        "SET UP A LOCAL MODEL FOR ME",
                        id="llama-guided",
                        variant="success",
                    )
                    yield Button("USE AN EXISTING SERVER (ADVANCED)", id="llama-advanced")
                    yield Button("CANCEL", id="llama-choice-cancel")
                yield Static(
                    "Set up for me: Syzygy checks this computer, recommends a model,\n"
                    "shows you exactly what it would download, and only then asks.\n"
                    "Advanced: you already run an OpenAI-compatible server and want\n"
                    "to point Syzygy at it.",
                    classes="muted",
                )
            with Vertical(id="llama-form", classes="hidden"):
                yield Static("EXISTING SERVER (ADVANCED)", classes="section-heading")
                yield Static("BASE URL", classes="field-label")
                yield Input(placeholder="http://127.0.0.1:8080/v1", id="llama-base-url")
                yield Static("MODEL ID (OPTIONAL)", classes="field-label")
                yield Input(placeholder="local", id="llama-model-id")
                yield Static("", id="llama-probe-status")
                yield Static(LLAMA_CPP_HELP, id="llama-help", classes="muted")
                with Horizontal(classes="button-row"):
                    yield Button("USE", id="llama-use", variant="success")
                    yield Button("PROBE", id="llama-probe")
                    yield Button("CANCEL", id="llama-cancel")
            with Vertical(id="model-key-form", classes="hidden"):
                yield Static("", id="key-form-heading", classes="section-heading")
                yield Static("MODEL ID", classes="field-label")
                yield Input(placeholder="e.g. gpt-4o-mini", id="model-id-input")
                yield Static("API KEY", classes="field-label")
                yield Input(placeholder="", password=True, id="api-key-input")
                yield Static("", id="key-form-error", classes="error")
                with Horizontal(classes="button-row"):
                    yield Button("SAVE & USE", id="save-key", variant="success")
                    yield Button("CANCEL", id="cancel-key")
        # Outside the scroll region on purpose. This is the only line that
        # confirms a selection actually took effect, and inside
        # `#model-body` it sat below the fold on a standard-height
        # terminal - a confirmation nobody can see is indistinguishable
        # from the key doing nothing, which is half of what M11.3 was.
        # `markup=False`: it quotes provider errors verbatim, and "[P]"
        # would otherwise be swallowed as Rich markup.
        yield Static("", id="model-message", classes="muted", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_status()

    def on_screen_resume(self) -> None:
        super().on_screen_resume()
        self._refresh_status()

    # -- status -------------------------------------------------------------

    @work(thread=True, exclusive=True)
    def _refresh_status(self) -> None:
        try:
            status = load_status()
        except ImportError as exc:
            self.app.call_from_thread(self._status_unavailable, str(exc))
            return
        except Exception as exc:
            # A saved-but-malformed `base_url` makes the probe raise out of
            # httpx rather than returning False, and a status screen that
            # crashes is strictly worse than one that reports the problem.
            self.app.call_from_thread(self._status_unavailable, f"{type(exc).__name__}: {exc}")
            return
        self.app.call_from_thread(self._status_loaded, status)

    def _status_unavailable(self, reason: str) -> None:
        if not self.is_mounted:
            return
        self.query_one("#model-active", Static).update(
            f"Provider status unavailable: {reason} (install the `providers` extra)."
        )
        self.query_one("#model-list", ListView).clear()
        self.query_one("#model-list", ListView).append(
            ProviderListItem("fixture", "FIXTURE — no model, canned copy (active)")
        )

    def _status_loaded(self, status: ProviderStatus) -> None:
        if not self.is_mounted:
            return
        self._status = status
        active_label = status.active_provider_id
        if status.active_model_id:
            active_label += f" ({status.active_model_id})"
        if status.fallback_reason:
            active_label += f" - FALLING BACK TO FIXTURE: {status.fallback_reason}"
        self.query_one("#model-active", Static).update(f"Active provider: {active_label}")
        local_line = self.query_one("#model-local-state", Static)
        if status.local_model_summary is None:
            local_line.add_class("hidden")
        else:
            local_line.remove_class("hidden")
            local_line.update(status.local_model_summary)
            local_line.set_classes("error" if status.local_model_needs_repair else "ok")
        self._render_list(status)
        self.query_one("#model-list", ListView).focus()

    def _render_list(self, status: ProviderStatus) -> None:
        listing = self.query_one("#model-list", ListView)
        listing.clear()

        def marker(provider_id: str) -> str:
            return " (active)" if status.active_provider_id == provider_id else ""

        listing.append(
            ProviderListItem("fixture", f"FIXTURE — no model, canned copy{marker('fixture')}")
        )
        reachable = "reachable" if status.llama_cpp_reachable else "NOT reachable"
        listing.append(
            ProviderListItem(
                "llama_cpp",
                f"LLAMA.CPP — {reachable} at {status.llama_cpp_base_url}"
                f", no API key needed{marker('llama_cpp')}",
            )
        )
        for provider_id, label in _HOSTED_PROVIDER_LABELS.items():
            source = (
                status.openai_key_source
                if provider_id == "openai"
                else status.anthropic_key_source
            )
            key_state = {
                "keyring": "key stored",
                "env": f"key set via {_HOSTED_ENV_VARS[provider_id]}",
                None: "no key configured",
            }[source]
            listing.append(
                ProviderListItem(
                    provider_id, f"{label.upper()} — {key_state}{marker(provider_id)}"
                )
            )
        listing.index = 0

    # -- selection ------------------------------------------------------------

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if not isinstance(item, ProviderListItem):
            return
        if item.provider_id in _HOSTED_PROVIDER_LABELS:
            self._open_key_form(item.provider_id)
            return
        if item.provider_id == "llama_cpp":
            self._open_llama_choice()
            return
        self._select_fixture()

    # -- local model (M16.9a) --------------------------------------------------

    def _open_llama_choice(self) -> None:
        self._llama_choice_open = True
        status = self._status
        # The wizard re-runs inventory, discovery, and verification from
        # the top, which is exactly what repairing a broken managed setup
        # requires - so it is the same button, differently labelled.
        self.query_one("#llama-guided", Button).label = (
            "REPAIR LOCAL MODEL"
            if status is not None and status.local_model_needs_repair
            else "SET UP A LOCAL MODEL FOR ME"
        )
        self.query_one("#model-list", ListView).add_class("hidden")
        self.query_one("#llama-choice").remove_class("hidden")
        self.query_one("#llama-guided", Button).focus()

    def _close_llama_choice(self) -> None:
        self._llama_choice_open = False
        self.query_one("#llama-choice").add_class("hidden")
        self.query_one("#model-list", ListView).remove_class("hidden")
        self.query_one("#model-list", ListView).focus()

    def _open_guided_setup(self) -> None:
        """Hand over to the M16 wizard. Everything it does - inventory,
        recommendation, consent, download, start, verify - lives in
        `syzygy.local_models`; this screen only opens the door."""
        from syzygy.tui.screens.local_setup import LocalSetupScreen

        self._close_llama_choice()
        self.app.push_screen(LocalSetupScreen())

    def _select_fixture(self) -> None:
        from syzygy.interpretation.providers.selection import clear_selection

        clear_selection(self._settings_path())
        self.query_one("#model-message", Static).update(
            "Active provider set to fixture - readings use canned copy and "
            "nothing leaves this machine."
        )
        self._refresh_status()

    # -- llama.cpp (M11.3) -----------------------------------------------------

    def _open_llama_form(self) -> None:
        """The advanced route: point Syzygy at a server you already run.

        Selecting it used to save a selection and nothing else, which -
        with no server running - left the row still reading "not
        reachable" and gave the user nothing to act on (M11.3). The form
        below is the thing that was missing: which URL, is anything there,
        and how to start one if not.
        """
        self._llama_form_open = True
        status = self._status
        base_url = status.llama_cpp_base_url if status else ""
        self.query_one("#llama-base-url", Input).value = base_url
        already_selected = status is not None and status.active_provider_id == "llama_cpp"
        self.query_one("#llama-model-id", Input).value = (
            (status.active_model_id or "") if already_selected and status else ""
        )
        self._render_probe_status(status.llama_cpp_reachable if status else None, base_url)
        self.query_one("#model-list", ListView).add_class("hidden")
        self.query_one("#llama-form").remove_class("hidden")
        self.query_one("#llama-base-url", Input).focus()

    def _close_llama_form(self) -> None:
        self._llama_form_open = False
        self.query_one("#llama-form").add_class("hidden")
        self.query_one("#model-list", ListView).remove_class("hidden")
        self.query_one("#model-list", ListView).focus()

    def _render_probe_status(self, reachable: bool | None, base_url: str) -> None:
        """`None` means "probing right now" - every state says something,
        so a probe is never a silent no-op (M11.3b)."""
        line = self.query_one("#llama-probe-status", Static)
        help_text = self.query_one("#llama-help", Static)
        if reachable is None:
            line.update(f"Probing {base_url}…")
            line.set_classes("muted")
            return
        if reachable:
            line.update(f"A server answered at {base_url}.")
            line.set_classes("ok")
            help_text.add_class("hidden")
            return
        line.update(f"Nothing answered at {base_url}.")
        line.set_classes("error")
        help_text.remove_class("hidden")

    def _form_base_url(self) -> str:
        from syzygy.interpretation.providers.llama_cpp import DEFAULT_BASE_URL

        return self.query_one("#llama-base-url", Input).value.strip() or DEFAULT_BASE_URL

    def action_probe(self) -> None:
        """`[P]` from anywhere on this screen re-checks the local server -
        the whole point being that the answer changes once the user starts
        one, without having to leave and come back."""
        if self._key_form_provider_id is not None or self._llama_choice_open:
            return
        if self._llama_form_open:
            self._probe_now()
            return
        self.query_one("#model-message", Static).update("Probing the local server…")
        self._refresh_status()

    def _probe_now(self) -> None:
        base_url = self._form_base_url()
        self._render_probe_status(None, base_url)
        self._probe_worker(base_url)

    @work(thread=True, exclusive=True, group="llama-probe")
    def _probe_worker(self, base_url: str) -> None:
        self.app.call_from_thread(self._probe_finished, probe_llama_cpp(base_url), base_url)

    def _probe_finished(self, reachable: bool, base_url: str) -> None:
        if not self.is_mounted or not self._llama_form_open:
            return
        self._render_probe_status(reachable, base_url)

    def _use_llama_cpp(self) -> None:
        """Select llama.cpp, reachable or not.

        An unreachable server is *allowed*: it may be started later, and
        `syzygy model use` saves the same selection without checking. What
        must not happen is saving silently - the message says which of the
        two situations the user is now in (M11.3b).
        """
        from syzygy.interpretation.providers.llama_cpp import DEFAULT_BASE_URL
        from syzygy.interpretation.providers.selection import (
            LLAMA_CPP_PROVIDER_ID,
            ProviderBuildError,
            ProviderSelection,
            build_provider,
            save_selection,
        )

        base_url = self._form_base_url()
        model_id = self.query_one("#llama-model-id", Input).value.strip() or None
        selection = ProviderSelection(
            provider_id=LLAMA_CPP_PROVIDER_ID,
            model_id=model_id,
            # Only persist a non-default URL, so the saved settings don't
            # pin a default that may move.
            base_url=None if base_url == DEFAULT_BASE_URL else base_url,
        )

        message = self.query_one("#model-message", Static)
        try:
            build_provider(selection)
        except ProviderBuildError as exc:
            message.update(
                f"warning: {exc}\nSelection saved, but readings will use fixture until "
                "this is fixed."
            )
            save_selection(self._settings_path(), selection)
            self._close_llama_form()
            self._refresh_status()
            return

        save_selection(self._settings_path(), selection)
        self._close_llama_form()
        self._llama_use_probe(base_url)

    @work(thread=True, exclusive=True, group="llama-probe")
    def _llama_use_probe(self, base_url: str) -> None:
        """Re-probe after selecting, so the confirmation message can say
        whether readings will actually work right now."""
        self.app.call_from_thread(
            self._llama_use_finished, probe_llama_cpp(base_url), base_url
        )

    def _llama_use_finished(self, reachable: bool, base_url: str) -> None:
        if not self.is_mounted:
            return
        if reachable:
            text = f"Active provider set to llama_cpp at {base_url}."
        else:
            text = (
                f"Active provider set to llama_cpp at {base_url}, but nothing is "
                f"answering there yet. Start a server and press [P] to probe again - "
                f"readings fall back to fixture copy until it responds."
            )
        self.query_one("#model-message", Static).update(text)
        self._refresh_status()

    def _open_key_form(self, provider_id: str) -> None:
        self._key_form_provider_id = provider_id
        self.query_one("#key-form-heading", Static).update(
            f"{_HOSTED_PROVIDER_LABELS[provider_id]} API key"
        )
        self.query_one("#model-id-input", Input).value = ""
        self.query_one("#api-key-input", Input).value = ""
        self.query_one("#key-form-error", Static).update("")
        self.query_one("#model-list", ListView).add_class("hidden")
        self.query_one("#model-key-form").remove_class("hidden")
        self.query_one("#model-id-input", Input).focus()

    def _close_key_form(self) -> None:
        self._key_form_provider_id = None
        self.query_one("#model-key-form").add_class("hidden")
        self.query_one("#model-list", ListView).remove_class("hidden")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "llama-guided":
            self._open_guided_setup()
        elif event.button.id == "llama-advanced":
            self._close_llama_choice()
            self._open_llama_form()
        elif event.button.id == "llama-choice-cancel":
            self._close_llama_choice()
        elif event.button.id == "cancel-key":
            self._close_key_form()
        elif event.button.id == "save-key":
            self._save_key_and_use()
        elif event.button.id == "llama-cancel":
            self._close_llama_form()
        elif event.button.id == "llama-probe":
            self._probe_now()
        elif event.button.id == "llama-use":
            self._use_llama_cpp()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """ENTER in the base-URL field probes it - the natural thing to
        want after typing a URL, and it keeps the form usable without
        reaching for the buttons."""
        event.stop()
        if event.input.id == "llama-base-url":
            self._probe_now()
        elif event.input.id == "llama-model-id":
            self._use_llama_cpp()
        elif event.input.id in ("model-id-input", "api-key-input"):
            self._save_key_and_use()

    def _save_key_and_use(self) -> None:
        provider_id = self._key_form_provider_id
        if provider_id is None:
            return
        model_id = self.query_one("#model-id-input", Input).value.strip()
        api_key = self.query_one("#api-key-input", Input).value
        error = self.query_one("#key-form-error", Static)

        if not model_id:
            error.update("A model id is required (e.g. gpt-4o-mini).")
            return
        if not api_key:
            error.update("An API key is required.")
            return

        from syzygy.interpretation.providers.api_keys import store_api_key
        from syzygy.interpretation.providers.selection import (
            ProviderBuildError,
            ProviderSelection,
            build_provider,
            save_selection,
        )

        store_api_key(provider_id, api_key)
        settings_path = self._settings_path()
        selection = ProviderSelection(provider_id=provider_id, model_id=model_id)
        message = self.query_one("#model-message", Static)
        try:
            build_provider(selection)
        except ProviderBuildError as exc:
            message.update(
                f"warning: {exc}\nSelection saved, but readings will use fixture until "
                "this is fixed."
            )
            save_selection(settings_path, selection)
            self._close_key_form()
            self._refresh_status()
            return

        save_selection(settings_path, selection)
        message.update(
            f"Active provider set to {provider_id} ({model_id}). Selecting a hosted "
            "provider sends interpretation context — including an Oracle question when "
            "present — to its servers."
        )
        self._close_key_form()
        self._refresh_status()

    def _settings_path(self):
        from syzygy.config import default_app_paths

        return default_app_paths().settings_path

    def action_back(self) -> None:
        if self._key_form_provider_id is not None:
            self._close_key_form()
            return
        if self._llama_choice_open:
            self._close_llama_choice()
            return
        if self._llama_form_open:
            self._close_llama_form()
            return
        if len(self.app.screen_stack) > 1:
            self.app.pop_screen()
