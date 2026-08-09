"""Runtime state: everything that is true only right now (M16.1c/M16.7d).

Separate document, separate lifetime, from `settings.py`. This one holds
the PID, the leased port, the last health check, and in-flight download
progress - facts that a reboot invalidates and that no user ever chose.
Deleting this file loses nothing but a resumable download's bookkeeping.

**Why a PID is never enough.** A recorded PID after a crash may belong to
an unrelated process that reused the number, and killing that would be
inexcusable. So a managed server records four things - PID, the executable
path it was launched from, a start token Syzygy generated, and the launch
metadata - and `ProcessIdentity.matches` requires all of them to line up
against the live process before anything is signalled. When they do not,
the state is stale and gets cleaned up rather than acted on.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from syzygy.local_models.paths import atomic_write_json, read_json


class ProcessIdentity(BaseModel):
    """Enough to be sure a live PID is the server Syzygy started."""

    model_config = ConfigDict(frozen=True)

    pid: int
    #: Resolved path of the binary that was launched.
    executable: str
    #: Random per-launch token, also passed to the child in its
    #: environment, so a probe can confirm identity even where reading
    #: another process's command line is not permitted.
    start_token: str
    started_at_utc: str
    port: int
    model_path: str
    log_path: str | None = None

    def matches(self, *, executable: str, port: int, model_path: str) -> bool:
        return (
            self.executable == executable
            and self.port == port
            and self.model_path == model_path
        )


class DownloadProgress(BaseModel):
    """One in-flight or resumable download.

    `etag`/`last_modified` are what make a resume safe: a partial file is
    only ever continued when the server still reports the same validator
    it did when the bytes were first written. Different validator means a
    changed upstream artifact, which is a `FailureKind.UPSTREAM_CHANGED`,
    not something to append to.
    """

    model_config = ConfigDict(frozen=True)

    key: str
    url: str
    partial_path: str
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    etag: str | None = None
    last_modified: str | None = None
    updated_at_utc: str = ""


class HealthRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    checked_at_utc: str
    healthy: bool
    detail: str | None = None


class LocalRuntimeState(BaseModel):
    model_config = ConfigDict(frozen=True)

    process: ProcessIdentity | None = None
    health: HealthRecord | None = None
    downloads: tuple[DownloadProgress, ...] = Field(default_factory=tuple)

    def with_download(self, progress: DownloadProgress) -> LocalRuntimeState:
        others = tuple(item for item in self.downloads if item.key != progress.key)
        return self.model_copy(update={"downloads": (*others, progress)})

    def without_download(self, key: str) -> LocalRuntimeState:
        return self.model_copy(
            update={"downloads": tuple(item for item in self.downloads if item.key != key)}
        )

    def download(self, key: str) -> DownloadProgress | None:
        for item in self.downloads:
            if item.key == key:
                return item
        return None


def load_runtime_state(path: Path) -> LocalRuntimeState:
    """Never raises - a corrupt cache is an empty cache."""
    payload = read_json(path)
    if not payload:
        return LocalRuntimeState()
    try:
        return LocalRuntimeState.model_validate(payload)
    except ValueError:
        return LocalRuntimeState()


def save_runtime_state(path: Path, state: LocalRuntimeState) -> None:
    atomic_write_json(path, state.model_dump(mode="json"))


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
