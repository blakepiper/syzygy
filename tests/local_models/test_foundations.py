"""Contracts, state machine, paths, and settings (M16.1).

Small, fast, and load-bearing: everything above depends on provenance
being un-fakeable, transitions being data, ownership being provable, and
the settings section not clobbering its neighbours.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from syzygy.local_models.contracts import (
    Backend,
    Fact,
    GpuDevice,
    GpuVendor,
    Provenance,
    detected,
    inferred,
    unknown,
)
from syzygy.local_models.diagnostics import diagnostics_report, redact, redact_argv
from syzygy.local_models.paths import (
    LocalModelPaths,
    atomic_write_json,
    forget_ownership,
    is_syzygy_owned,
    read_json,
    read_ownership,
    write_ownership,
)
from syzygy.local_models.settings import (
    LaunchProfile,
    LicenseAcceptance,
    LocalModelSettings,
    ManagementMode,
    ModelRecord,
    clear_local_model_settings,
    load_local_model_settings,
    save_local_model_settings,
)
from syzygy.local_models.state import (
    InvalidSetupTransition,
    SetupState,
    assert_transition,
    can_transition,
    is_terminal,
)

# -- provenance --------------------------------------------------------------


def test_a_detected_fact_is_known() -> None:
    fact = detected(42)

    assert fact.known is True
    assert fact.require() == 42
    assert fact.provenance is Provenance.DETECTED


def test_an_inferred_fact_always_carries_its_reasoning() -> None:
    fact = inferred(8, "half the logical core count")

    assert fact.provenance is Provenance.INFERRED
    assert fact.note


def test_an_unknown_fact_has_no_value_and_refuses_to_produce_one() -> None:
    fact: Fact[int] = unknown("nvidia-smi not on PATH")

    assert fact.known is False
    assert fact.value is None
    with pytest.raises(ValueError, match="nvidia-smi"):
        fact.require()


def test_candidate_backends_end_in_cpu_and_never_repeat() -> None:
    from datetime import UTC, datetime

    from syzygy.local_models.contracts import MachineInventory

    inventory = MachineInventory(
        collected_at_utc=datetime(2026, 1, 1, tzinfo=UTC),
        gpus=(
            GpuDevice(index=0, vendor=GpuVendor.NVIDIA, backends=(Backend.CUDA, Backend.VULKAN)),
            GpuDevice(index=1, vendor=GpuVendor.INTEL, backends=(Backend.VULKAN,)),
        ),
    )

    assert inventory.candidate_backends == (Backend.CUDA, Backend.VULKAN, Backend.CPU)
    assert inventory.best_backend is Backend.CUDA


# -- state machine -----------------------------------------------------------


def test_the_happy_path_is_walkable_end_to_end() -> None:
    path = [
        SetupState.INTRO,
        SetupState.INVENTORY,
        SetupState.DISCOVERY,
        SetupState.RECOMMEND,
        SetupState.CONSENT,
        SetupState.RUNTIME,
        SetupState.MODEL,
        SetupState.START,
        SetupState.VERIFY,
        SetupState.COMPLETE,
    ]
    for current, target in zip(path, path[1:], strict=False):
        assert_transition(current, target)


def test_a_running_endpoint_may_skip_straight_to_verification() -> None:
    assert can_transition(SetupState.DISCOVERY, SetupState.VERIFY)


def test_an_installed_runtime_may_skip_acquisition() -> None:
    assert can_transition(SetupState.CONSENT, SetupState.MODEL)


def test_skipping_verification_is_impossible() -> None:
    assert not can_transition(SetupState.START, SetupState.COMPLETE)
    assert not can_transition(SetupState.MODEL, SetupState.COMPLETE)
    with pytest.raises(InvalidSetupTransition):
        assert_transition(SetupState.INTRO, SetupState.COMPLETE)


def test_failing_and_cancelling_are_legal_from_every_working_state() -> None:
    working = [
        SetupState.INTRO,
        SetupState.INVENTORY,
        SetupState.DISCOVERY,
        SetupState.RECOMMEND,
        SetupState.CONSENT,
        SetupState.RUNTIME,
        SetupState.MODEL,
        SetupState.START,
        SetupState.VERIFY,
    ]
    for state in working:
        assert can_transition(state, SetupState.FAILED)
        assert can_transition(state, SetupState.CANCELLED)


def test_completion_is_terminal_and_leads_nowhere() -> None:
    assert is_terminal(SetupState.COMPLETE)
    for state in SetupState:
        assert not can_transition(SetupState.COMPLETE, state)


def test_a_failure_can_return_to_the_step_that_failed() -> None:
    for state in (SetupState.RUNTIME, SetupState.MODEL, SetupState.START, SetupState.VERIFY):
        assert can_transition(SetupState.FAILED, state)


def test_resuming_after_cancelling_starts_over_at_the_intro() -> None:
    assert can_transition(SetupState.CANCELLED, SetupState.INTRO)
    assert not can_transition(SetupState.CANCELLED, SetupState.VERIFY)


def test_re_entering_a_working_step_is_allowed_but_not_a_terminal_one() -> None:
    assert can_transition(SetupState.MODEL, SetupState.MODEL)
    assert not can_transition(SetupState.COMPLETE, SetupState.COMPLETE)


# -- paths and ownership -----------------------------------------------------


def test_the_layout_is_created_under_one_root(tmp_path) -> None:
    from syzygy.config import AppPaths

    app = AppPaths(
        data_dir=tmp_path,
        database_path=tmp_path / "syzygy.db",
        settings_path=tmp_path / "settings.json",
        knowledge_dir=tmp_path / "knowledge",
        models_dir=tmp_path / "models",
        logs_dir=tmp_path / "logs",
    )
    paths = LocalModelPaths.from_app_paths(app)
    paths.ensure_exists()

    assert paths.root == tmp_path / "local_models"
    for directory in (paths.runtime_dir, paths.models_dir, paths.partial_dir, paths.logs_dir):
        assert directory.is_dir()
        assert paths.contains(directory)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_the_managed_tree_is_private_to_this_user(local_paths) -> None:
    assert local_paths.root.stat().st_mode & 0o777 == 0o700


def test_ownership_is_merged_not_replaced(local_paths) -> None:
    write_ownership(local_paths.models_dir, kind="model", entries=("a.gguf",))
    write_ownership(local_paths.models_dir, kind="model", entries=("b.gguf",))

    marker = read_ownership(local_paths.models_dir)
    assert marker is not None
    assert marker.entries == ("a.gguf", "b.gguf")


def test_forgetting_removes_only_the_named_entry(local_paths) -> None:
    write_ownership(local_paths.models_dir, kind="model", entries=("a.gguf", "b.gguf"))
    forget_ownership(local_paths.models_dir, "a.gguf")

    marker = read_ownership(local_paths.models_dir)
    assert marker is not None and marker.entries == ("b.gguf",)


def test_an_unrecognized_marker_schema_means_not_ours(local_paths) -> None:
    target = local_paths.models_dir / "x.gguf"
    target.write_bytes(b"x")
    atomic_write_json(
        local_paths.models_dir / "OWNERSHIP.json",
        {"schema": "something-else", "entries": ["x.gguf"]},
    )

    assert is_syzygy_owned(local_paths, target) is False


def test_a_missing_or_corrupt_marker_reads_as_none(local_paths) -> None:
    assert read_ownership(local_paths.models_dir) is None
    (local_paths.models_dir / "OWNERSHIP.json").write_text("{oops")
    assert read_ownership(local_paths.models_dir) is None


def test_a_path_outside_the_tree_is_never_contained(local_paths, tmp_path) -> None:
    assert local_paths.contains(tmp_path / "elsewhere" / "x") is False


def test_atomic_write_leaves_no_temporary_file_behind(tmp_path) -> None:
    target = tmp_path / "state.json"
    atomic_write_json(target, {"a": 1})

    assert json.loads(target.read_text()) == {"a": 1}
    assert list(tmp_path.iterdir()) == [target]


def test_read_json_never_raises(tmp_path) -> None:
    assert read_json(tmp_path / "absent.json") == {}
    broken = tmp_path / "broken.json"
    broken.write_text("[1, 2, 3]")  # valid JSON, wrong shape
    assert read_json(broken) == {}


# -- settings ----------------------------------------------------------------


def test_the_local_model_section_does_not_disturb_the_provider_section(settings_path) -> None:
    from syzygy.interpretation.providers.selection import (
        ProviderSelection,
        load_selection,
        save_selection,
    )

    save_selection(settings_path, ProviderSelection(provider_id="openai", model_id="gpt"))
    save_local_model_settings(
        settings_path, LocalModelSettings(mode=ManagementMode.MANAGED)
    )

    selection = load_selection(settings_path)
    assert selection is not None and selection.provider_id == "openai"
    assert load_local_model_settings(settings_path).mode is ManagementMode.MANAGED


def test_a_partially_completed_setup_round_trips(settings_path) -> None:
    settings = LocalModelSettings(
        mode=ManagementMode.MANAGED,
        model=ModelRecord(path="/models/x.gguf", syzygy_owned=True),
        launch=LaunchProfile(context_tokens=8192, max_output_tokens=1536, gpu_layers=999),
    )
    save_local_model_settings(settings_path, settings)

    loaded = load_local_model_settings(settings_path)
    assert loaded.model is not None and loaded.model.path == "/models/x.gguf"
    assert loaded.launch is not None and loaded.launch.gpu_layers == 999
    assert loaded.runtime is None


def test_a_corrupt_section_reads_as_nothing_set_up(settings_path) -> None:
    settings_path.write_text(json.dumps({"local_model": {"mode": "nonsense"}}))

    assert load_local_model_settings(settings_path).mode is None


def test_licence_acceptance_is_keyed_on_artifact_and_catalog_revision() -> None:
    settings = LocalModelSettings().with_license(
        LicenseAcceptance(
            artifact_id="a",
            license_id="Apache-2.0",
            license_url="https://huggingface.co/x/LICENSE",
            catalog_version="2026-08-08",
            accepted_at_utc="2026-08-08T00:00:00+00:00",
        )
    )

    assert settings.accepted_license("a", "Apache-2.0", "2026-08-08")
    assert not settings.accepted_license("a", "Apache-2.0", "2026-09-01")
    assert not settings.accepted_license("a", "MIT", "2026-08-08")
    assert not settings.accepted_license("b", "Apache-2.0", "2026-08-08")


def test_replacing_an_acceptance_does_not_duplicate_it() -> None:
    def acceptance(version: str) -> LicenseAcceptance:
        return LicenseAcceptance(
            artifact_id="a",
            license_id="Apache-2.0",
            license_url="https://huggingface.co/x/LICENSE",
            catalog_version=version,
            accepted_at_utc="2026-08-08T00:00:00+00:00",
        )

    settings = LocalModelSettings().with_license(acceptance("1")).with_license(acceptance("2"))

    assert len(settings.licenses) == 1
    assert settings.licenses[0].catalog_version == "2"


def test_clearing_forgets_the_setup_without_touching_any_file(settings_path) -> None:
    save_local_model_settings(
        settings_path,
        LocalModelSettings(model=ModelRecord(path="/models/x.gguf", syzygy_owned=True)),
    )
    clear_local_model_settings(settings_path)

    assert load_local_model_settings(settings_path).model is None


# -- redaction ---------------------------------------------------------------


@pytest.mark.parametrize(
    "secret",
    [
        "hf_abcdefghijklmnopqrstuv",
        "sk-abcdefghijklmnopqrstuv",
        "sk-ant-abcdefghijklmnopqrst",
        "Bearer abcdefghijklmnop",
        "Authorization: Token abcdefgh",
    ],
)
def test_credential_shapes_are_removed(secret: str) -> None:
    assert secret not in redact(f"request failed with {secret} attached")


def test_a_token_in_a_query_string_is_removed_but_the_url_survives() -> None:
    cleaned = redact("https://example.invalid/model.gguf?token=abcdef123456&x=1")

    assert "abcdef123456" not in cleaned
    assert "model.gguf" in cleaned


def test_the_home_directory_becomes_a_tilde(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    cleaned = redact(f"could not open {tmp_path}/models/x.gguf")

    assert str(tmp_path) not in cleaned
    assert "~/models/x.gguf" in cleaned


def test_redaction_never_raises_on_empty_input() -> None:
    assert redact("") == ""
    assert redact_argv([]) == ""


def test_the_diagnostics_report_contains_no_environment_dump() -> None:
    from datetime import UTC, datetime

    from syzygy.local_models.contracts import MachineInventory

    report = diagnostics_report(
        MachineInventory(
            collected_at_utc=datetime(2026, 1, 1, tzinfo=UTC),
            os_name=detected("Linux"),
            total_ram_bytes=detected(16 * 1024**3),
        )
    )

    assert "[machine]" in report
    assert "Installed memory: 16.0 GiB" in report
    assert "PATH" not in report
    assert "environ" not in report.lower()
