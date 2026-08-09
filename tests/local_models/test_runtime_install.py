"""Runtime acquisition (M16.5e).

No real install, no real network. The archive route is driven through
`httpx.MockTransport` with archives built in the test; the package-manager
route is driven through a fake `Probe`.
"""

from __future__ import annotations

import hashlib
import io
import tarfile
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from syzygy.local_models.catalog import load_runtime_manifest
from syzygy.local_models.contracts import Backend, Compatibility, FailureKind
from syzygy.local_models.inventory import collect_inventory
from syzygy.local_models.paths import read_ownership
from syzygy.local_models.probe import CommandResult
from syzygy.local_models.runtime_install import (
    RuntimeInstallError,
    check_package_manager,
    install_runtime_archive,
    install_via_package_manager,
    plan_runtime_install,
    qualify_after_manager_install,
    remove_managed_runtime,
)

from .machines import linux_cpu_probe, make_probe, ok


def build_archive(*, server_body: bytes = b"#!/bin/sh\n") -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        info = tarfile.TarInfo("llama-b10331/llama-server")
        info.size = len(server_body)
        info.mode = 0o755
        bundle.addfile(info, io.BytesIO(server_body))
        readme = b"MIT"
        info = tarfile.TarInfo("llama-b10331/LICENSE")
        info.size = len(readme)
        bundle.addfile(info, io.BytesIO(readme))
    return buffer.getvalue()


def patched_plan(local_paths, monkeypatch, archive: bytes):
    """A plan whose digest and size match the archive the fake server will
    actually serve."""
    inventory = collect_inventory(linux_cpu_probe())
    plan = plan_runtime_install(inventory, local_paths)
    build = plan.build.model_copy(
        update={"sha256": hashlib.sha256(archive).hexdigest(), "size_bytes": len(archive)}
    )
    return plan.__class__(
        build=build,
        manifest=plan.manifest,
        install_dir=plan.install_dir,
        download_bytes=len(archive),
        disk_bytes=len(archive) * 2,
        backend=plan.backend,
        reason=plan.reason,
        managers=plan.managers,
    )


def serving(archive: bytes):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=archive, headers={"Content-Length": str(len(archive))}
        )

    return handler


def probe_reporting(version: str):
    """A probe that answers `--version` for whatever path it is given -
    the installed binary's path is not known until extraction."""

    def run(argv, timeout):
        if len(argv) >= 2 and argv[1] == "--version":
            return CommandResult(argv=tuple(argv), returncode=0, stderr=version)
        return CommandResult(argv=tuple(argv), missing=True)

    return replace(make_probe(), run=run)


# -- planning ----------------------------------------------------------------


def test_a_plan_states_source_version_size_and_location(local_paths) -> None:
    plan = plan_runtime_install(collect_inventory(linux_cpu_probe()), local_paths)

    assert plan.source_url.startswith("https://github.com/")
    assert plan.version == load_runtime_manifest().release_tag
    assert plan.download_bytes > 0
    assert plan.install_dir == local_paths.runtime_dir / plan.version
    assert plan.backend is Backend.CPU
    assert plan.reason


def test_an_unsupported_platform_gets_a_typed_refusal(local_paths) -> None:
    inventory = collect_inventory(make_probe(system="Haiku", machine="ppc64"))

    with pytest.raises(RuntimeInstallError) as caught:
        plan_runtime_install(inventory, local_paths)

    assert caught.value.failure.kind is FailureKind.UNSUPPORTED_PLATFORM
    assert caught.value.failure.retryable is False


# -- the archive route -------------------------------------------------------


def test_a_verified_archive_is_unpacked_qualified_and_promoted(
    local_paths, monkeypatch
) -> None:
    archive = build_archive()
    plan = patched_plan(local_paths, monkeypatch, archive)
    monkeypatch.setattr(
        "syzygy.local_models.runtime_install.download_verified",
        lambda request, paths, **kwargs: _write(request.destination, archive),
    )

    capabilities = install_runtime_archive(plan, local_paths, probe_reporting("version: 10331\n"))

    assert capabilities.compatibility is Compatibility.COMPATIBLE
    installed = Path(capabilities.candidate.locator)
    assert installed.exists()
    assert local_paths.contains(installed)
    marker = read_ownership(local_paths.runtime_dir)
    assert marker is not None and plan.version in marker.entries
    # The archive is not left behind in `partial/`.
    assert not list(local_paths.partial_dir.glob("*.tar.gz"))


def _write(destination: Path, payload: bytes) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return destination


def test_a_download_failure_becomes_a_runtime_install_failure(
    local_paths, monkeypatch
) -> None:
    from syzygy.local_models.contracts import SetupFailure
    from syzygy.local_models.download import DownloadError

    archive = build_archive()
    plan = patched_plan(local_paths, monkeypatch, archive)

    def failing(request, paths, **kwargs):
        raise DownloadError(
            SetupFailure(kind=FailureKind.OFFLINE, message="no network")
        )

    monkeypatch.setattr("syzygy.local_models.runtime_install.download_verified", failing)

    with pytest.raises(RuntimeInstallError) as caught:
        install_runtime_archive(plan, local_paths, make_probe())

    assert caught.value.failure.kind is FailureKind.OFFLINE


def test_a_malicious_archive_is_refused_and_nothing_is_promoted(
    local_paths, monkeypatch
) -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        info = tarfile.TarInfo("../escaped")
        info.size = 1
        bundle.addfile(info, io.BytesIO(b"x"))
    archive = buffer.getvalue()

    plan = patched_plan(local_paths, monkeypatch, archive)
    monkeypatch.setattr(
        "syzygy.local_models.runtime_install.download_verified",
        lambda request, paths, **kwargs: _write(request.destination, archive),
    )

    with pytest.raises(RuntimeInstallError) as caught:
        install_runtime_archive(plan, local_paths, make_probe())

    assert caught.value.failure.kind is FailureKind.ARCHIVE_UNSAFE
    assert not plan.install_dir.exists()


def test_an_archive_without_the_server_program_is_refused(local_paths, monkeypatch) -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        info = tarfile.TarInfo("llama-b10331/README")
        info.size = 2
        bundle.addfile(info, io.BytesIO(b"hi"))
    archive = buffer.getvalue()

    plan = patched_plan(local_paths, monkeypatch, archive)
    monkeypatch.setattr(
        "syzygy.local_models.runtime_install.download_verified",
        lambda request, paths, **kwargs: _write(request.destination, archive),
    )

    with pytest.raises(RuntimeInstallError) as caught:
        install_runtime_archive(plan, local_paths, make_probe())

    assert caught.value.failure.kind is FailureKind.RUNTIME_UNSUITABLE
    assert not plan.install_dir.exists()


def test_a_replacement_that_fails_qualification_leaves_the_old_one_in_place(
    local_paths, monkeypatch
) -> None:
    archive = build_archive()
    plan = patched_plan(local_paths, monkeypatch, archive)

    previous = plan.install_dir / "llama-server"
    previous.parent.mkdir(parents=True, exist_ok=True)
    previous.write_text("the known-good build")

    monkeypatch.setattr(
        "syzygy.local_models.runtime_install.download_verified",
        lambda request, paths, **kwargs: _write(request.destination, archive),
    )

    # A binary that does not identify itself as llama.cpp fails to qualify.
    with pytest.raises(RuntimeInstallError):
        install_runtime_archive(plan, local_paths, probe_reporting("GNU coreutils 9.4\n"))

    assert previous.read_text() == "the known-good build"


# -- the package-manager route -----------------------------------------------


def manager():
    return load_runtime_manifest().package_managers[0]


def test_a_missing_manager_is_reported_not_installed() -> None:
    availability = check_package_manager(manager(), make_probe())

    assert availability.available is False
    assert "isn't installed" in availability.note


def test_a_present_manager_reports_its_version() -> None:
    entry = manager()
    probe = make_probe(
        which={entry.executable: f"/usr/bin/{entry.executable}"},
        commands={tuple(entry.version_argv): ok("4.2.0\n")},
    )

    availability = check_package_manager(entry, probe)

    assert availability.available is True
    assert availability.version == "4.2.0"


def test_installing_with_a_missing_manager_is_a_typed_failure() -> None:
    with pytest.raises(RuntimeInstallError) as caught:
        install_via_package_manager(manager(), make_probe())

    assert caught.value.failure.kind is FailureKind.PACKAGE_MANAGER_MISSING
    assert caught.value.failure.retryable is False


def test_a_manager_that_wants_elevation_stops_rather_than_escalating() -> None:
    entry = manager()
    probe = make_probe(
        which={entry.executable: f"/usr/bin/{entry.executable}"},
        commands={
            tuple(entry.install_argv): CommandResult(
                argv=tuple(entry.install_argv),
                returncode=1,
                stderr="Error: sudo: a password is required",
            )
        },
    )

    with pytest.raises(RuntimeInstallError) as caught:
        install_via_package_manager(entry, probe)

    assert caught.value.failure.kind is FailureKind.ELEVATION_REFUSED
    assert caught.value.failure.retryable is False
    assert "yourself" in (caught.value.failure.detail or "")


def test_a_manager_that_hangs_is_stopped(monkeypatch) -> None:
    entry = manager()
    probe = make_probe(
        which={entry.executable: f"/usr/bin/{entry.executable}"},
        commands={
            tuple(entry.install_argv): CommandResult(
                argv=tuple(entry.install_argv), timed_out=True
            )
        },
    )

    with pytest.raises(RuntimeInstallError) as caught:
        install_via_package_manager(entry, probe)

    assert caught.value.failure.kind is FailureKind.STARTUP_TIMEOUT


def test_a_successful_manager_install_is_qualified_like_anything_else() -> None:
    entry = manager()
    probe = make_probe(
        which={entry.executable: f"/usr/bin/{entry.executable}"},
        commands={tuple(entry.install_argv): ok("installed\n")},
    )
    assert install_via_package_manager(entry, probe)

    # Nothing landed on PATH: the honest answer is "not yet", not "done".
    result = qualify_after_manager_install(entry, probe)
    assert result.compatibility is Compatibility.UNKNOWN
    assert "PATH" in result.next_action


# -- removal -----------------------------------------------------------------


def test_only_a_marked_managed_runtime_can_be_removed(local_paths, tmp_path) -> None:
    from syzygy.local_models.paths import write_ownership

    managed = local_paths.runtime_dir / "b10331"
    managed.mkdir(parents=True)
    (managed / "llama-server").write_text("x")
    write_ownership(local_paths.runtime_dir, kind="runtime", entries=("b10331",))

    unmarked = local_paths.runtime_dir / "b9999"
    unmarked.mkdir()
    outside = tmp_path / "system" / "llama.cpp"
    outside.mkdir(parents=True)

    assert remove_managed_runtime(local_paths, outside) is False
    assert outside.exists()
    assert remove_managed_runtime(local_paths, unmarked) is False
    assert unmarked.exists()
    assert remove_managed_runtime(local_paths, managed) is True
    assert not managed.exists()
