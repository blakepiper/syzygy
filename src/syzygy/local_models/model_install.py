"""Getting the model file, and owning it responsibly (M16.6).

Three distinct relationships Syzygy can have with a GGUF file, and they
are never blurred:

* **managed** - Syzygy downloaded it from the catalog into
  `LocalModelPaths.models_dir` and wrote an ownership marker. This is the
  only kind it may ever delete.
* **external** - the user pointed at a file they already had. Syzygy
  reads its header, checks whether it fits, and refers to it by path. It
  is never moved, rewritten, or removed, and neither is the directory it
  lives in - including another application's Hugging Face cache.
* **absent** - nothing set up. A supported state; the ritual runs on
  `FixtureProvider`.

Discovery of existing files is *only* through a path the user chooses.
There is no home-directory crawl: a background scan of someone's disk for
model files is not something an astrology program should do, and the
"found 40 GB of models" screen it would produce is not worth it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from syzygy.local_models.catalog import ModelCatalog, load_catalog
from syzygy.local_models.contracts import (
    FailureKind,
    FitEstimate,
    FitVerdict,
    MachineInventory,
    ModelArtifact,
    RecoveryAction,
    SetupFailure,
)
from syzygy.local_models.download import (
    CancelCheck,
    DownloadError,
    DownloadRequest,
    ProgressCallback,
    download_verified,
    free_disk_bytes,
    verify_digest,
)
from syzygy.local_models.fit import SYZYGY_CONTEXT_TOKENS, estimate_fit, memory_budget
from syzygy.local_models.gguf import GgufError, GgufMetadata, inspect_gguf_file
from syzygy.local_models.paths import (
    LocalModelPaths,
    forget_ownership,
    is_syzygy_owned,
    read_ownership,
)
from syzygy.local_models.settings import (
    LicenseAcceptance,
    LocalModelSettings,
    ModelRecord,
    load_local_model_settings,
    save_local_model_settings,
)

#: GGUF architectures llama.cpp's server can actually run for Syzygy's
#: purposes. Not an allowlist of *models* - a new Qwen or Llama revision
#: needs no change here - but a guard against pointing the wizard at an
#: embedding model or a vision projector and getting a baffling failure at
#: reading time.
_UNSUPPORTED_ARCHITECTURES = frozenset({"bert", "nomic-bert", "clip", "t5encoder"})


class ModelInstallError(Exception):
    def __init__(self, failure: SetupFailure) -> None:
        super().__init__(failure.message)
        self.failure = failure


@dataclass(frozen=True)
class ModelDownloadPlan:
    """The receipt shown before a single byte is fetched (M16.6a)."""

    artifact: ModelArtifact
    catalog_version: str
    destination: Path
    fit: FitEstimate
    #: True when this exact artifact at this exact licence revision has not
    #: been accepted yet.
    needs_license_acceptance: bool
    #: Bytes over the network. Zero when a verified copy is already here.
    download_bytes: int
    #: Peak extra disk during the download (the partial file).
    temporary_bytes: int
    #: What it occupies once finished.
    final_bytes: int
    free_disk_bytes: int | None

    @property
    def already_present(self) -> bool:
        return self.download_bytes == 0

    @property
    def purpose(self) -> str:
        return (
            "This model writes the two interpretations of your daily reading, and the "
            "chart and sky summaries. It never chooses your card and never calculates "
            "your chart - Syzygy has already fixed both before the model sees anything."
        )


def plan_model_download(
    artifact: ModelArtifact,
    inventory: MachineInventory,
    paths: LocalModelPaths,
    settings_path: Path,
    *,
    catalog: ModelCatalog | None = None,
) -> ModelDownloadPlan:
    catalog = catalog or load_catalog()
    settings = load_local_model_settings(settings_path)
    destination = paths.models_dir / artifact.filename

    present = destination.exists() and destination.stat().st_size == artifact.size_bytes
    fit = estimate_fit(artifact, inventory)

    return ModelDownloadPlan(
        artifact=artifact,
        catalog_version=catalog.catalog_version,
        destination=destination,
        fit=fit,
        needs_license_acceptance=not settings.accepted_license(
            artifact.id, artifact.license_id, catalog.catalog_version
        ),
        download_bytes=0 if present else artifact.size_bytes,
        temporary_bytes=0 if present else artifact.size_bytes,
        final_bytes=artifact.size_bytes,
        free_disk_bytes=free_disk_bytes(paths.models_dir),
    )


def accept_license(settings_path: Path, plan: ModelDownloadPlan) -> LocalModelSettings:
    """Record acceptance against the exact artifact and catalog revision.

    Versioned deliberately: if a catalog update changes an artifact's terms
    or its licence URL, `LocalModelSettings.accepted_license` stops
    matching and the user is asked again, rather than a consent given to
    one set of terms silently covering another.
    """
    settings = load_local_model_settings(settings_path)
    updated = settings.with_license(
        LicenseAcceptance(
            artifact_id=plan.artifact.id,
            license_id=plan.artifact.license_id,
            license_url=plan.artifact.license_url,
            catalog_version=plan.catalog_version,
            accepted_at_utc=datetime.now(UTC).isoformat(timespec="seconds"),
        )
    )
    save_local_model_settings(settings_path, updated)
    return updated


def download_model(
    plan: ModelDownloadPlan,
    paths: LocalModelPaths,
    settings_path: Path,
    *,
    on_progress: ProgressCallback | None = None,
    cancel: CancelCheck | None = None,
) -> Path:
    """Fetch the artifact. Refuses without a recorded licence acceptance,
    and refuses a fit verdict of insufficient disk."""
    settings = load_local_model_settings(settings_path)
    if not settings.accepted_license(
        plan.artifact.id, plan.artifact.license_id, plan.catalog_version
    ):
        raise ModelInstallError(
            SetupFailure(
                kind=FailureKind.TERMS_NOT_ACCEPTED,
                message="The model's licence hasn't been accepted yet.",
                detail=f"{plan.artifact.license_id}: {plan.artifact.license_url}",
                actions=(RecoveryAction.OPEN_LICENSE, RecoveryAction.SKIP_FOR_NOW),
                retryable=False,
            )
        )
    if plan.fit.verdict is FitVerdict.INSUFFICIENT_DISK:
        raise ModelInstallError(
            SetupFailure(
                kind=FailureKind.INSUFFICIENT_DISK,
                message="There isn't enough free disk space for this model.",
                detail=plan.fit.reason,
                actions=(RecoveryAction.FREE_DISK_SPACE, RecoveryAction.CHOOSE_SMALLER),
                retryable=False,
            )
        )

    try:
        path = download_verified(
            DownloadRequest(
                key=plan.artifact.id,
                url=plan.artifact.download_url,
                sha256=plan.artifact.sha256,
                expected_bytes=plan.artifact.size_bytes,
                destination=plan.destination,
                kind="model",
            ),
            paths,
            on_progress=on_progress,
            cancel=cancel,
        )
    except DownloadError as exc:
        raise ModelInstallError(exc.failure) from exc

    # A downloaded file that is not a GGUF Syzygy understands is a catalog
    # bug, and it is better caught here - with the file in hand - than at
    # the first reading.
    try:
        inspect_gguf_file(path)
    except GgufError as exc:
        path.unlink(missing_ok=True)
        forget_ownership(paths.models_dir, plan.destination.name)
        raise ModelInstallError(
            SetupFailure(
                kind=FailureKind.UPSTREAM_CHANGED,
                message="The downloaded file isn't a model Syzygy can read.",
                detail=str(exc),
                actions=(RecoveryAction.RETRY, RecoveryAction.COPY_DIAGNOSTICS),
            )
        ) from exc

    save_local_model_settings(
        settings_path,
        settings.model_copy(
            update={
                "model": ModelRecord(
                    artifact_id=plan.artifact.id,
                    catalog_version=plan.catalog_version,
                    path=str(path),
                    sha256=plan.artifact.sha256,
                    size_bytes=plan.artifact.size_bytes,
                    syzygy_owned=True,
                    served_model_id=plan.artifact.id,
                )
            }
        ),
    )
    return path


# -- external files ----------------------------------------------------------


@dataclass(frozen=True)
class ExternalModelReport:
    """What Syzygy learned about a file the user pointed at."""

    path: Path
    usable: bool
    reason: str
    size_bytes: int | None = None
    metadata: GgufMetadata | None = None
    #: Estimated memory need at Syzygy's context, when computable.
    estimated_memory_bytes: int | None = None
    fits: bool | None = None


def inspect_external_model(
    path: Path, inventory: MachineInventory
) -> ExternalModelReport:
    """Read a user-chosen `.gguf`'s header and judge it, without loading
    weights and without touching the file in any way."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        return ExternalModelReport(path=path, usable=False, reason=f"can't read that file: {exc}")

    if path.suffix.lower() != ".gguf":
        return ExternalModelReport(
            path=path,
            usable=False,
            reason="Syzygy needs a .gguf model file. Other formats aren't supported.",
            size_bytes=size,
        )

    try:
        metadata = inspect_gguf_file(path)
    except GgufError as exc:
        return ExternalModelReport(path=path, usable=False, reason=str(exc), size_bytes=size)

    if metadata.architecture.lower() in _UNSUPPORTED_ARCHITECTURES:
        return ExternalModelReport(
            path=path,
            usable=False,
            reason=(
                f"That's a {metadata.architecture} model - it doesn't write text, so "
                "Syzygy can't use it for readings."
            ),
            size_bytes=size,
            metadata=metadata,
        )
    if not metadata.has_chat_template:
        return ExternalModelReport(
            path=path,
            usable=False,
            reason=(
                "That model file has no chat template, so a server can't turn Syzygy's "
                "prompt into something it understands."
            ),
            size_bytes=size,
            metadata=metadata,
        )
    if metadata.context_length is not None and metadata.context_length < SYZYGY_CONTEXT_TOKENS:
        return ExternalModelReport(
            path=path,
            usable=False,
            reason=(
                f"That model was trained for {metadata.context_length} tokens of context; "
                f"Syzygy asks for {SYZYGY_CONTEXT_TOKENS}."
            ),
            size_bytes=size,
            metadata=metadata,
        )

    kv_cache = metadata.kv_cache_bytes(SYZYGY_CONTEXT_TOKENS)
    if kv_cache is None:
        return ExternalModelReport(
            path=path,
            usable=True,
            reason=(
                "Syzygy can use this, but couldn't work out how much memory it needs - "
                "the file doesn't describe its attention shape."
            ),
            size_bytes=size,
            metadata=metadata,
        )

    # Same shape as the catalog estimate: weights + KV cache + the same
    # documented runtime-overhead rule, so an external file and a catalog
    # entry are judged by identical arithmetic.
    required = size + kv_cache + (1024**3 + int(size * 0.08))
    budget, _, _, budget_reason = memory_budget(inventory)
    fits = None if budget is None else required <= budget
    return ExternalModelReport(
        path=path,
        usable=True,
        reason=(
            f"Needs about {required / 1024**3:.1f} GB"
            + (
                f", and about {budget / 1024**3:.1f} GB is available ({budget_reason})."
                if budget is not None
                else ", and this computer's memory could not be determined."
            )
        ),
        size_bytes=size,
        metadata=metadata,
        estimated_memory_bytes=required,
        fits=fits,
    )


def use_external_model(
    settings_path: Path, report: ExternalModelReport, *, served_model_id: str = "local"
) -> None:
    """Point the managed setup at a file the user already had. Records it
    as *not* Syzygy-owned, which is what stops cleanup ever touching it."""
    settings = load_local_model_settings(settings_path)
    save_local_model_settings(
        settings_path,
        settings.model_copy(
            update={
                "model": ModelRecord(
                    artifact_id=None,
                    catalog_version=None,
                    path=str(report.path),
                    sha256=None,
                    size_bytes=report.size_bytes,
                    syzygy_owned=False,
                    served_model_id=served_model_id,
                )
            }
        ),
    )


# -- manage local files ------------------------------------------------------


@dataclass(frozen=True)
class LocalModelFile:
    """One row of **Manage local files** (M16.6e)."""

    path: Path
    size_bytes: int
    #: True only if the ownership marker proves Syzygy put it there.
    syzygy_owned: bool
    #: Catalog artifact id, when known.
    artifact_id: str | None
    #: "verified", "not verified", or "digest unknown".
    verification: str
    #: True when this is the model the current setup would start.
    in_use: bool
    last_used_at_utc: str | None = None

    @property
    def removable(self) -> bool:
        """Only a Syzygy-owned file may be removed, and never the one a
        running server currently has open (the caller stops it first)."""
        return self.syzygy_owned


def list_local_models(
    paths: LocalModelPaths, settings_path: Path, *, deep_verify: bool = False
) -> tuple[LocalModelFile, ...]:
    """Managed files plus whatever external file the settings reference.

    `deep_verify` re-hashes every managed file, which is minutes of I/O on
    a 9 GB model - it is the explicit `--deep` option, never the default.
    """
    settings = load_local_model_settings(settings_path)
    configured = settings.model
    marker = read_ownership(paths.models_dir)
    known = set(marker.entries) if marker and marker.recognized else set()

    rows: list[LocalModelFile] = []
    seen: set[str] = set()

    if paths.models_dir.exists():
        for candidate in sorted(paths.models_dir.glob("*.gguf")):
            seen.add(str(candidate.resolve()))
            owned = candidate.name in known and is_syzygy_owned(paths, candidate)
            artifact_id = _artifact_id_for(candidate, settings)
            rows.append(
                LocalModelFile(
                    path=candidate,
                    size_bytes=_size(candidate),
                    syzygy_owned=owned,
                    artifact_id=artifact_id,
                    verification=_verification(candidate, settings, deep_verify=deep_verify),
                    in_use=configured is not None and configured.path == str(candidate),
                )
            )

    if configured is not None:
        external = Path(configured.path)
        try:
            resolved = str(external.resolve())
        except OSError:
            resolved = str(external)
        if resolved not in seen:
            rows.append(
                LocalModelFile(
                    path=external,
                    size_bytes=_size(external),
                    syzygy_owned=False,
                    artifact_id=configured.artifact_id,
                    verification=(
                        "not found" if not external.exists() else "external - not verified"
                    ),
                    in_use=True,
                )
            )
    return tuple(rows)


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _artifact_id_for(path: Path, settings: LocalModelSettings) -> str | None:
    if settings.model is not None and settings.model.path == str(path):
        return settings.model.artifact_id
    catalog = load_catalog()
    for artifact in catalog.artifacts:
        if artifact.filename == path.name:
            return artifact.id
    return None


def _verification(path: Path, settings: LocalModelSettings, *, deep_verify: bool) -> str:
    record = settings.model
    expected = record.sha256 if record is not None and record.path == str(path) else None
    if expected is None:
        catalog = load_catalog()
        for artifact in catalog.artifacts:
            if artifact.filename == path.name:
                expected = artifact.sha256
                break
    if expected is None:
        return "digest unknown"
    if not deep_verify:
        return "size matches" if _size(path) > 0 else "empty"
    return "verified" if verify_digest(path, expected) else "DOES NOT MATCH"


def remove_managed_model(paths: LocalModelPaths, target: Path, settings_path: Path) -> bool:
    """Delete one Syzygy-owned model file, and keep settings consistent.

    Returns False - and deletes nothing - for anything Syzygy cannot prove
    it owns. The caller is responsible for stopping a running server first;
    `supervisor.stop` is a separate, separately-confirmed action.
    """
    if not is_syzygy_owned(paths, target):
        return False
    try:
        target.unlink()
    except OSError:
        return False
    forget_ownership(paths.models_dir, target.name)

    settings = load_local_model_settings(settings_path)
    if settings.model is not None and settings.model.path == str(target):
        # The configured model just went away: drop the record and the
        # verification that depended on it, so startup offers repair
        # rather than trying to start a server on a missing file.
        save_local_model_settings(
            settings_path,
            settings.model_copy(update={"model": None, "last_verification": None}),
        )
    return True
