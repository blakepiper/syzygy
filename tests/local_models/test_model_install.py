"""Model acquisition, ownership, and cleanup (M16.6f).

The ownership boundary is the point: Syzygy may delete a file it
downloaded and marked, and nothing else - not a file the user pointed at,
not a file that appeared in the managed directory by other means, and not
anything outside the tree.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from syzygy.local_models.catalog import load_catalog
from syzygy.local_models.contracts import FailureKind
from syzygy.local_models.model_install import (
    ModelInstallError,
    accept_license,
    download_model,
    inspect_external_model,
    list_local_models,
    plan_model_download,
    remove_managed_model,
    use_external_model,
)
from syzygy.local_models.paths import write_ownership
from syzygy.local_models.settings import (
    LocalModelSettings,
    ModelRecord,
    load_local_model_settings,
    save_local_model_settings,
)

from .test_fit import machine
from .test_gguf import QWEN_LIKE, header


def gguf(path: Path, entries=None, *, padding: int = 4096) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header(entries if entries is not None else QWEN_LIKE) + b"\0" * padding)
    return path


def artifact():
    return load_catalog().artifacts[0]


# -- the plan ----------------------------------------------------------------


def test_the_plan_states_every_number_the_receipt_needs(local_paths, settings_path) -> None:
    entry = artifact()
    plan = plan_model_download(entry, machine(), local_paths, settings_path)

    assert plan.download_bytes == entry.size_bytes
    assert plan.final_bytes == entry.size_bytes
    assert plan.needs_license_acceptance is True
    assert plan.catalog_version == load_catalog().catalog_version
    assert "never chooses your card" in plan.purpose


def test_accepting_a_licence_is_recorded_against_the_exact_revision(
    local_paths, settings_path
) -> None:
    plan = plan_model_download(artifact(), machine(), local_paths, settings_path)
    settings = accept_license(settings_path, plan)

    assert settings.accepted_license(
        plan.artifact.id, plan.artifact.license_id, plan.catalog_version
    )
    # A different catalog revision is a different set of terms.
    assert not settings.accepted_license(
        plan.artifact.id, plan.artifact.license_id, "2099-01-01"
    )


def test_downloading_without_accepting_terms_is_refused(local_paths, settings_path) -> None:
    plan = plan_model_download(artifact(), machine(), local_paths, settings_path)

    with pytest.raises(ModelInstallError) as caught:
        download_model(plan, local_paths, settings_path)

    assert caught.value.failure.kind is FailureKind.TERMS_NOT_ACCEPTED
    assert caught.value.failure.retryable is False


def test_insufficient_disk_is_refused_before_any_request(local_paths, settings_path) -> None:
    plan = plan_model_download(
        artifact(), machine(free_disk=1024), local_paths, settings_path
    )
    accept_license(settings_path, plan)

    with pytest.raises(ModelInstallError) as caught:
        download_model(plan, local_paths, settings_path)

    assert caught.value.failure.kind is FailureKind.INSUFFICIENT_DISK


# -- external files ----------------------------------------------------------


def test_a_usable_external_model_is_accepted_and_never_moved(tmp_path) -> None:
    target = gguf(tmp_path / "elsewhere" / "mine.gguf")

    report = inspect_external_model(target, machine())

    assert report.usable is True
    assert report.metadata is not None
    assert report.estimated_memory_bytes is not None
    assert target.exists()  # untouched


def test_a_non_gguf_file_is_rejected_with_a_readable_reason(tmp_path) -> None:
    target = tmp_path / "model.bin"
    target.write_bytes(b"nope")

    report = inspect_external_model(target, machine())

    assert report.usable is False
    assert ".gguf" in report.reason


def test_a_corrupt_gguf_is_rejected(tmp_path) -> None:
    target = tmp_path / "model.gguf"
    target.write_bytes(b"GGUF" + b"\0" * 32)

    assert inspect_external_model(target, machine()).usable is False


def test_an_embedding_model_is_rejected_as_unusable_for_readings(tmp_path) -> None:
    from .test_gguf import _kv_string, _kv_uint32

    entries = [
        _kv_string("general.architecture", "bert"),
        _kv_uint32("bert.block_count", 12),
        _kv_string("tokenizer.chat_template", "x"),
    ]
    target = gguf(tmp_path / "embed.gguf", entries)

    report = inspect_external_model(target, machine())

    assert report.usable is False
    assert "doesn't write text" in report.reason


def test_a_model_without_a_chat_template_is_rejected(tmp_path) -> None:
    entries = [entry for entry in QWEN_LIKE if b"chat_template" not in entry]
    target = gguf(tmp_path / "raw.gguf", entries)

    report = inspect_external_model(target, machine())

    assert report.usable is False
    assert "chat template" in report.reason


def test_a_model_trained_for_too_little_context_is_rejected(tmp_path) -> None:
    from .test_gguf import _kv_uint32

    entries = [entry for entry in QWEN_LIKE if b"context_length" not in entry]
    entries.append(_kv_uint32("qwen3.context_length", 2048))
    target = gguf(tmp_path / "short.gguf", entries)

    report = inspect_external_model(target, machine())

    assert report.usable is False
    assert "2048" in report.reason


def test_choosing_an_external_file_records_it_as_not_owned(tmp_path, settings_path) -> None:
    target = gguf(tmp_path / "mine.gguf")
    report = inspect_external_model(target, machine())

    use_external_model(settings_path, report)

    record = load_local_model_settings(settings_path).model
    assert record is not None
    assert record.syzygy_owned is False
    assert record.path == str(target)


# -- manage local files ------------------------------------------------------


def test_managed_and_external_files_are_listed_with_their_ownership(
    local_paths, settings_path, tmp_path
) -> None:
    managed = gguf(local_paths.models_dir / "managed.gguf")
    write_ownership(local_paths.models_dir, kind="model", entries=("managed.gguf",))
    external = gguf(tmp_path / "outside" / "external.gguf")
    save_local_model_settings(
        settings_path,
        LocalModelSettings(model=ModelRecord(path=str(external), syzygy_owned=False)),
    )

    rows = {row.path.name: row for row in list_local_models(local_paths, settings_path)}

    assert rows["managed.gguf"].syzygy_owned is True
    assert rows["managed.gguf"].removable is True
    assert rows["external.gguf"].syzygy_owned is False
    assert rows["external.gguf"].removable is False
    assert rows["external.gguf"].in_use is True
    assert managed.exists() and external.exists()


def test_a_file_in_the_managed_directory_without_a_marker_is_not_owned(
    local_paths, settings_path
) -> None:
    gguf(local_paths.models_dir / "stranger.gguf")

    rows = list_local_models(local_paths, settings_path)

    assert rows[0].syzygy_owned is False
    assert rows[0].removable is False


def test_removing_a_managed_file_works_and_clears_the_setting(
    local_paths, settings_path
) -> None:
    managed = gguf(local_paths.models_dir / "managed.gguf")
    write_ownership(local_paths.models_dir, kind="model", entries=("managed.gguf",))
    save_local_model_settings(
        settings_path,
        LocalModelSettings(model=ModelRecord(path=str(managed), syzygy_owned=True)),
    )

    assert remove_managed_model(local_paths, managed, settings_path) is True
    assert not managed.exists()
    assert load_local_model_settings(settings_path).model is None


def test_removing_an_external_file_is_refused_and_deletes_nothing(
    local_paths, settings_path, tmp_path
) -> None:
    external = gguf(tmp_path / "someone-elses-cache" / "model.gguf")

    assert remove_managed_model(local_paths, external, settings_path) is False
    assert external.exists()


def test_removing_an_unmarked_file_inside_the_tree_is_refused(
    local_paths, settings_path
) -> None:
    stranger = gguf(local_paths.models_dir / "stranger.gguf")

    assert remove_managed_model(local_paths, stranger, settings_path) is False
    assert stranger.exists()


@pytest.mark.parametrize("suffix", ["", ".gguf"])
def test_a_symlink_out_of_the_tree_is_not_owned(
    local_paths, settings_path, tmp_path, suffix: str
) -> None:
    outside = gguf(tmp_path / f"outside{suffix or '.gguf'}")
    link = local_paths.models_dir / f"link{suffix}"
    link.symlink_to(outside)
    write_ownership(local_paths.models_dir, kind="model", entries=(link.name,))

    assert remove_managed_model(local_paths, link, settings_path) is False
    assert outside.exists()


def test_deep_verification_reports_a_digest_mismatch(local_paths, settings_path) -> None:
    managed = gguf(local_paths.models_dir / "managed.gguf")
    write_ownership(local_paths.models_dir, kind="model", entries=("managed.gguf",))
    save_local_model_settings(
        settings_path,
        LocalModelSettings(
            model=ModelRecord(path=str(managed), sha256="f" * 64, syzygy_owned=True)
        ),
    )

    rows = list_local_models(local_paths, settings_path, deep_verify=True)

    assert rows[0].verification == "DOES NOT MATCH"


def test_a_configured_file_that_vanished_is_listed_as_not_found(
    local_paths, settings_path, tmp_path
) -> None:
    save_local_model_settings(
        settings_path,
        LocalModelSettings(model=ModelRecord(path=str(tmp_path / "gone.gguf"))),
    )

    rows = list_local_models(local_paths, settings_path)

    assert rows[0].verification == "not found"


def test_struct_helpers_produce_a_readable_header(tmp_path) -> None:
    """Guards the test helper itself: a broken `gguf()` would make every
    rejection test above pass for the wrong reason."""
    target = gguf(tmp_path / "ok.gguf")
    assert target.read_bytes()[:4] == b"GGUF"
    assert struct.unpack("<I", target.read_bytes()[4:8])[0] == 3
