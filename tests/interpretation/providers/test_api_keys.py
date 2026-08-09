"""Tests for hosted-provider API key resolution (docs/old/DESIGN.md §13.3).

The real OS keyring is never touched here - a tiny in-memory fake stands
in for `keyring.get_password`/`set_password`/`delete_password`, so these
tests are deterministic on any machine (including one with no keyring
backend configured at all) and never write a real credential.
"""

from __future__ import annotations

import keyring.errors
import pytest

from syzygy.interpretation.providers import api_keys


@pytest.fixture(autouse=True)
def fake_keyring(monkeypatch):
    store: dict[tuple[str, str], str] = {}

    def fake_get_password(service: str, username: str) -> str | None:
        return store.get((service, username))

    def fake_set_password(service: str, username: str, password: str) -> None:
        store[(service, username)] = password

    def fake_delete_password(service: str, username: str) -> None:
        if (service, username) not in store:
            raise keyring.errors.PasswordDeleteError("not found")
        del store[(service, username)]

    monkeypatch.setattr(api_keys.keyring, "get_password", fake_get_password)
    monkeypatch.setattr(api_keys.keyring, "set_password", fake_set_password)
    monkeypatch.setattr(api_keys.keyring, "delete_password", fake_delete_password)
    return store


def test_resolve_prefers_keyring_over_environment(monkeypatch):
    monkeypatch.setenv("FAKE_API_KEY", "from-env")
    api_keys.store_api_key("fake", "from-keyring")

    assert api_keys.resolve_api_key("fake", "FAKE_API_KEY") == "from-keyring"


def test_resolve_falls_back_to_environment(monkeypatch):
    monkeypatch.setenv("FAKE_API_KEY", "from-env")

    assert api_keys.resolve_api_key("fake", "FAKE_API_KEY") == "from-env"


def test_resolve_raises_when_neither_is_set(monkeypatch):
    monkeypatch.delenv("FAKE_API_KEY", raising=False)

    with pytest.raises(api_keys.MissingAPIKeyError):
        api_keys.resolve_api_key("fake", "FAKE_API_KEY")


def test_has_stored_api_key_reflects_the_keyring_only(monkeypatch):
    monkeypatch.setenv("FAKE_API_KEY", "from-env")
    assert api_keys.has_stored_api_key("fake") is False

    api_keys.store_api_key("fake", "from-keyring")
    assert api_keys.has_stored_api_key("fake") is True


def test_delete_api_key_is_safe_when_nothing_is_stored():
    api_keys.delete_api_key("fake")  # must not raise


def test_delete_api_key_removes_a_stored_key():
    api_keys.store_api_key("fake", "from-keyring")
    api_keys.delete_api_key("fake")
    assert api_keys.has_stored_api_key("fake") is False


def test_providers_do_not_share_a_keyring_namespace():
    api_keys.store_api_key("openai", "openai-key")
    with pytest.raises(api_keys.MissingAPIKeyError):
        api_keys.resolve_api_key("anthropic", "NONEXISTENT_ENV_VAR")
