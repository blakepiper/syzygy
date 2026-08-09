"""The `local_model` settings section (M16.1c).

A *section* of `AppPaths.settings_path`, added the way `syzygy.settings`
says to add one: `save_section` read-modify-writes, so this cannot clobber
the `provider` section next to it and the `provider` section cannot clobber
this. The two stay separate on purpose - `provider` answers "what does a
reading call", and this answers "what did the user set up locally". A
managed local model that is configured but not currently active is a real
state, and collapsing the two would lose it.

**Only durable choices live here.** A PID, a leased port, a health check,
download progress, and log paths are all facts about *this run* and belong
in `runtime_state.py`, which is cache. The test for whether something
belongs here: would you want it back after a reboot? A downloaded model's
path, yes. The port it happened to get last Tuesday, no.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from syzygy.local_models.contracts import Backend
from syzygy.settings import load_section, save_section

#: Top-level key in the settings document.
LOCAL_MODEL_SECTION: Final = "local_model"

#: Bumped when a field's meaning changes incompatibly. An older document
#: still loads (unknown fields are ignored, missing ones default), so this
#: exists to let `verification.needs_reverification` notice a jump rather
#: than to gate parsing.
SETTINGS_SCHEMA_VERSION: Final = 1


class ManagementMode(StrEnum):
    #: Syzygy installed the runtime and/or model and starts the server.
    MANAGED = "managed"
    #: The user runs their own server; Syzygy only talks to it.
    EXTERNAL = "external"


class RuntimeRecord(BaseModel):
    """The llama.cpp installation this setup settled on."""

    model_config = ConfigDict(frozen=True)

    #: Absolute path to the executable, or `None` for an external endpoint.
    path: str | None = None
    version: str | None = None
    #: llama.cpp build number, when one could be parsed out of `version`.
    build: int | None = None
    backend: Backend = Backend.CPU
    #: True only when the file lives under `LocalModelPaths.runtime_dir`.
    syzygy_owned: bool = False
    #: For `EXTERNAL`: the base URL to talk to.
    base_url: str | None = None


class ModelRecord(BaseModel):
    """The GGUF this setup settled on."""

    model_config = ConfigDict(frozen=True)

    #: Catalog artifact id, or `None` for a file the user pointed at.
    artifact_id: str | None = None
    catalog_version: str | None = None
    path: str
    sha256: str | None = None
    size_bytes: int | None = None
    #: False for a user-supplied file: referenced, never moved or removed.
    syzygy_owned: bool = False
    #: The `model` string sent to the server, which is also what
    #: `/v1/models` must report back (M16.8a's identity check).
    served_model_id: str = "local"


class LaunchProfile(BaseModel):
    """The exact server configuration the user approved.

    Persisted rather than recomputed so that a machine whose free memory
    changed overnight does not silently get different `--n-gpu-layers` than
    the profile shown on the consent screen.
    """

    model_config = ConfigDict(frozen=True)

    context_tokens: int
    max_output_tokens: int
    threads: int | None = None
    #: Layers offloaded to the accelerator. `0` is CPU-only; `None` means
    #: "let llama.cpp decide", which Syzygy avoids on a first setup.
    gpu_layers: int | None = None


class LicenseAcceptance(BaseModel):
    """Recorded against the *exact* artifact and license revision, so a
    catalog update that changes terms asks again rather than inheriting a
    consent given to different terms (M16.6a)."""

    model_config = ConfigDict(frozen=True)

    artifact_id: str
    license_id: str
    license_url: str
    catalog_version: str
    accepted_at_utc: str


class VerificationRecord(BaseModel):
    """Evidence that the smoke test passed, and against what.

    Every version that could invalidate it is recorded, because M16.8c's
    rule is that a *future upgrade* must know when verification has to run
    again - and it cannot know that from a boolean.
    """

    model_config = ConfigDict(frozen=True)

    verified_at_utc: str
    runtime_version: str | None = None
    artifact_id: str | None = None
    catalog_version: str | None = None
    prompt_version: str
    served_model_id: str
    #: Digest of the model file as verified, so digest drift is detectable
    #: at startup without re-hashing gigabytes (size + mtime do the cheap
    #: check; this is what a full `--deep` check compares against).
    model_sha256: str | None = None


class LocalModelSettings(BaseModel):
    """The whole `local_model` section. Every field optional: a partially
    completed setup must round-trip, or "resume" is a lie."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = SETTINGS_SCHEMA_VERSION
    mode: ManagementMode | None = None
    runtime: RuntimeRecord | None = None
    model: ModelRecord | None = None
    launch: LaunchProfile | None = None
    licenses: tuple[LicenseAcceptance, ...] = Field(default_factory=tuple)
    last_verification: VerificationRecord | None = None

    def with_license(self, acceptance: LicenseAcceptance) -> LocalModelSettings:
        """Add or replace the acceptance for one artifact."""
        others = tuple(
            item for item in self.licenses if item.artifact_id != acceptance.artifact_id
        )
        return self.model_copy(update={"licenses": (*others, acceptance)})

    def accepted_license(
        self, artifact_id: str, license_id: str, catalog_version: str
    ) -> bool:
        """Has this exact artifact, at this exact license and catalog
        revision, been accepted? Any drift means no."""
        return any(
            item.artifact_id == artifact_id
            and item.license_id == license_id
            and item.catalog_version == catalog_version
            for item in self.licenses
        )


def load_local_model_settings(path: Path) -> LocalModelSettings:
    """Never raises. A corrupt or foreign section reads as "nothing set
    up", which every caller already handles by offering setup."""
    section = load_section(path, LOCAL_MODEL_SECTION)
    if not section:
        return LocalModelSettings()
    try:
        return LocalModelSettings.model_validate(section)
    except ValueError:
        return LocalModelSettings()


def save_local_model_settings(path: Path, settings: LocalModelSettings) -> None:
    save_section(path, LOCAL_MODEL_SECTION, settings.model_dump(mode="json"))


def clear_local_model_settings(path: Path) -> None:
    """Forget the local setup entirely. Does *not* delete any file - that
    is `model_install.remove_managed_model`'s job, deliberately separate
    and separately confirmed (M16.6e)."""
    save_section(path, LOCAL_MODEL_SECTION, None)
