import pytest

from syzygy.cli import main
from syzygy.interpretation.providers import api_keys


def test_dev_deck_lists_78_cards(capsys):
    exit_code = main(["dev", "deck"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "the_fool" in out
    assert "78 cards total." in out


def test_doctor_exits_zero(isolated_app_paths, capsys):
    exit_code = main(["doctor"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "deck    OK" in out
    # Knowledge base and provider config are informational (DESIGN.md
    # section 15/13.3's "no model configured" and "no source ingested"
    # are both supported states) - doctor reports them, but neither can
    # fail its exit code.
    assert "not ingested" in out
    assert "llama_cpp" in out
    assert "active provider: fixture" in out


def test_help_flag_prints_usage(capsys):
    # `syzygy` with no arguments launches the TUI (DESIGN.md section 20),
    # so usage is reached through --help rather than through no arguments.
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "usage" in out.lower()
    assert "tui" in out


def test_unknown_subcommand_group_prints_help(capsys):
    exit_code = main(["dev"])
    assert exit_code == 0
    assert "usage" in capsys.readouterr().out.lower()


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0


@pytest.fixture(autouse=True)
def fake_keyring(monkeypatch):
    """None of the `model` command tests below should touch a real OS
    keyring - a tiny in-memory fake keeps them deterministic on any
    machine, same as `tests/interpretation/providers/test_api_keys.py`."""
    store: dict[tuple[str, str], str] = {}

    def fake_get_password(service: str, username: str) -> str | None:
        return store.get((service, username))

    def fake_set_password(service: str, username: str, password: str) -> None:
        store[(service, username)] = password

    def fake_delete_password(service: str, username: str) -> None:
        import keyring.errors

        if (service, username) not in store:
            raise keyring.errors.PasswordDeleteError("not found")
        del store[(service, username)]

    monkeypatch.setattr(api_keys.keyring, "get_password", fake_get_password)
    monkeypatch.setattr(api_keys.keyring, "set_password", fake_set_password)
    monkeypatch.setattr(api_keys.keyring, "delete_password", fake_delete_password)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_model_status_reports_unconfigured_providers(capsys):
    exit_code = main(["model", "status"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "llama_cpp" in out
    assert "not reachable" in out
    assert "openai" in out and "no key configured" in out
    assert "anthropic" in out and "no key configured" in out


def test_model_status_reports_an_env_var_key(capsys, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    exit_code = main(["model", "status"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "openai" in out and "OPENAI_API_KEY" in out


def test_model_configure_stores_a_key(capsys, monkeypatch):
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: "secret-key")

    exit_code = main(["model", "configure", "openai"])
    assert exit_code == 0
    assert "secret-key" not in capsys.readouterr().out
    assert api_keys.has_stored_api_key("openai") is True
    assert api_keys.resolve_api_key("openai", "OPENAI_API_KEY") == "secret-key"


def test_model_configure_rejects_an_empty_key(capsys, monkeypatch):
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: "")

    exit_code = main(["model", "configure", "openai"])
    assert exit_code == 1
    assert api_keys.has_stored_api_key("openai") is False


def test_model_configure_delete_removes_a_stored_key(capsys):
    api_keys.store_api_key("anthropic", "secret-key")

    exit_code = main(["model", "configure", "anthropic", "--delete"])
    assert exit_code == 0
    assert api_keys.has_stored_api_key("anthropic") is False


def test_model_configure_rejects_llama_cpp(capsys):
    with pytest.raises(SystemExit):
        main(["model", "configure", "llama_cpp"])


@pytest.fixture
def isolated_app_paths(tmp_path, monkeypatch):
    """`model use` writes to `AppPaths.settings_path` - point that at a
    tmp directory instead of the real machine's `platformdirs` data dir,
    the same way `fake_keyring` isolates the OS keyring above."""
    from syzygy.config import AppPaths

    paths = AppPaths(
        data_dir=tmp_path,
        database_path=tmp_path / "syzygy.db",
        settings_path=tmp_path / "settings.json",
        knowledge_dir=tmp_path / "knowledge",
        models_dir=tmp_path / "models",
        logs_dir=tmp_path / "logs",
    )
    monkeypatch.setattr("syzygy.config.default_app_paths", lambda: paths)
    return paths


def test_model_use_fixture_clears_any_saved_selection(isolated_app_paths, capsys):
    isolated_app_paths.settings_path.write_text('{"provider_id": "openai", "model_id": "x"}')

    exit_code = main(["model", "use", "fixture"])
    assert exit_code == 0
    assert not isolated_app_paths.settings_path.exists()


def test_model_use_llama_cpp_saves_a_selection(isolated_app_paths, capsys):
    exit_code = main(["model", "use", "llama_cpp", "--model", "local-test"])
    assert exit_code == 0

    import json

    saved = json.loads(isolated_app_paths.settings_path.read_text())
    assert saved == {"provider_id": "llama_cpp", "model_id": "local-test", "base_url": None}


def test_model_use_openai_without_a_model_id_warns_but_still_saves(isolated_app_paths, capsys):
    exit_code = main(["model", "use", "openai"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "model id" in captured.err.lower()
    assert isolated_app_paths.settings_path.exists()


def test_model_use_openai_discloses_leaving_the_local_machine(isolated_app_paths, capsys):
    main(["model", "use", "openai", "--model", "gpt-4o-mini"])
    out = capsys.readouterr().out
    assert "sends" in out.lower() and "servers" in out.lower()


def test_model_use_llama_cpp_does_not_disclose_leaving_the_machine(isolated_app_paths, capsys):
    main(["model", "use", "llama_cpp"])
    out = capsys.readouterr().out
    assert "servers" not in out.lower()


def test_model_status_reflects_the_active_selection(isolated_app_paths, capsys):
    main(["model", "use", "llama_cpp", "--model", "local-test"])
    capsys.readouterr()  # discard `use`'s own output

    exit_code = main(["model", "status"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "active provider: llama_cpp (local-test)" in out
