"""M10.4: in-TUI model provider onboarding.

`ModelSetupScreen` is plumbing around the existing CLI-only
`syzygy.interpretation.providers.selection`/`.api_keys`/`.llama_cpp`
machinery, so these tests isolate that machinery from the real machine
the same way `tests/interpretation/providers/test_api_keys.py` already
does: a fake in-memory keyring (never the real OS keyring) and a tmp
settings file (never the real `AppPaths.settings_path`), plus a mocked
`llama_cpp.probe` (never a real network call).
"""

from __future__ import annotations

import json

import keyring
import pytest
from textual.widgets import Button, Input, ListView, Static

from syzygy.config import AppPaths
from syzygy.tui.app import SyzygyApp
from syzygy.tui.screens.home import HomeScreen
from syzygy.tui.screens.model_setup import ModelSetupScreen
from syzygy.tui.screens.welcome import NO_MODEL_CONFIGURED_NUDGE, WelcomeScreen

from .test_ritual_flow import q, settle, text_of


@pytest.fixture
def fake_keyring(monkeypatch):
    store: dict[tuple[str, str], str] = {}

    def fake_get_password(service: str, username: str) -> str | None:
        return store.get((service, username))

    def fake_set_password(service: str, username: str, password: str) -> None:
        store[(service, username)] = password

    monkeypatch.setattr(keyring, "get_password", fake_get_password)
    monkeypatch.setattr(keyring, "set_password", fake_set_password)
    return store


@pytest.fixture
def fake_settings_path(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.json"
    fake_paths = AppPaths(
        data_dir=tmp_path,
        database_path=tmp_path / "syzygy.db",
        settings_path=settings_path,
        knowledge_dir=tmp_path / "knowledge",
        models_dir=tmp_path / "models",
        logs_dir=tmp_path / "logs",
    )
    monkeypatch.setattr("syzygy.config.default_app_paths", lambda: fake_paths)
    return settings_path


@pytest.fixture
def reachable_llama_cpp(monkeypatch):
    async def fake_probe(*args, **kwargs) -> bool:
        return True

    monkeypatch.setattr("syzygy.interpretation.providers.llama_cpp.probe", fake_probe)


@pytest.fixture(autouse=True)
def isolated_environment(fake_keyring, fake_settings_path, reachable_llama_cpp):
    """Every test in this file gets an isolated provider environment -
    no real keyring writes, no real network probe, no real settings file."""


def _saved_selection(settings_path) -> dict:
    return json.loads(settings_path.read_text())


async def test_home_screen_m_opens_model_setup(app: SyzygyApp, profile):
    async with app.run_test() as pilot:
        await settle(pilot)
        assert isinstance(pilot.app.screen, HomeScreen)

        await pilot.press("m")
        await settle(pilot)
        assert isinstance(pilot.app.screen, ModelSetupScreen)
        assert "Active provider: fixture" in text_of(q(pilot, "#model-active", Static))


async def test_welcome_screen_m_opens_model_setup(app: SyzygyApp):
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(pilot.app.screen, WelcomeScreen)

        await pilot.press("m")
        await settle(pilot)
        assert isinstance(pilot.app.screen, ModelSetupScreen)


async def test_welcome_shows_nudge_when_nothing_is_configured(app: SyzygyApp):
    async with app.run_test() as pilot:
        await settle(pilot)
        assert NO_MODEL_CONFIGURED_NUDGE in text_of(q(pilot, "#welcome-model-nudge", Static))


async def test_welcome_hides_nudge_once_a_provider_is_selected(
    app: SyzygyApp, fake_settings_path
):
    fake_settings_path.write_text(json.dumps({"provider_id": "llama_cpp", "model_id": None}))
    async with app.run_test() as pilot:
        await settle(pilot)
        assert text_of(q(pilot, "#welcome-model-nudge", Static)) == ""


async def test_selecting_llama_cpp_saves_the_selection(app: SyzygyApp, fake_settings_path):
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("m")
        await settle(pilot)
        assert isinstance(pilot.app.screen, ModelSetupScreen)

        listing = q(pilot, "#model-list", ListView)
        listing.index = 1  # fixture(0), llama_cpp(1), openai(2), anthropic(3)
        await pilot.pause()
        await pilot.press("enter")
        await settle(pilot)

        saved = _saved_selection(fake_settings_path)
        assert saved["provider_id"] == "llama_cpp"
        assert "Active provider set to llama_cpp" in text_of(q(pilot, "#model-message", Static))


async def test_configuring_openai_stores_the_key_and_saves_the_selection(
    app: SyzygyApp, fake_settings_path, fake_keyring
):
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("m")
        await settle(pilot)

        listing = q(pilot, "#model-list", ListView)
        listing.index = 2  # openai
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert not q(pilot, "#model-key-form").has_class("hidden")
        q(pilot, "#model-id-input", Input).value = "gpt-4o-mini"
        q(pilot, "#api-key-input", Input).value = "sk-test-key"
        q(pilot, "#save-key", Button).press()
        await settle(pilot)

        assert fake_keyring[("syzygy-openai", "api_key")] == "sk-test-key"
        saved = _saved_selection(fake_settings_path)
        assert saved["provider_id"] == "openai"
        assert saved["model_id"] == "gpt-4o-mini"


async def test_configuring_anthropic_stores_the_key_and_saves_the_selection(
    app: SyzygyApp, fake_settings_path, fake_keyring
):
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("m")
        await settle(pilot)

        listing = q(pilot, "#model-list", ListView)
        listing.index = 3  # anthropic
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        q(pilot, "#model-id-input", Input).value = "claude-test"
        q(pilot, "#api-key-input", Input).value = "sk-ant-test"
        q(pilot, "#save-key", Button).press()
        await settle(pilot)

        assert fake_keyring[("syzygy-anthropic", "api_key")] == "sk-ant-test"
        saved = _saved_selection(fake_settings_path)
        assert saved["provider_id"] == "anthropic"
        assert saved["model_id"] == "claude-test"


async def test_saving_a_key_without_a_model_id_shows_an_inline_error(
    app: SyzygyApp, fake_settings_path
):
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("m")
        await settle(pilot)

        listing = q(pilot, "#model-list", ListView)
        listing.index = 2  # openai
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        q(pilot, "#api-key-input", Input).value = "sk-test-key"
        q(pilot, "#save-key", Button).press()
        await pilot.pause()

        assert "model id is required" in text_of(q(pilot, "#key-form-error", Static))
        assert not fake_settings_path.exists()


async def test_cancel_returns_to_the_provider_list(app: SyzygyApp):
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("m")
        await settle(pilot)

        listing = q(pilot, "#model-list", ListView)
        listing.index = 2  # openai
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert not q(pilot, "#model-key-form").has_class("hidden")

        q(pilot, "#cancel-key", Button).press()
        await pilot.pause()
        assert q(pilot, "#model-key-form").has_class("hidden")
        assert not q(pilot, "#model-list").has_class("hidden")
