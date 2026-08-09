"""One download pipeline, used for both the runtime and the model
(M16.5c, M16.6b).

The rules are the same for a 16 MB archive and a 9 GB weight file, so
there is one implementation of them:

* bytes land in `LocalModelPaths.partial_dir`, never at the destination,
  so a half-finished file can never be executed or loaded;
* the digest is verified **before** anything is extracted, executed, or
  promoted, and the file is promoted with `os.replace`, which is atomic;
* a resume only continues a partial whose upstream validator (`ETag` /
  `Last-Modified`) still matches what was recorded when the first byte
  arrived. A changed validator is `UPSTREAM_CHANGED`, not something to
  append to - appending to it would produce a corrupt file that fails the
  digest check much later and for no visible reason;
* redirects are bounded, every phase has a timeout, and cancellation is
  checked every chunk so **Cancel** is immediate rather than "after this
  gigabyte";
* free disk is checked before starting *and* before promotion, because
  something else on the machine can fill the volume in the meantime.

Nothing here decides *whether* to download. Consent belongs to the
orchestrator and the UI; this module only carries out a decision already
made.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import httpx

from syzygy.local_models.contracts import FailureKind, RecoveryAction, SetupFailure
from syzygy.local_models.diagnostics import redact
from syzygy.local_models.paths import LocalModelPaths, write_ownership
from syzygy.local_models.runtime_state import (
    DownloadProgress,
    LocalRuntimeState,
    load_runtime_state,
    now_iso,
    save_runtime_state,
)

#: Read in chunks large enough to keep the loop cheap on a fast link and
#: small enough that cancellation feels instant on a slow one.
CHUNK_BYTES: Final = 1024 * 1024

#: A model host that redirects more than this is misconfigured or hostile.
MAX_REDIRECTS: Final = 5

#: Connect fast, then be patient: a CDN can stall mid-transfer on a
#: perfectly good connection, but a host that will not accept a connection
#: in fifteen seconds is down.
DEFAULT_TIMEOUT: Final = httpx.Timeout(connect=15.0, read=120.0, write=120.0, pool=15.0)

#: Kept free beyond the file itself, so a download cannot fill the volume
#: the readings database lives on.
DISK_HEADROOM_BYTES: Final = 512 * 1024 * 1024


class DownloadCancelled(Exception):
    """The caller's `cancel()` returned True. The partial file is kept and
    is resumable; nothing has been promoted."""


class DownloadError(Exception):
    """A typed failure. `failure` is what the UI renders."""

    def __init__(self, failure: SetupFailure) -> None:
        super().__init__(failure.message)
        self.failure = failure


@dataclass(frozen=True)
class DownloadRequest:
    """One artifact to fetch. Immutable, and fully pinned - a request with
    no digest cannot be constructed, which is how "download something and
    hope" is kept out of the codebase."""

    #: Stable key for the resume record: the catalog artifact id, or the
    #: runtime asset name.
    key: str
    url: str
    sha256: str
    expected_bytes: int
    destination: Path
    #: What the file is, for the ownership marker.
    kind: str = "model"


#: `(downloaded_bytes, total_bytes)`. Called often; must be cheap.
ProgressCallback = Callable[[int, int | None], None]
CancelCheck = Callable[[], bool]


def free_disk_bytes(path: Path) -> int | None:
    import shutil

    probe = path
    while True:
        try:
            return shutil.disk_usage(probe).free
        except OSError:
            parent = probe.parent
            if parent == probe:
                return None
            probe = parent


def verify_digest(path: Path, expected_sha256: str) -> bool:
    """Hash a file on disk. Used after download, and by the startup repair
    check when a `--deep` verification is asked for."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError:
        return False
    return digest.hexdigest() == expected_sha256.lower()


def download_verified(
    request: DownloadRequest,
    paths: LocalModelPaths,
    *,
    on_progress: ProgressCallback | None = None,
    cancel: CancelCheck | None = None,
    client: httpx.Client | None = None,
) -> Path:
    """Fetch, verify, and atomically promote `request`. Returns the final
    path. Raises `DownloadError` or `DownloadCancelled`; never leaves a
    partially written file at the destination.
    """
    paths.ensure_exists()

    # Already there and correct? Then this is a no-op, which is what makes
    # "try again" after a crash cheap instead of another nine gigabytes.
    if request.destination.exists() and verify_digest(request.destination, request.sha256):
        if on_progress:
            on_progress(request.expected_bytes, request.expected_bytes)
        return request.destination

    _require_disk(paths.partial_dir, request.expected_bytes, "starting the download")

    partial = paths.partial_dir / f"{request.key}.partial"
    state = load_runtime_state(paths.state_path)
    record = state.download(request.key)

    resume_from, digest = _prepare_resume(partial, record, request)

    owns_client = client is None
    http = client or httpx.Client(
        timeout=DEFAULT_TIMEOUT, follow_redirects=True, max_redirects=MAX_REDIRECTS
    )
    try:
        headers: dict[str, str] = {}
        if resume_from:
            headers["Range"] = f"bytes={resume_from}-"
            if record and record.etag:
                # Only continue if the file we started is the file that is
                # still there. Anything else and we start over.
                headers["If-Range"] = record.etag

        try:
            with http.stream("GET", request.url, headers=headers) as response:
                _raise_for_http_status(response, request)

                if resume_from and response.status_code != 206:
                    # The server ignored the range (or the validator moved).
                    # Start clean rather than concatenating two prefixes.
                    resume_from = 0
                    digest = hashlib.sha256()
                    partial.unlink(missing_ok=True)

                total = _expected_total(response, resume_from)
                _check_declared_length(total, request)

                mode = "ab" if resume_from else "wb"
                written = resume_from
                validator = response.headers.get("ETag")
                last_modified = response.headers.get("Last-Modified")

                with partial.open(mode) as handle:
                    for chunk in response.iter_bytes(CHUNK_BYTES):
                        if cancel is not None and cancel():
                            handle.flush()
                            _remember(
                                paths, request, partial, written, total, validator, last_modified
                            )
                            raise DownloadCancelled(request.key)
                        handle.write(chunk)
                        digest.update(chunk)
                        written += len(chunk)
                        if on_progress:
                            on_progress(written, total)

                _remember(paths, request, partial, written, total, validator, last_modified)
        except httpx.HTTPError as exc:
            raise DownloadError(_transport_failure(exc)) from exc

        if request.expected_bytes and written != request.expected_bytes:
            raise DownloadError(
                SetupFailure(
                    kind=FailureKind.UPSTREAM_CHANGED,
                    message="The file that arrived isn't the size Syzygy expected.",
                    detail=(
                        f"expected {request.expected_bytes} bytes, received {written}. "
                        "The published file may have been replaced."
                    ),
                    actions=(RecoveryAction.RETRY, RecoveryAction.COPY_DIAGNOSTICS),
                )
            )

        if digest.hexdigest() != request.sha256.lower():
            # A bad digest means the bytes on disk are worthless: keeping
            # them would only let a later "resume" build on a corrupt base.
            partial.unlink(missing_ok=True)
            _forget(paths, request.key)
            raise DownloadError(
                SetupFailure(
                    kind=FailureKind.DIGEST_MISMATCH,
                    message=(
                        "The download didn't match its published checksum, so "
                        "Syzygy discarded it."
                    ),
                    detail=(
                        f"expected sha256 {request.sha256}, computed {digest.hexdigest()}"
                    ),
                    actions=(RecoveryAction.RETRY, RecoveryAction.COPY_DIAGNOSTICS),
                )
            )

        _require_disk(request.destination.parent, written, "saving the download")
        request.destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(partial, request.destination)
        write_ownership(
            request.destination.parent,
            kind=request.kind,
            entries=(request.destination.name,),
            identity=request.key,
        )
        _forget(paths, request.key)
        return request.destination
    finally:
        if owns_client:
            http.close()


# -- helpers -----------------------------------------------------------------


def _prepare_resume(
    partial: Path, record: DownloadProgress | None, request: DownloadRequest
) -> tuple[int, Any]:
    """How many bytes we can keep, and the hash of exactly those bytes.

    Re-hashing the partial from disk is the only correct way to resume: the
    recorded byte count is a claim, and the file is the fact. They disagree
    whenever a crash happened between the write and the state save.
    """
    digest = hashlib.sha256()
    if not partial.exists():
        return 0, digest
    if record is None or record.url != request.url:
        # A partial with no record, or from a different URL, is not
        # something to build on.
        partial.unlink(missing_ok=True)
        return 0, digest

    try:
        with partial.open("rb") as handle:
            size = 0
            while True:
                chunk = handle.read(CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
    except OSError:
        partial.unlink(missing_ok=True)
        return 0, hashlib.sha256()

    if request.expected_bytes and size > request.expected_bytes:
        # Longer than the finished file: this cannot be a prefix of it.
        partial.unlink(missing_ok=True)
        return 0, hashlib.sha256()
    return size, digest


def _raise_for_http_status(response: httpx.Response, request: DownloadRequest) -> None:
    status = response.status_code
    if status < 300:
        return
    response.read()
    if status in (401, 403):
        raise DownloadError(
            SetupFailure(
                kind=FailureKind.AUTHENTICATION_REQUIRED,
                message=(
                    "The publisher is asking for a sign-in before this model can be "
                    "downloaded."
                ),
                detail=f"{request.url} answered {status}",
                actions=(RecoveryAction.CHOOSE_SMALLER, RecoveryAction.OPEN_LICENSE),
                retryable=False,
            )
        )
    if status == 404 or status == 410:
        raise DownloadError(
            SetupFailure(
                kind=FailureKind.UPSTREAM_CHANGED,
                message="That file is no longer published where Syzygy expected it.",
                detail=f"{request.url} answered {status}",
                actions=(RecoveryAction.CHOOSE_SMALLER, RecoveryAction.COPY_DIAGNOSTICS),
                retryable=False,
            )
        )
    if status == 416:
        raise DownloadError(
            SetupFailure(
                kind=FailureKind.CORRUPT_PARTIAL,
                message="The partly-downloaded file no longer matches what's published.",
                detail=f"{request.url} rejected the resume range ({status})",
                actions=(RecoveryAction.RETRY,),
            )
        )
    raise DownloadError(
        SetupFailure(
            kind=FailureKind.OFFLINE if status >= 500 else FailureKind.UPSTREAM_CHANGED,
            message="The download server returned an error.",
            detail=f"{request.url} answered {status}",
            actions=(RecoveryAction.RETRY, RecoveryAction.COPY_DIAGNOSTICS),
        )
    )


def _expected_total(response: httpx.Response, resume_from: int) -> int | None:
    length = response.headers.get("Content-Length")
    if length is None:
        return None
    try:
        declared = int(length)
    except ValueError:
        return None
    # On a 206 the length is what remains, not the whole file.
    return declared + resume_from if response.status_code == 206 else declared


def _check_declared_length(total: int | None, request: DownloadRequest) -> None:
    if total is None or not request.expected_bytes:
        return
    if total != request.expected_bytes:
        raise DownloadError(
            SetupFailure(
                kind=FailureKind.UPSTREAM_CHANGED,
                message="The published file isn't the size Syzygy has recorded for it.",
                detail=(
                    f"the server offers {total} bytes; the catalog pins "
                    f"{request.expected_bytes}. Syzygy won't download a file it "
                    "cannot verify."
                ),
                actions=(RecoveryAction.CHOOSE_SMALLER, RecoveryAction.COPY_DIAGNOSTICS),
                retryable=False,
            )
        )


def _transport_failure(exc: httpx.HTTPError) -> SetupFailure:
    return SetupFailure(
        kind=FailureKind.OFFLINE,
        message="Syzygy couldn't reach the download server.",
        detail=redact(f"{type(exc).__name__}: {exc}"),
        actions=(RecoveryAction.RETRY, RecoveryAction.SKIP_FOR_NOW),
    )


def _require_disk(directory: Path, needed: int, phase: str) -> None:
    free = free_disk_bytes(directory)
    if free is None:
        return
    if free < needed + DISK_HEADROOM_BYTES:
        raise DownloadError(
            SetupFailure(
                kind=FailureKind.INSUFFICIENT_DISK,
                message=f"Not enough free disk space for {phase}.",
                detail=(
                    f"{(needed + DISK_HEADROOM_BYTES) / 1024**3:.1f} GB needed, "
                    f"{free / 1024**3:.1f} GB free"
                ),
                actions=(RecoveryAction.FREE_DISK_SPACE, RecoveryAction.CHOOSE_SMALLER),
                retryable=False,
            )
        )


def _remember(
    paths: LocalModelPaths,
    request: DownloadRequest,
    partial: Path,
    written: int,
    total: int | None,
    etag: str | None,
    last_modified: str | None,
) -> None:
    state = load_runtime_state(paths.state_path)
    save_runtime_state(
        paths.state_path,
        state.with_download(
            DownloadProgress(
                key=request.key,
                url=request.url,
                partial_path=str(partial),
                downloaded_bytes=written,
                total_bytes=total,
                etag=etag,
                last_modified=last_modified,
                updated_at_utc=now_iso(),
            )
        ),
    )


def _forget(paths: LocalModelPaths, key: str) -> None:
    state: LocalRuntimeState = load_runtime_state(paths.state_path)
    save_runtime_state(paths.state_path, state.without_download(key))


def discard_partial(paths: LocalModelPaths, key: str) -> None:
    """Throw away a resumable partial. Only ever called for a file under
    `partial_dir`, which Syzygy created."""
    partial = paths.partial_dir / f"{key}.partial"
    if paths.contains(partial):
        partial.unlink(missing_ok=True)
    _forget(paths, key)
