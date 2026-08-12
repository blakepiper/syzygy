"""The local-model CLI surface (M16.10a/b).

Read-only commands must be scriptable and must never prompt; mutating
commands must require a confirmation and must refuse anything Syzygy does
not own. Nothing here downloads, starts a process, or opens a socket - the
data directory is redirected into `tmp_path` and the state is written by
hand.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from syzygy.cli import main
from syzygy.config import AppPaths
from syzygy.local_models.paths import LocalModelPaths, write_ownership
from syzygy.local_models.settings import (
    LocalModelSettings,
    ManagementMode,
    ModelRecord,
    RuntimeRecord,
    VerificationRecord,
    save_local_model_settings,
)


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch):
    """Point every `default_app_paths()` caller at `tmp_path`."""
    paths = AppPaths(
        data_dir=tmp_path,
        database_path=tmp_path / "syzygy.db",
        settings_path=tmp_path / "settings.json",
        knowledge_dir=tmp_path / "knowledge",
        models_dir=tmp_path / "models",
        logs_dir=tmp_path / "logs",
    )
    paths.ensure_exists()
    monkeypatch.setattr("syzygy.config.default_app_paths", lambda: paths)
    layout = LocalModelPaths.from_app_paths(paths)
    layout.ensure_exists()
    return paths, layout


def configure(paths: AppPaths, layout: LocalModelPaths) -> Path:
    """A healthy managed setup, with real files on disk."""
    model = layout.models_dir / "model.gguf"
    model.write_bytes(b"\0" * 512)
    write_ownership(layout.models_dir, kind="model", entries=("model.gguf",))
    runtime = layout.runtime_dir / "b10331" / "llama-server"
    runtime.parent.mkdir(parents=True, exist_ok=True)
    runtime.write_text("#!/bin/sh\n")

    from syzygy.interpretation.prompts import PROMPT_VERSION
    from syzygy.local_models.catalog import load_catalog

    save_local_model_settings(
        paths.settings_path,
        LocalModelSettings(
            mode=ManagementMode.MANAGED,
            runtime=RuntimeRecord(path=str(runtime), version="b10331", syzygy_owned=True),
            model=ModelRecord(
                path=str(model),
                size_bytes=512,
                artifact_id="qwen3-4b-instruct-q4-k-m",
                syzygy_owned=True,
            ),
            last_verification=VerificationRecord(
                verified_at_utc="2026-08-09T00:00:00+00:00",
                runtime_version="b10331",
                catalog_version=load_catalog().catalog_version,
                prompt_version=PROMPT_VERSION,
                served_model_id="qwen3-4b-instruct-q4-k-m",
            ),
        ),
    )
    return model


# -- read-only commands -------------------------------------------------------


def test_status_on_a_fresh_install_says_not_configured(isolated, capsys) -> None:
    assert main(["model", "local", "status"]) == 0

    output = capsys.readouterr().out
    assert "not configured" in output
    assert "setup-local" in output
    assert "Readings work without one" in output


def test_status_reports_a_configured_setup(isolated, capsys) -> None:
    paths, layout = isolated
    configure(paths, layout)

    assert main(["model", "local", "status"]) == 0

    output = capsys.readouterr().out
    assert "mode           managed" in output
    assert "qwen3-4b-instruct-q4-k-m" in output
    assert "present" in output
    assert "(current)" in output


def test_doctor_exits_zero_when_nothing_is_configured(isolated, capsys) -> None:
    """A missing local model is a supported state, not a failing
    environment requirement (M16.10b)."""
    assert main(["model", "local", "doctor"]) == 0
    assert "not configured" in capsys.readouterr().out


def test_doctor_exits_zero_on_a_healthy_setup(isolated, capsys) -> None:
    paths, layout = isolated
    configure(paths, layout)

    assert main(["model", "local", "doctor"]) == 0

    output = capsys.readouterr().out
    assert "OK" in output
    assert "127.0.0.1 only" in output


def test_doctor_exits_nonzero_when_the_model_file_vanished(isolated, capsys) -> None:
    paths, layout = isolated
    model = configure(paths, layout)
    model.unlink()

    assert main(["model", "local", "doctor"]) == 1
    assert "NEEDS REPAIR" in capsys.readouterr().out


def test_doctor_deep_reports_a_digest_mismatch(isolated, capsys) -> None:
    paths, layout = isolated
    model = configure(paths, layout)
    from syzygy.local_models.settings import load_local_model_settings

    settings = load_local_model_settings(paths.settings_path)
    save_local_model_settings(
        paths.settings_path,
        settings.model_copy(
            update={"model": settings.model.model_copy(update={"sha256": "f" * 64})}
        ),
    )
    assert model.exists()

    assert main(["model", "local", "doctor", "--deep"]) == 1
    assert "DOES NOT MATCH" in capsys.readouterr().out


def test_list_shows_ownership(isolated, capsys) -> None:
    paths, layout = isolated
    configure(paths, layout)

    assert main(["model", "local", "list"]) == 0

    output = capsys.readouterr().out
    assert "managed" in output
    assert "in use" in output


def test_the_global_doctor_includes_the_local_model_without_failing(
    isolated, capsys, monkeypatch
) -> None:
    monkeypatch.setattr(
        "syzygy.cli._print_provider_status", lambda: print("providers: skipped")
    )
    assert main(["doctor"]) == 0
    assert "local model" in capsys.readouterr().out


# -- mutating commands --------------------------------------------------------


def test_remove_refuses_a_file_syzygy_does_not_own(isolated, capsys, tmp_path) -> None:
    outside = tmp_path / "somewhere-else" / "someone-elses.gguf"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"\0" * 16)

    assert main(["model", "local", "remove", str(outside), "--yes"]) == 1
    assert outside.exists()
    assert "not a file Syzygy downloaded" in capsys.readouterr().err


def test_remove_without_a_terminal_and_without_yes_does_nothing(
    isolated, capsys, monkeypatch
) -> None:
    """M16.10a: a confirmation prompt must never hang a scripted run, and
    must never be answered by default."""
    paths, layout = isolated
    model = configure(paths, layout)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    assert main(["model", "local", "remove", str(model)]) == 0
    assert model.exists()
    assert "Not a terminal" in capsys.readouterr().err


def test_remove_with_yes_deletes_a_managed_file_and_clears_the_setting(
    isolated, capsys
) -> None:
    paths, layout = isolated
    model = configure(paths, layout)

    assert main(["model", "local", "remove", str(model), "--yes"]) == 0

    assert not model.exists()
    from syzygy.local_models.settings import load_local_model_settings

    assert load_local_model_settings(paths.settings_path).model is None
    assert "can download it again" in capsys.readouterr().out


def test_stop_with_nothing_running_is_a_no_op(isolated, capsys) -> None:
    assert main(["model", "local", "stop"]) == 0
    assert "No local model server" in capsys.readouterr().out


def test_stop_clears_a_stale_record_without_signalling_anything(
    isolated, capsys
) -> None:
    """A recorded PID that cannot be verified is cleaned up, never
    signalled (M16.7d)."""
    _paths, layout = isolated
    from syzygy.local_models.runtime_state import (
        LocalRuntimeState,
        ProcessIdentity,
        load_runtime_state,
        save_runtime_state,
    )

    save_runtime_state(
        layout.state_path,
        LocalRuntimeState(
            process=ProcessIdentity(
                pid=2**30,
                executable="/nowhere/llama-server",
                start_token="t",
                started_at_utc="2026-01-01T00:00:00+00:00",
                port=1,
                model_path="/nowhere/model.gguf",
            )
        ),
    )

    assert main(["model", "local", "stop"]) == 0

    assert "Nothing was signalled" in capsys.readouterr().out
    assert load_runtime_state(layout.state_path).process is None


def test_status_does_not_report_a_dead_process_as_a_running_server(
    isolated, capsys
) -> None:
    """The record outlives an unclean exit. Printing it as a live server
    sent the user looking for a process that had been gone for days
    (M25.3)."""
    paths, layout = isolated
    configure(paths, layout)
    from syzygy.local_models.runtime_state import (
        LocalRuntimeState,
        ProcessIdentity,
        save_runtime_state,
    )

    save_runtime_state(
        layout.state_path,
        LocalRuntimeState(
            process=ProcessIdentity(
                pid=2**30,
                executable="/nowhere/llama-server",
                start_token="t",
                started_at_utc="2026-01-01T00:00:00+00:00",
                port=41234,
                model_path="/nowhere/model.gguf",
            )
        ),
    )

    assert main(["model", "local", "status"]) == 0

    output = capsys.readouterr().out
    assert "no longer running" in output
    assert "model local stop" in output


def test_start_without_a_configured_model_refuses(isolated, capsys) -> None:
    assert main(["model", "local", "start"]) == 1
    assert "No managed local model" in capsys.readouterr().err


def test_use_file_refuses_something_that_is_not_a_model(isolated, capsys, tmp_path) -> None:
    junk = tmp_path / "notes.txt"
    junk.write_text("hello")

    assert main(["model", "local", "use-file", str(junk)]) == 1
    assert "will not use this file" in capsys.readouterr().err


def test_use_file_adopts_a_valid_model_without_moving_it(
    isolated, capsys, tmp_path
) -> None:
    paths, layout = isolated
    configure(paths, layout)

    from .test_model_install import gguf

    mine = gguf(tmp_path / "my-models" / "mine.gguf")

    assert main(["model", "local", "use-file", str(mine)]) == 0

    from syzygy.local_models.settings import load_local_model_settings

    record = load_local_model_settings(paths.settings_path).model
    assert record is not None
    assert record.path == str(mine)
    assert record.syzygy_owned is False
    # Adopting a different model invalidates the previous verification.
    assert load_local_model_settings(paths.settings_path).last_verification is None
    assert mine.exists()
    assert "never move or delete it" in capsys.readouterr().out


def test_use_file_needs_a_runner_first(isolated, capsys, tmp_path) -> None:
    from .test_model_install import gguf

    mine = gguf(tmp_path / "mine.gguf")

    assert main(["model", "local", "use-file", str(mine)]) == 1
    assert "No model runner is configured" in capsys.readouterr().err


# -- setup-local --------------------------------------------------------------


def test_setup_local_without_a_terminal_is_a_read_only_report(
    isolated, capsys, monkeypatch
) -> None:
    """No terminal means nobody can consent, so it prints the plan and
    stops - it must never download on a machine that cannot answer."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr(
        "syzygy.local_models.orchestrator.LocalSetupSession.run_discovery",
        lambda self: _empty_discovery(self),
    )

    assert main(["model", "setup-local"]) == 0

    output = capsys.readouterr().out
    assert "Syzygy will:" in output
    assert "It will contact:" in output
    assert "read-only report" in output


def _empty_discovery(session):
    from syzygy.local_models.orchestrator import DiscoveryReport
    from syzygy.local_models.state import SetupState

    session.move_to(SetupState.DISCOVERY)
    session.discovery = DiscoveryReport()
    return session.discovery


def test_setup_local_rejects_an_unknown_tier(isolated, capsys) -> None:
    """argparse rejects it before any machine is touched."""
    with pytest.raises(SystemExit) as caught:
        main(["model", "setup-local", "--tier", "nonsense"])

    assert caught.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_the_evaluation_harness_is_disabled_without_dev_mode(
    isolated, capsys, monkeypatch
) -> None:
    monkeypatch.delenv("SYZYGY_DEV", raising=False)

    assert (
        main(
            [
                "dev",
                "evaluate-local",
                "--base-url",
                "http://127.0.0.1:1/v1",
                "--model",
                "m",
                "--artifact",
                "a",
                "--hardware",
                "test",
            ]
        )
        == 1
    )
    assert "maintainer tool" in capsys.readouterr().err
