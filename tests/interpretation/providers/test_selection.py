"""Tests for provider selection persistence and resolution
(the "wiring" that lets `default_services`/the CLI pick a real provider
instead of always defaulting to `FixtureProvider`).

The real OS keyring is never touched - the two cases that would reach it
(openai/anthropic with no key) are exercised through an unrecognized
provider id and a missing model id instead, which fail the same way
(`ProviderBuildError`) without needing a keyring fake.
"""

from __future__ import annotations

import pytest

from syzygy.interpretation.providers.fixture import FixtureProvider
from syzygy.interpretation.providers.llama_cpp import LlamaCppProvider
from syzygy.interpretation.providers.selection import (
    ProviderBuildError,
    ProviderSelection,
    build_provider,
    clear_selection,
    load_selection,
    resolve_selected_provider,
    save_selection,
)


def test_load_selection_returns_none_when_no_file_exists(tmp_path):
    assert load_selection(tmp_path / "settings.json") is None


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "nested" / "settings.json"
    selection = ProviderSelection(provider_id="llama_cpp", model_id="local-test")

    save_selection(path, selection)
    loaded = load_selection(path)

    assert loaded == selection


def test_load_selection_tolerates_a_corrupt_file(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("not json")
    assert load_selection(path) is None


def test_clear_selection_is_safe_when_nothing_is_saved(tmp_path):
    clear_selection(tmp_path / "settings.json")  # must not raise


def test_clear_selection_removes_a_saved_file(tmp_path):
    path = tmp_path / "settings.json"
    save_selection(path, ProviderSelection(provider_id="fixture"))
    clear_selection(path)
    assert load_selection(path) is None


def test_build_provider_fixture():
    provider = build_provider(ProviderSelection(provider_id="fixture"))
    assert isinstance(provider, FixtureProvider)


def test_build_provider_llama_cpp_defaults_model_id():
    provider = build_provider(ProviderSelection(provider_id="llama_cpp"))
    assert isinstance(provider, LlamaCppProvider)
    assert provider.model_id == "local"


def test_build_provider_llama_cpp_honors_overrides():
    provider = build_provider(
        ProviderSelection(
            provider_id="llama_cpp", model_id="my-model", base_url="http://example.local/v1"
        )
    )
    assert isinstance(provider, LlamaCppProvider)
    assert provider.model_id == "my-model"


def test_build_provider_openai_requires_a_model_id():
    with pytest.raises(ProviderBuildError, match="model id"):
        build_provider(ProviderSelection(provider_id="openai"))


def test_build_provider_anthropic_requires_a_model_id():
    with pytest.raises(ProviderBuildError, match="model id"):
        build_provider(ProviderSelection(provider_id="anthropic"))


def test_build_provider_rejects_an_unknown_provider_id():
    with pytest.raises(ProviderBuildError, match="unknown provider"):
        build_provider(ProviderSelection(provider_id="bogus"))


def test_resolve_selected_provider_with_no_selection_is_fixture_and_quiet():
    provider, reason = resolve_selected_provider(None)
    assert isinstance(provider, FixtureProvider)
    assert reason is None


def test_resolve_selected_provider_falls_back_with_a_reason_on_failure():
    provider, reason = resolve_selected_provider(ProviderSelection(provider_id="bogus"))
    assert isinstance(provider, FixtureProvider)
    assert reason is not None and "bogus" in reason


def test_resolve_selected_provider_returns_the_built_provider_on_success():
    provider, reason = resolve_selected_provider(
        ProviderSelection(provider_id="llama_cpp", model_id="local-test")
    )
    assert isinstance(provider, LlamaCppProvider)
    assert reason is None
