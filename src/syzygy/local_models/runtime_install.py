"""Acquiring the model runner, with consent and without surprises (M16.5).

Two routes, and the user picks:

* **the pinned official archive** - downloaded, digest-verified, unpacked
  under the checks in `archives`, qualified with the same version probe
  used on anything already installed, and only then promoted into place;
* **a package manager they already have** - Homebrew, winget, Nix - run as
  an argument array, never through a shell, and never with elevation. If
  the command turns out to need administrator rights, the flow stops and
  says so rather than escalating.

Neither route ever compiles from source, pipes a remote script into a
shell, or runs anything that has not been verified first.

**Rollback.** A managed runtime is replaced by extracting beside the old
one and swapping directories only after the new one answers a version
query. If it does not, the previous directory is put back exactly as it
was. An upgrade that fails leaves a working installation, which is the
whole reason updates are user-initiated and go through this path.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from syzygy.local_models.archives import (
    ArchiveError,
    extract_archive,
    find_executable,
    make_executable,
)
from syzygy.local_models.catalog import (
    PackageManager,
    RuntimeBuild,
    RuntimeManifest,
    load_runtime_manifest,
    select_runtime_build,
)
from syzygy.local_models.contracts import (
    Backend,
    Compatibility,
    FailureKind,
    MachineInventory,
    RecoveryAction,
    RuntimeCandidate,
    RuntimeCapabilities,
    RuntimeKind,
    RuntimeSource,
    SetupFailure,
)
from syzygy.local_models.diagnostics import redact, redact_argv
from syzygy.local_models.discovery import qualify_binary
from syzygy.local_models.download import (
    CancelCheck,
    DownloadError,
    DownloadRequest,
    ProgressCallback,
    download_verified,
)
from syzygy.local_models.paths import LocalModelPaths, write_ownership
from syzygy.local_models.probe import Probe

#: Strings a package manager prints when it wants a password or an
#: administrator token. Matching text is unavoidable here - there is no
#: structured signal - so the consequence of a match is conservative:
#: stop and explain, never answer the prompt.
_ELEVATION_MARKERS = (
    "sudo",
    "password for",
    "administrator",
    "requires elevation",
    "run as administrator",
    "permission denied",
    "access is denied",
)


class RuntimeInstallError(Exception):
    def __init__(self, failure: SetupFailure) -> None:
        super().__init__(failure.message)
        self.failure = failure


@dataclass(frozen=True)
class InstallPlan:
    """Exactly what will happen, shown before anything happens (M16.5b).

    Every field on here appears on the consent screen. If a value is not
    on this object, it is not something the install does - which is the
    property that makes the receipt trustworthy rather than decorative.
    """

    build: RuntimeBuild
    manifest: RuntimeManifest
    #: Where the unpacked runtime will live.
    install_dir: Path
    #: Bytes to download, and the archive's own name.
    download_bytes: int
    #: Roughly what it occupies once unpacked. The archives are already
    #: compressed binaries, so this is the download size with a margin, not
    #: a compression-ratio guess.
    disk_bytes: int
    backend: Backend
    reason: str
    #: Package managers that could do this instead, if the user prefers.
    managers: tuple[PackageManager, ...] = ()

    @property
    def source_url(self) -> str:
        return self.build.url

    @property
    def version(self) -> str:
        return self.manifest.release_tag


def plan_runtime_install(
    inventory: MachineInventory,
    paths: LocalModelPaths,
    *,
    manifest: RuntimeManifest | None = None,
) -> InstallPlan:
    """Decide which archive this machine gets. Raises if there is none."""
    manifest = manifest or load_runtime_manifest()
    choice = select_runtime_build(inventory, manifest)
    if choice.build is None:
        raise RuntimeInstallError(
            SetupFailure(
                kind=FailureKind.UNSUPPORTED_PLATFORM,
                message="Syzygy doesn't have a reviewed model runner for this system.",
                detail=choice.reason,
                actions=(RecoveryAction.USE_EXISTING_SERVER, RecoveryAction.SKIP_FOR_NOW),
                retryable=False,
            )
        )
    return InstallPlan(
        build=choice.build,
        manifest=manifest,
        install_dir=paths.runtime_dir / manifest.release_tag,
        download_bytes=choice.build.size_bytes,
        disk_bytes=int(choice.build.size_bytes * 1.6),
        backend=choice.build.backend,
        reason=choice.reason,
        managers=choice.managers,
    )


def install_runtime_archive(
    plan: InstallPlan,
    paths: LocalModelPaths,
    probe: Probe,
    *,
    on_progress: ProgressCallback | None = None,
    cancel: CancelCheck | None = None,
) -> RuntimeCapabilities:
    """Download, verify, unpack, qualify, and promote. Returns the
    capabilities of the runtime now installed."""
    paths.ensure_exists()

    archive_path = paths.partial_dir / plan.build.asset
    try:
        download_verified(
            DownloadRequest(
                key=f"runtime-{plan.manifest.release_tag}-{plan.build.backend.value}",
                url=plan.build.url,
                sha256=plan.build.sha256,
                expected_bytes=plan.build.size_bytes,
                destination=archive_path,
                kind="runtime-archive",
            ),
            paths,
            on_progress=on_progress,
            cancel=cancel,
        )
    except DownloadError as exc:
        raise RuntimeInstallError(exc.failure) from exc

    staging = paths.runtime_dir / f".staging-{plan.manifest.release_tag}"
    shutil.rmtree(staging, ignore_errors=True)
    try:
        extract_archive(archive_path, staging, archive_format=plan.build.archive_format)
    except ArchiveError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise RuntimeInstallError(exc.failure) from exc
    finally:
        # The archive is worth nothing once unpacked, and it is the largest
        # thing in `partial/`.
        archive_path.unlink(missing_ok=True)

    executable = find_executable(staging, plan.manifest.server_executables)
    if executable is None:
        shutil.rmtree(staging, ignore_errors=True)
        raise RuntimeInstallError(
            SetupFailure(
                kind=FailureKind.RUNTIME_UNSUITABLE,
                message="The downloaded runner didn't contain the server program.",
                detail=(
                    "expected one of "
                    f"{', '.join(plan.manifest.server_executables)} inside "
                    f"{plan.build.asset}"
                ),
                actions=(RecoveryAction.RETRY, RecoveryAction.COPY_DIAGNOSTICS),
            )
        )
    make_executable(executable)

    # Qualify *before* promoting, so a broken download never replaces a
    # working installation.
    staged_candidate = RuntimeCandidate(
        kind=RuntimeKind.BINARY,
        source=RuntimeSource.MANAGED,
        locator=str(executable),
        resolved_path=str(executable),
        syzygy_owned=True,
        notes=("just installed by Syzygy",),
    )
    capabilities = qualify_binary(
        staged_candidate, probe, manifest=plan.manifest, minimum_build=plan.manifest.build
    )
    if not capabilities.usable:
        shutil.rmtree(staging, ignore_errors=True)
        raise RuntimeInstallError(
            SetupFailure(
                kind=FailureKind.RUNTIME_UNSUITABLE,
                message="The runner Syzygy downloaded didn't start correctly.",
                detail=capabilities.next_action,
                actions=(RecoveryAction.RETRY, RecoveryAction.COPY_DIAGNOSTICS),
            )
        )

    final = _promote(staging, plan.install_dir)
    promoted = find_executable(final, plan.manifest.server_executables)
    if promoted is None:  # pragma: no cover - would mean the rename lost files
        raise RuntimeInstallError(
            SetupFailure(
                kind=FailureKind.RUNTIME_UNSUITABLE,
                message="The runner disappeared while being installed.",
                actions=(RecoveryAction.RETRY,),
            )
        )
    make_executable(promoted)
    write_ownership(
        paths.runtime_dir,
        kind="runtime",
        entries=(final.name,),
        identity=plan.manifest.release_tag,
    )

    return capabilities.model_copy(
        update={
            "candidate": capabilities.candidate.model_copy(
                update={"locator": str(promoted), "resolved_path": str(promoted)}
            ),
            "backend": plan.build.backend,
        }
    )


def _promote(staging: Path, final: Path) -> Path:
    """Swap `staging` into `final`, keeping the previous copy until the
    swap has actually happened."""
    rollback = final.with_name(final.name + ".rollback")
    shutil.rmtree(rollback, ignore_errors=True)
    had_previous = final.exists()
    if had_previous:
        final.rename(rollback)
    try:
        staging.rename(final)
    except OSError:
        if had_previous:
            rollback.rename(final)
        raise
    shutil.rmtree(rollback, ignore_errors=True)
    return final


# -- package-manager route ---------------------------------------------------


@dataclass(frozen=True)
class ManagerAvailability:
    manager: PackageManager
    available: bool
    version: str | None
    note: str


def check_package_manager(manager: PackageManager, probe: Probe) -> ManagerAvailability:
    """Is this manager present? Syzygy never installs a package manager -
    that is a much bigger change to someone's machine than installing one
    program, and it is not what they asked for."""
    if probe.which(manager.executable) is None:
        return ManagerAvailability(
            manager, False, None, f"{manager.executable} isn't installed on this computer"
        )
    result = probe.run(manager.version_argv, 20.0)
    if not result.ok:
        return ManagerAvailability(manager, False, None, redact(result.failure_note))
    version = (result.stdout or result.stderr).strip().splitlines()
    return ManagerAvailability(
        manager, True, version[0] if version else None, manager.notes
    )


def install_via_package_manager(
    manager: PackageManager,
    probe: Probe,
    *,
    timeout: float = 900.0,
) -> str:
    """Run the manager's install command and return its (redacted) output.

    Raises `RuntimeInstallError` if the manager is missing, if the command
    fails, or if its output suggests it wanted elevation. Syzygy does not
    answer a password prompt, and `stdin` is closed, so a command that
    wants one fails quickly instead of hanging on a terminal nobody is
    watching.
    """
    if probe.which(manager.executable) is None:
        raise RuntimeInstallError(
            SetupFailure(
                kind=FailureKind.PACKAGE_MANAGER_MISSING,
                message=f"{manager.executable} isn't installed on this computer.",
                detail=manager.notes,
                actions=(RecoveryAction.RETRY, RecoveryAction.SKIP_FOR_NOW),
                retryable=False,
            )
        )

    result = probe.run(manager.install_argv, timeout)
    combined = redact(f"{result.stdout}\n{result.stderr}")

    if result.timed_out:
        raise RuntimeInstallError(
            SetupFailure(
                kind=FailureKind.STARTUP_TIMEOUT,
                message=f"{manager.executable} took too long and was stopped.",
                detail=redact_argv(manager.install_argv),
                actions=(RecoveryAction.RETRY, RecoveryAction.SKIP_FOR_NOW),
            )
        )
    if not result.ok:
        lowered = combined.lower()
        if any(marker in lowered for marker in _ELEVATION_MARKERS):
            raise RuntimeInstallError(
                SetupFailure(
                    kind=FailureKind.ELEVATION_REFUSED,
                    message=(
                        f"{manager.executable} asked for administrator permission. "
                        "Syzygy won't do that on your behalf."
                    ),
                    detail=(
                        f"Run this yourself if you want to: {redact_argv(manager.install_argv)}"
                    ),
                    actions=(RecoveryAction.RETRY, RecoveryAction.SKIP_FOR_NOW),
                    retryable=False,
                )
            )
        raise RuntimeInstallError(
            SetupFailure(
                kind=FailureKind.RUNTIME_UNSUITABLE,
                message=f"{manager.executable} couldn't install the model runner.",
                detail=combined[-2000:],
                actions=(RecoveryAction.RETRY, RecoveryAction.COPY_DIAGNOSTICS),
            )
        )
    return combined


def qualify_after_manager_install(
    manager: PackageManager,
    probe: Probe,
    *,
    manifest: RuntimeManifest | None = None,
) -> RuntimeCapabilities:
    """After a manager install, find what it put on `PATH` and qualify it
    through the same probe as anything else (M16.5d)."""
    manifest = manifest or load_runtime_manifest()
    for name in (*manifest.server_executables, *manifest.unified_executables):
        found = probe.which(name)
        if not found:
            continue
        candidate = RuntimeCandidate(
            kind=RuntimeKind.BINARY,
            source=RuntimeSource.PATH,
            locator=found,
            resolved_path=str(Path(found).resolve()),
            notes=(f"installed by {manager.executable}",),
        )
        return qualify_binary(candidate, probe, manifest=manifest)
    return RuntimeCapabilities(
        candidate=RuntimeCandidate(
            kind=RuntimeKind.BINARY, source=RuntimeSource.PATH, locator=manager.formula
        ),
        compatibility=Compatibility.UNKNOWN,
        next_action=(
            f"{manager.executable} reported success, but the server program isn't on "
            "PATH yet. Opening a new terminal usually fixes this."
        ),
    )


def remove_managed_runtime(paths: LocalModelPaths, directory: Path) -> bool:
    """Delete a runtime Syzygy installed. Refuses anything else (M16.6e).

    Directory-level rather than file-level, because that is what was
    installed: the marker in `runtime/` names the version directory.
    """
    from syzygy.local_models.paths import forget_ownership, read_ownership

    if not paths.contains(directory):
        return False
    marker = read_ownership(paths.runtime_dir)
    if marker is None or not marker.recognized or directory.name not in marker.entries:
        return False
    shutil.rmtree(directory, ignore_errors=True)
    forget_ownership(paths.runtime_dir, directory.name)
    return not directory.exists()
