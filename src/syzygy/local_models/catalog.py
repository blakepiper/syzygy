"""Loading and validating the pinned catalog and runtime allowlist
(M16.3a, M16.5a).

Validation runs on load, not at some later "check the catalog" step, and
it is deliberately strict: an entry that is not HTTPS, not digest-pinned,
or not revision-pinned is a `CatalogValidationError`, which fails the test
suite and the build rather than reaching a user as a download. The rules
are the ones M16's safety contract names, restated as code so they cannot
drift from the prose:

* every URL is `https://`;
* every artifact pins a 64-hex `sha256` and a positive exact `size_bytes`;
* every artifact pins an immutable 40-hex `revision`, and its
  `download_url` actually contains that revision - a `/resolve/main/` URL
  with a revision field beside it is the exact mistake this catches;
* the `download_url` host is on the publisher allowlist;
* every profile is computed at Syzygy's pinned context;
* at most one artifact per tier, and a retired artifact has no tier.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any, Final
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from syzygy.local_models.contracts import (
    Backend,
    MachineInventory,
    ModelArtifact,
    ModelTier,
    SupportStatus,
)
from syzygy.local_models.fit import SYZYGY_CONTEXT_TOKENS

CATALOG_SCHEMA: Final = "local-model-catalog-v1"
RUNTIMES_SCHEMA: Final = "local-model-runtimes-v1"

#: Hosts a catalog artifact may be downloaded from. Not a security control
#: on its own - the digest is that - but it stops a typo or a bad merge
#: from pointing an install at somewhere nobody reviewed.
ALLOWED_MODEL_HOSTS: Final = frozenset({"huggingface.co", "cdn-lfs.huggingface.co"})
ALLOWED_RUNTIME_HOSTS: Final = frozenset({"github.com", "objects.githubusercontent.com"})

_HEX40 = 40
_HEX64 = 64


class CatalogValidationError(ValueError):
    """The bundled catalog or runtime manifest violates a pinning rule."""


# -- runtime manifest --------------------------------------------------------


class RuntimeBuild(BaseModel):
    """One allowlisted llama.cpp archive."""

    model_config = ConfigDict(frozen=True)

    os: str
    architectures: tuple[str, ...]
    backend: Backend
    asset: str
    url: str
    sha256: str
    size_bytes: int
    archive_format: str
    notes: str = ""


class PackageManager(BaseModel):
    """A package manager Syzygy will drive *if the user picks that route*.

    `install_argv` is an argument array, always. Nothing in this package
    builds a command string, and nothing here may request elevation - a
    manager that needs `sudo` is reported as unavailable rather than
    escalated to (M16.5b).
    """

    model_config = ConfigDict(frozen=True)

    id: str
    os: str
    executable: str
    formula: str
    install_argv: tuple[str, ...]
    version_argv: tuple[str, ...]
    notes: str = ""


class RuntimeManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_name: str
    project: str
    project_url: str
    license_id: str
    license_url: str
    release_tag: str
    build: int
    release_url: str
    server_executables: tuple[str, ...]
    unified_executables: tuple[str, ...]
    builds: tuple[RuntimeBuild, ...]
    package_managers: tuple[PackageManager, ...]

    def build_for(
        self, *, os_name: str, architecture: str, backend: Backend
    ) -> RuntimeBuild | None:
        arch = architecture.lower()
        for entry in self.builds:
            if entry.os != os_name or entry.backend is not backend:
                continue
            if arch in {item.lower() for item in entry.architectures}:
                return entry
        return None

    def managers_for(self, os_name: str) -> tuple[PackageManager, ...]:
        return tuple(manager for manager in self.package_managers if manager.os == os_name)


class ModelCatalog(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_name: str
    catalog_version: str
    profile_context_tokens: int
    artifacts: tuple[ModelArtifact, ...]

    def by_id(self, artifact_id: str) -> ModelArtifact | None:
        for artifact in self.artifacts:
            if artifact.id == artifact_id:
                return artifact
        return None

    def by_tier(self, tier: ModelTier) -> ModelArtifact | None:
        for artifact in self.artifacts:
            if artifact.tier is tier and artifact.support_status is not SupportStatus.RETIRED:
                return artifact
        return None

    @property
    def offerable(self) -> tuple[ModelArtifact, ...]:
        """Everything a first-time setup may show. Retired entries are not
        offered; an already-installed retired model still runs, and the
        repair route explains why it is gone."""
        return tuple(
            artifact
            for artifact in self.artifacts
            if artifact.support_status is not SupportStatus.RETIRED
        )


# -- loading -----------------------------------------------------------------


def _read_resource(name: str) -> dict[str, Any]:
    text = resources.files("syzygy.resources.local_models").joinpath(name).read_text(
        encoding="utf-8"
    )
    loaded = yaml.safe_load(text)
    if not isinstance(loaded, dict):
        raise CatalogValidationError(f"{name} is not a mapping")
    return loaded


@lru_cache(maxsize=1)
def load_catalog() -> ModelCatalog:
    return parse_catalog(_read_resource("catalog.yaml"))


@lru_cache(maxsize=1)
def load_runtime_manifest() -> RuntimeManifest:
    return parse_runtime_manifest(_read_resource("runtimes.yaml"))


def parse_catalog(payload: dict[str, Any]) -> ModelCatalog:
    if payload.get("schema") != CATALOG_SCHEMA:
        raise CatalogValidationError(
            f"catalog schema {payload.get('schema')!r}, expected {CATALOG_SCHEMA!r}"
        )
    try:
        catalog = ModelCatalog(
            schema_name=CATALOG_SCHEMA,
            catalog_version=str(payload["catalog_version"]),
            profile_context_tokens=int(payload["profile_context_tokens"]),
            artifacts=tuple(
                ModelArtifact.model_validate(entry) for entry in payload.get("artifacts", [])
            ),
        )
    except (KeyError, TypeError, ValidationError) as exc:
        raise CatalogValidationError(f"catalog is malformed: {exc}") from exc
    _validate_catalog(catalog)
    return catalog


def parse_runtime_manifest(payload: dict[str, Any]) -> RuntimeManifest:
    if payload.get("schema") != RUNTIMES_SCHEMA:
        raise CatalogValidationError(
            f"runtime manifest schema {payload.get('schema')!r}, expected {RUNTIMES_SCHEMA!r}"
        )
    try:
        manifest = RuntimeManifest(
            schema_name=RUNTIMES_SCHEMA,
            project=str(payload["project"]),
            project_url=str(payload["project_url"]),
            license_id=str(payload["license_id"]),
            license_url=str(payload["license_url"]),
            release_tag=str(payload["release_tag"]),
            build=int(payload["build"]),
            release_url=str(payload["release_url"]),
            server_executables=tuple(payload["server_executables"]),
            unified_executables=tuple(payload["unified_executables"]),
            builds=tuple(RuntimeBuild.model_validate(entry) for entry in payload["builds"]),
            package_managers=tuple(
                PackageManager.model_validate(entry)
                for entry in payload.get("package_managers", [])
            ),
        )
    except (KeyError, TypeError, ValidationError) as exc:
        raise CatalogValidationError(f"runtime manifest is malformed: {exc}") from exc
    _validate_runtime_manifest(manifest)
    return manifest


# -- validation --------------------------------------------------------------


def _require_https(url: str, *, allowed_hosts: frozenset[str], what: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise CatalogValidationError(f"{what} is not https: {url}")
    if parsed.hostname not in allowed_hosts:
        raise CatalogValidationError(f"{what} host {parsed.hostname!r} is not allowlisted")


def _require_hex(value: str, length: int, what: str) -> None:
    if len(value) != length or any(character not in "0123456789abcdef" for character in value):
        raise CatalogValidationError(f"{what} is not a {length}-character lowercase hex digest")


def _validate_catalog(catalog: ModelCatalog) -> None:
    if catalog.profile_context_tokens != SYZYGY_CONTEXT_TOKENS:
        raise CatalogValidationError(
            f"catalog profiles are computed at {catalog.profile_context_tokens} tokens, "
            f"but Syzygy pins {SYZYGY_CONTEXT_TOKENS}"
        )
    if not catalog.artifacts:
        raise CatalogValidationError("catalog has no artifacts")

    seen_ids: set[str] = set()
    seen_tiers: set[ModelTier] = set()
    for artifact in catalog.artifacts:
        where = f"artifact {artifact.id!r}"
        if artifact.id in seen_ids:
            raise CatalogValidationError(f"duplicate {where}")
        seen_ids.add(artifact.id)

        _require_https(
            artifact.download_url, allowed_hosts=ALLOWED_MODEL_HOSTS, what=f"{where} download_url"
        )
        _require_https(
            artifact.source_url, allowed_hosts=ALLOWED_MODEL_HOSTS, what=f"{where} source_url"
        )
        _require_https(
            artifact.license_url, allowed_hosts=ALLOWED_MODEL_HOSTS, what=f"{where} license_url"
        )
        _require_hex(artifact.sha256, _HEX64, f"{where} sha256")
        _require_hex(artifact.revision, _HEX40, f"{where} revision")

        # The pin has to be in the URL that is actually fetched, or the
        # revision field is decoration and the download follows a branch.
        if artifact.revision not in artifact.download_url:
            raise CatalogValidationError(
                f"{where} download_url does not pin revision {artifact.revision}"
            )
        if artifact.size_bytes <= 0:
            raise CatalogValidationError(f"{where} has no size")
        if artifact.filename not in artifact.download_url:
            raise CatalogValidationError(f"{where} download_url does not end at its filename")

        profile = artifact.memory_profile
        if profile.context_tokens != SYZYGY_CONTEXT_TOKENS:
            raise CatalogValidationError(
                f"{where} profile is at {profile.context_tokens} tokens, "
                f"not Syzygy's {SYZYGY_CONTEXT_TOKENS}"
            )
        if profile.kv_cache_bytes <= 0 or profile.runtime_overhead_bytes <= 0:
            raise CatalogValidationError(f"{where} profile has a non-positive component")
        if artifact.context_tokens != SYZYGY_CONTEXT_TOKENS:
            raise CatalogValidationError(
                f"{where} declares a context Syzygy does not request"
            )
        if artifact.min_runtime_build <= 0:
            raise CatalogValidationError(f"{where} has no minimum runtime build")

        if artifact.tier is not None:
            if artifact.support_status is SupportStatus.RETIRED:
                raise CatalogValidationError(f"{where} is retired but still holds a tier")
            if artifact.tier in seen_tiers:
                raise CatalogValidationError(f"tier {artifact.tier.value} is claimed twice")
            seen_tiers.add(artifact.tier)
        if artifact.support_status is SupportStatus.SUPPORTED and not artifact.evidence_id:
            # M16.3c: only an artifact with committed Syzygy-specific
            # evaluation results may claim full support. Everything else is
            # `provisional`, and the UI says so.
            raise CatalogValidationError(
                f"{where} claims full support without an evidence_id from the "
                "evaluation harness"
            )


def _validate_runtime_manifest(manifest: RuntimeManifest) -> None:
    if not manifest.builds:
        raise CatalogValidationError("runtime manifest has no builds")
    if manifest.build <= 0:
        raise CatalogValidationError("runtime manifest has no build number")
    _require_https(
        manifest.release_url, allowed_hosts=ALLOWED_RUNTIME_HOSTS, what="release_url"
    )

    seen: set[tuple[str, str, Backend]] = set()
    for entry in manifest.builds:
        where = f"runtime build {entry.asset!r}"
        _require_https(entry.url, allowed_hosts=ALLOWED_RUNTIME_HOSTS, what=f"{where} url")
        _require_hex(entry.sha256, _HEX64, f"{where} sha256")
        if entry.size_bytes <= 0:
            raise CatalogValidationError(f"{where} has no size")
        if entry.archive_format not in ("tar.gz", "zip"):
            raise CatalogValidationError(f"{where} has unsupported format {entry.archive_format!r}")
        if manifest.release_tag not in entry.url:
            raise CatalogValidationError(f"{where} url does not pin {manifest.release_tag}")
        for architecture in entry.architectures:
            key = (entry.os, architecture.lower(), entry.backend)
            if key in seen:
                raise CatalogValidationError(f"two builds claim {key}")
            seen.add(key)

    for manager in manifest.package_managers:
        if not manager.install_argv or manager.install_argv[0] != manager.executable:
            raise CatalogValidationError(
                f"package manager {manager.id!r} install command does not start with its executable"
            )
        # Nothing in this package may escalate privileges; a manifest that
        # asks for it is a bug, not a prompt.
        for argv in (manager.install_argv, manager.version_argv):
            if any(token in ("sudo", "runas", "doas", "pkexec") for token in argv):
                raise CatalogValidationError(
                    f"package manager {manager.id!r} requests privilege elevation"
                )


# -- selection ---------------------------------------------------------------


@dataclass(frozen=True)
class RuntimeChoice:
    """What the wizard proposes to install, and why."""

    build: RuntimeBuild | None
    reason: str
    #: Package managers that could do it instead, if the user prefers.
    managers: tuple[PackageManager, ...] = ()


def select_runtime_build(
    inventory: MachineInventory, manifest: RuntimeManifest | None = None
) -> RuntimeChoice:
    """Pick the archive for this machine, preferring acceleration.

    Falls back to the CPU build rather than to nothing: a machine whose
    accelerator has no allowlisted build still gets a working local model,
    just a slower one, and the reason says so.
    """
    manifest = manifest or load_runtime_manifest()
    if not inventory.os_name.known or not inventory.architecture.known:
        return RuntimeChoice(None, "this machine's OS or architecture could not be determined")

    os_name = inventory.os_name.require()
    architecture = inventory.architecture.require()
    managers = manifest.managers_for(os_name)

    # Walk every backend this machine could use, best first. Stopping at
    # the *preferred* one would drop a Linux NVIDIA machine to the
    # processor purely because there is no reviewed Linux CUDA archive,
    # even though its Vulkan driver is right there.
    candidates = inventory.candidate_backends
    for backend in candidates:
        build = manifest.build_for(
            os_name=os_name, architecture=architecture, backend=backend
        )
        if build is None:
            continue
        if backend is Backend.CPU and candidates[0] is not Backend.CPU:
            skipped = ", ".join(
                item.value for item in candidates if item is not Backend.CPU
            )
            return RuntimeChoice(
                build,
                f"no reviewed {skipped} build for {os_name} {architecture}; "
                "the processor build will be used",
                managers,
            )
        if backend is Backend.CPU:
            return RuntimeChoice(build, "no graphics acceleration Syzygy can use", managers)
        if backend is not candidates[0]:
            return RuntimeChoice(
                build,
                f"{backend.value} is the fastest reviewed build for this machine "
                f"(no reviewed {candidates[0].value} build for {os_name} {architecture})",
                managers,
            )
        return RuntimeChoice(build, f"{backend.value} acceleration is available here", managers)

    return RuntimeChoice(
        None, f"no reviewed llama.cpp build for {os_name} {architecture}", managers
    )
