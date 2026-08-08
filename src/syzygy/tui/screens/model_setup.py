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
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Footer, Input, Label, ListItem, ListView, Static

from syzygy.tui.screens.base import SyzygyScreen, TitleBar

#: Hosted providers need a separately-billed API key (DESIGN.md 13.2/13.3).
#: `llama_cpp` needs none, and `fixture` needs nothing at all.
_HOSTED_PROVIDER_LABELS = {"openai": "OpenAI", "anthropic": "Anthropic"}
_HOSTED_ENV_VARS = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}


@dataclass
class ProviderStatus:
    """What `_load_status` learns about the local environment - enough to
    render every row without any further I/O."""

    active_provider_id: str
    active_model_id: str | None
    fallback_reason: str | None
    llama_cpp_reachable: bool
    #: "keyring", "env", or `None` (no key found anywhere) - mirrors
    #: `syzygy model status`'s three-way distinction.
    openai_key_source: str | None
    anthropic_key_source: str | None


def _key_source(provider_id: str) -> str | None:
    import os

    from syzygy.interpretation.providers.api_keys import has_stored_api_key

    if has_stored_api_key(provider_id):
        return "keyring"
    if os.environ.get(_HOSTED_ENV_VARS[provider_id]):
        return "env"
    return None


def load_status() -> ProviderStatus:
    """Synchronous, blocking (keyring + a local HTTP probe) - callers must
    run this off the event loop."""
    import asyncio

    from syzygy.config import default_app_paths
    from syzygy.interpretation.providers import llama_cpp
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

    return ProviderStatus(
        active_provider_id=active_provider_id,
        active_model_id=active_model_id,
        fallback_reason=fallback_reason,
        llama_cpp_reachable=asyncio.run(llama_cpp.probe()),
        openai_key_source=_key_source("openai"),
        anthropic_key_source=_key_source("anthropic"),
    )


class ProviderListItem(ListItem):
    def __init__(self, provider_id: str, label: str) -> None:
        super().__init__(Label(label, markup=False))
        self.provider_id = provider_id


class ModelSetupScreen(SyzygyScreen):
    """List providers, show live status, select one. Hosted providers
    reveal a small key-entry form instead of selecting immediately."""

    BINDINGS = [("escape", "back", "back")]

    def __init__(self) -> None:
        super().__init__()
        self._status: ProviderStatus | None = None
        self._key_form_provider_id: str | None = None

    def compose(self) -> ComposeResult:
        yield TitleBar("MODEL")
        with VerticalScroll(id="model-body"):
            yield Static(
                "Readings use whichever provider is active. Fixture needs no\n"
                "setup and never leaves this machine. OpenAI and Anthropic need a\n"
                "separate, separately-billed API key - never a ChatGPT/Claude Pro\n"
                "login, which no third-party app can use.",
                classes="muted",
            )
            yield Static("", id="model-active", classes="muted")
            yield ListView(id="model-list")
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
            yield Static("", id="model-message", classes="muted")
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
        reachable = "reachable" if status.llama_cpp_reachable else "not reachable"
        listing.append(
            ProviderListItem(
                "llama_cpp", f"LLAMA.CPP — {reachable}, no API key needed{marker('llama_cpp')}"
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
        self._select_local_provider(item.provider_id)

    def _select_local_provider(self, provider_id: str) -> None:
        """`fixture` or `llama_cpp` - no key needed, select immediately."""
        from syzygy.interpretation.providers.selection import (
            FIXTURE_PROVIDER_ID,
            ProviderBuildError,
            ProviderSelection,
            build_provider,
            clear_selection,
            save_selection,
        )

        settings_path = self._settings_path()
        message = self.query_one("#model-message", Static)

        if provider_id == FIXTURE_PROVIDER_ID:
            clear_selection(settings_path)
            message.update("Active provider set to fixture.")
            self._refresh_status()
            return

        selection = ProviderSelection(provider_id=provider_id)
        try:
            build_provider(selection)
        except ProviderBuildError as exc:
            # Saved anyway, matching `syzygy model use`: fixing the
            # underlying problem (starting llama-server) shouldn't require
            # reopening this screen too.
            message.update(
                f"warning: {exc}\nSelection saved, but readings will use fixture until "
                "this is fixed."
            )
            save_selection(settings_path, selection)
            self._refresh_status()
            return

        save_selection(settings_path, selection)
        message.update(f"Active provider set to {provider_id}.")
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
        if event.button.id == "cancel-key":
            self._close_key_form()
        elif event.button.id == "save-key":
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
            "provider sends today's reading context to its servers on every reading "
            "from now on."
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
        if len(self.app.screen_stack) > 1:
            self.app.pop_screen()
