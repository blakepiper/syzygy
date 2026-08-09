"""Which `InterpretationProvider` a reading actually uses (Milestone 7
wiring, docs/old/IMPLEMENTATION_PLAN.md §7.3's "adding a new provider" note).

This is deliberately not part of `syzygy.domain` - it is application
configuration, not a fact about a reading, and it lives in a small local
JSON file (`AppPaths.settings_path`) rather than the SQLite database. It
holds only a provider id, an optional model id, and an optional local
`base_url`: never an API key (those stay in the OS keyring - see
`api_keys.py`) and never anything from `syzygy.domain.reading`.

`resolve_selected_provider` is the one function callers (the TUI's
`default_services`, the CLI) should use. It never raises: a selected
hosted provider with no resolvable key, an unreachable local server
setting, or a corrupt/missing settings file all fall back to
`FixtureProvider` rather than blocking the ritual (docs/old/DESIGN.md Milestone 5 /
docs/old/ARCHITECTURE_HANDOFF.md §34 - the app must stay usable with no model
configured). The fallback reason is returned as a string, not printed
here, because printing is a caller's job, not this module's.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from pydantic import BaseModel

from syzygy.interpretation.base import InterpretationProvider
from syzygy.interpretation.providers.api_keys import MissingAPIKeyError
from syzygy.interpretation.providers.fixture import FixtureProvider
from syzygy.settings import PROVIDER_SECTION, load_document, save_document, save_section

FIXTURE_PROVIDER_ID: Final = "fixture"
LLAMA_CPP_PROVIDER_ID: Final = "llama_cpp"
OPENAI_PROVIDER_ID: Final = "openai"
ANTHROPIC_PROVIDER_ID: Final = "anthropic"

#: Every id `syzygy model use` and `resolve_selected_provider` accept.
SELECTABLE_PROVIDER_IDS: Final = (
    FIXTURE_PROVIDER_ID,
    LLAMA_CPP_PROVIDER_ID,
    OPENAI_PROVIDER_ID,
    ANTHROPIC_PROVIDER_ID,
)

#: Provider ids whose selection sends the interpretation context off the
#: local machine (docs/old/DESIGN.md §13.3) - a caller presenting `model use` to a
#: person must disclose this before the first real call.
HOSTED_PROVIDER_IDS: Final = (OPENAI_PROVIDER_ID, ANTHROPIC_PROVIDER_ID)


class ProviderSelection(BaseModel):
    """The persisted choice. `model_id` is required for every provider
    except `fixture` (checked in `build_provider`, not here, so an
    invalid selection written by hand still loads and reports a clear
    fallback reason instead of failing to parse)."""

    provider_id: str
    model_id: str | None = None
    base_url: str | None = None


class ProviderBuildError(RuntimeError):
    """The selected provider could not be constructed - missing model id,
    missing API key, or an unrecognized provider id. Always caught inside
    `resolve_selected_provider`; only raised by `build_provider` for
    callers (tests, `syzygy model use`) that want the real error instead
    of a silent fixture fallback."""


def load_selection(path: Path) -> ProviderSelection | None:
    """`None` if nothing has been selected yet, or the file is missing or
    unreadable - never raises.

    Reads both shapes of the settings file. Before M15 the selection *was*
    the whole document (`{"provider_id": ...}`); it now lives under a
    `"provider"` key so other preferences can share the file. The legacy
    form is still accepted so an existing install does not silently lose
    its configured provider on upgrade.
    """
    document = load_document(path)
    if not document:
        return None

    section = document.get(PROVIDER_SECTION)
    if not isinstance(section, dict):
        section = document if "provider_id" in document else None
    if section is None:
        return None

    try:
        return ProviderSelection.model_validate(section)
    except ValueError:
        return None


def save_selection(path: Path, selection: ProviderSelection) -> None:
    save_section(path, PROVIDER_SECTION, selection.model_dump())


def clear_selection(path: Path) -> None:
    """Revert to no selection (`resolve_selected_provider` then always
    returns `FixtureProvider`). Safe to call if nothing was ever saved.

    Removes the provider section rather than the file: other subsystems
    keep their preferences there now.
    """
    save_section(path, PROVIDER_SECTION, None)
    # A legacy flat document has no section to remove - its keys *are* the
    # selection, so they have to go individually.
    document = load_document(path)
    if "provider_id" in document:
        for key in ("provider_id", "model_id", "base_url"):
            document.pop(key, None)
        save_document(path, document)


def build_provider(selection: ProviderSelection) -> InterpretationProvider:
    """Construct the provider `selection` names. Raises `ProviderBuildError`
    rather than returning a degraded provider - see
    `resolve_selected_provider` for the fallback-to-fixture wrapper every
    other caller should use instead of this directly."""
    if selection.provider_id == FIXTURE_PROVIDER_ID:
        return FixtureProvider()

    if selection.provider_id == LLAMA_CPP_PROVIDER_ID:
        from syzygy.interpretation.providers.llama_cpp import DEFAULT_BASE_URL, LlamaCppProvider

        return LlamaCppProvider(
            model_id=selection.model_id or "local",
            base_url=selection.base_url or DEFAULT_BASE_URL,
        )

    if selection.provider_id == OPENAI_PROVIDER_ID:
        from syzygy.interpretation.providers.openai import DEFAULT_BASE_URL, OpenAIProvider

        if not selection.model_id:
            raise ProviderBuildError("openai selection has no model id")
        try:
            return OpenAIProvider(
                model_id=selection.model_id,
                base_url=selection.base_url or DEFAULT_BASE_URL,
            )
        except MissingAPIKeyError as exc:
            raise ProviderBuildError(str(exc)) from exc

    if selection.provider_id == ANTHROPIC_PROVIDER_ID:
        from syzygy.interpretation.providers.anthropic import (
            DEFAULT_BASE_URL,
            AnthropicProvider,
        )

        if not selection.model_id:
            raise ProviderBuildError("anthropic selection has no model id")
        try:
            return AnthropicProvider(
                model_id=selection.model_id,
                base_url=selection.base_url or DEFAULT_BASE_URL,
            )
        except MissingAPIKeyError as exc:
            raise ProviderBuildError(str(exc)) from exc

    raise ProviderBuildError(f"unknown provider id {selection.provider_id!r}")


def resolve_selected_provider(
    selection: ProviderSelection | None,
) -> tuple[InterpretationProvider, str | None]:
    """The provider a reading should actually use, plus a human-readable
    reason if it had to fall back to `FixtureProvider`.

    Never raises. `selection is None` (nothing ever chosen) is the quiet,
    reason-less case - everything else that prevents building the chosen
    provider is reported so the caller can surface it (a stderr warning
    from the CLI, eventually a TUI banner) rather than silently
    downgrading a reading the user thought was real.
    """
    if selection is None:
        return FixtureProvider(), None
    try:
        return build_provider(selection), None
    except ProviderBuildError as exc:
        return FixtureProvider(), str(exc)
