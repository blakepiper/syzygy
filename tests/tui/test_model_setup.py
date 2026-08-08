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


async def _open_llama_form(pilot) -> None:
    await pilot.pause()
    await pilot.press("m")
    await settle(pilot)
    assert isinstance(pilot.app.screen, ModelSetupScreen)

    listing = q(pilot, "#model-list", ListView)
    listing.index = 1  # fixture(0), llama_cpp(1), openai(2), anthropic(3)
    await pilot.pause()
    await pilot.press("enter")
    await settle(pilot)
    assert not q(pilot, "#llama-form").has_class("hidden")


async def test_selecting_llama_cpp_saves_the_selection(app: SyzygyApp, fake_settings_path):
    async with app.run_test() as pilot:
        await _open_llama_form(pilot)
        q(pilot, "#llama-use", Button).press()
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


# -- M11.3: the llama.cpp row is actionable ------------------------------


@pytest.fixture
def unreachable_llama_cpp(monkeypatch):
    """Overrides the autouse `reachable_llama_cpp` for the tests that care
    about the unreachable case - which is the situation the M11.3 report
    came from."""
    probed: list[str] = []

    async def fake_probe(base_url=None, *args, **kwargs) -> bool:
        probed.append(base_url)
        return False

    monkeypatch.setattr("syzygy.interpretation.providers.llama_cpp.probe", fake_probe)
    return probed


async def test_unreachable_row_names_the_url_it_probed(app: SyzygyApp, unreachable_llama_cpp):
    """"Not reachable" on its own doesn't say where it looked."""
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("m")
        await settle(pilot)

        row = q(pilot, "#model-list", ListView).children[1]
        label = row.query_one("Label").visual.plain
        assert "NOT reachable at http://127.0.0.1:8080/v1" in label


async def test_llama_form_shows_how_to_start_a_server_when_unreachable(
    app: SyzygyApp, unreachable_llama_cpp
):
    """M11.3c: the unreachable state must say what to do, not only what is
    wrong."""
    async with app.run_test() as pilot:
        await _open_llama_form(pilot)

        assert "Nothing answered at" in text_of(q(pilot, "#llama-probe-status", Static))
        assert not q(pilot, "#llama-help").has_class("hidden")
        assert "llama-server -m" in text_of(q(pilot, "#llama-help", Static))


async def test_llama_help_is_hidden_once_a_server_answers(app: SyzygyApp):
    """The reachable fixture is autouse, so this is the happy path."""
    async with app.run_test() as pilot:
        await _open_llama_form(pilot)

        assert "A server answered at" in text_of(q(pilot, "#llama-probe-status", Static))
        assert q(pilot, "#llama-help").has_class("hidden")


async def test_selecting_an_unreachable_server_says_so_and_still_saves(
    app: SyzygyApp, fake_settings_path, unreachable_llama_cpp
):
    """M11.3b: selecting an unreachable server is allowed - it may start
    later - but it must never look like nothing happened."""
    async with app.run_test() as pilot:
        await _open_llama_form(pilot)
        q(pilot, "#llama-use", Button).press()
        await settle(pilot)

        assert _saved_selection(fake_settings_path)["provider_id"] == "llama_cpp"
        message = text_of(q(pilot, "#model-message", Static))
        assert "nothing is answering there yet" in message
        assert "[P] to probe again" in message
        assert "fall back to fixture" in message


async def test_a_custom_base_url_is_persisted(app: SyzygyApp, fake_settings_path):
    async with app.run_test() as pilot:
        await _open_llama_form(pilot)
        q(pilot, "#llama-base-url", Input).value = "http://192.168.1.50:9090/v1"
        q(pilot, "#llama-model-id", Input).value = "my-gguf"
        q(pilot, "#llama-use", Button).press()
        await settle(pilot)

        saved = _saved_selection(fake_settings_path)
        assert saved["base_url"] == "http://192.168.1.50:9090/v1"
        assert saved["model_id"] == "my-gguf"


async def test_the_default_base_url_is_not_pinned_into_settings(
    app: SyzygyApp, fake_settings_path
):
    """Saving the default would freeze a value that may move."""
    async with app.run_test() as pilot:
        await _open_llama_form(pilot)
        q(pilot, "#llama-use", Button).press()
        await settle(pilot)

        assert _saved_selection(fake_settings_path)["base_url"] is None


async def test_a_saved_base_url_is_what_gets_probed(
    app: SyzygyApp, fake_settings_path, unreachable_llama_cpp
):
    fake_settings_path.write_text(
        json.dumps(
            {
                "provider_id": "llama_cpp",
                "model_id": None,
                "base_url": "http://elsewhere:1234/v1",
            }
        )
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("m")
        await settle(pilot)

        assert "http://elsewhere:1234/v1" in unreachable_llama_cpp
        row = q(pilot, "#model-list", ListView).children[1]
        assert "http://elsewhere:1234/v1" in row.query_one("Label").visual.plain


async def test_probe_button_rechecks_the_typed_url(app: SyzygyApp, unreachable_llama_cpp):
    async with app.run_test() as pilot:
        await _open_llama_form(pilot)
        q(pilot, "#llama-base-url", Input).value = "http://127.0.0.1:9999/v1"
        q(pilot, "#llama-probe", Button).press()
        await settle(pilot)

        assert "http://127.0.0.1:9999/v1" in unreachable_llama_cpp
        assert "Nothing answered at http://127.0.0.1:9999/v1" in text_of(
            q(pilot, "#llama-probe-status", Static)
        )


async def test_probe_reflects_a_server_that_has_since_started(
    app: SyzygyApp, monkeypatch, unreachable_llama_cpp
):
    """The reason re-probing exists: the answer changes once the user
    starts a server, and they shouldn't have to leave the screen to find
    out."""
    async with app.run_test() as pilot:
        await _open_llama_form(pilot)
        assert "Nothing answered" in text_of(q(pilot, "#llama-probe-status", Static))

        async def now_reachable(*args, **kwargs) -> bool:
            return True

        monkeypatch.setattr("syzygy.interpretation.providers.llama_cpp.probe", now_reachable)
        q(pilot, "#llama-probe", Button).press()
        await settle(pilot)

        assert "A server answered" in text_of(q(pilot, "#llama-probe-status", Static))
        assert q(pilot, "#llama-help").has_class("hidden")


async def test_p_reprobes_from_the_provider_list(app: SyzygyApp, monkeypatch):
    """`[P]` is a list-level binding. It cannot fire while a form's `Input`
    has focus - a focused input gets first refusal on every printable key,
    the same rule that lets a literal "q" be typed into a form field - so
    the form offers a PROBE button and ENTER-in-the-URL-field instead."""
    reachable = False

    async def fake_probe(*args, **kwargs) -> bool:
        return reachable

    monkeypatch.setattr("syzygy.interpretation.providers.llama_cpp.probe", fake_probe)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("m")
        await settle(pilot)

        row = q(pilot, "#model-list", ListView).children[1]
        assert "NOT reachable" in row.query_one("Label").visual.plain

        reachable = True
        await pilot.press("p")
        await settle(pilot)

        row = q(pilot, "#model-list", ListView).children[1]
        assert "— reachable" in row.query_one("Label").visual.plain


async def test_enter_in_the_base_url_field_probes_it(app: SyzygyApp, unreachable_llama_cpp):
    async with app.run_test() as pilot:
        await _open_llama_form(pilot)
        base_url = q(pilot, "#llama-base-url", Input)
        base_url.focus()
        base_url.value = "http://127.0.0.1:7777/v1"
        await pilot.pause()

        await pilot.press("enter")
        await settle(pilot)

        assert "http://127.0.0.1:7777/v1" in unreachable_llama_cpp


async def test_a_bad_url_reads_as_unreachable_rather_than_crashing(app: SyzygyApp, monkeypatch):
    async def exploding_probe(*args, **kwargs) -> bool:
        raise ValueError("not a URL")

    monkeypatch.setattr("syzygy.interpretation.providers.llama_cpp.probe", exploding_probe)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("m")
        await settle(pilot)
        listing = q(pilot, "#model-list", ListView)
        listing.index = 1
        await pilot.pause()
        await pilot.press("enter")
        await settle(pilot)

        q(pilot, "#llama-base-url", Input).value = "not a url"
        q(pilot, "#llama-probe", Button).press()
        await settle(pilot)

        assert "Nothing answered at not a url" in text_of(q(pilot, "#llama-probe-status", Static))


async def test_escape_closes_the_llama_form(app: SyzygyApp):
    async with app.run_test() as pilot:
        await _open_llama_form(pilot)
        await pilot.press("escape")
        await pilot.pause()

        assert q(pilot, "#llama-form").has_class("hidden")
        assert isinstance(pilot.app.screen, ModelSetupScreen)


async def test_selecting_fixture_says_what_it_means(app: SyzygyApp, fake_settings_path):
    fake_settings_path.write_text(json.dumps({"provider_id": "llama_cpp", "model_id": None}))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("m")
        await settle(pilot)
        listing = q(pilot, "#model-list", ListView)
        listing.index = 0
        await pilot.pause()
        await pilot.press("enter")
        await settle(pilot)

        assert not fake_settings_path.exists()
        assert "canned copy" in text_of(q(pilot, "#model-message", Static))
