"""Extracting a downloaded runtime archive safely (M16.5c).

An archive is attacker-influenceable input even when it is digest-verified
- the digest proves the bytes are the ones the manifest pinned, not that
whoever built them was careful. So every member is checked before it is
written:

* the destination path must stay inside the extraction directory once
  resolved, which rejects `../../etc/cron.d/x`, an absolute path, a
  Windows drive letter, and a path that escapes through a symlinked
  parent;
* symlinks and hard links must point inside it too, which is the variant
  the naive `..` check misses - a link is written cheaply and dereferenced
  later;
* device nodes, FIFOs, and anything else that is not a regular file or a
  directory are skipped outright;
* the total uncompressed size is capped, so a compression bomb fails
  instead of filling the disk.

`tarfile.extractall(filter="data")` does much of this on modern Pythons.
It is used *as well*, not instead: the explicit checks are what this
module is for, they run on every supported version identically, and they
produce a message that says which member was rejected.
"""

from __future__ import annotations

import os
import stat
import tarfile
import zipfile
from pathlib import Path
from typing import Final

from syzygy.local_models.contracts import FailureKind, RecoveryAction, SetupFailure

#: Uncompressed ceiling for a runtime archive. The largest allowlisted
#: build unpacks to well under a gigabyte; anything claiming four is not
#: a llama.cpp release.
MAX_EXTRACTED_BYTES: Final = 4 * 1024**3
MAX_MEMBERS: Final = 20_000


class ArchiveError(Exception):
    """Extraction refused. `failure` is what the UI renders."""

    def __init__(self, failure: SetupFailure) -> None:
        super().__init__(failure.message)
        self.failure = failure


def _unsafe(detail: str) -> ArchiveError:
    return ArchiveError(
        SetupFailure(
            kind=FailureKind.ARCHIVE_UNSAFE,
            message="The downloaded archive contains something Syzygy won't unpack.",
            detail=detail,
            actions=(RecoveryAction.RETRY, RecoveryAction.COPY_DIAGNOSTICS),
            retryable=False,
        )
    )


def _resolve_within(root: Path, member_name: str) -> Path:
    """The path `member_name` would land at, proven to be inside `root`."""
    if not member_name or member_name in (".", "/"):
        raise _unsafe(f"archive member has no usable name: {member_name!r}")
    candidate = Path(member_name)
    if candidate.is_absolute() or candidate.drive or member_name.startswith(("/", "\\")):
        raise _unsafe(f"archive member has an absolute path: {member_name!r}")
    if ".." in candidate.parts:
        raise _unsafe(f"archive member escapes its directory: {member_name!r}")
    target = (root / candidate).resolve()
    root_resolved = root.resolve()
    if root_resolved != target and root_resolved not in target.parents:
        raise _unsafe(f"archive member resolves outside the target directory: {member_name!r}")
    return target


def _check_link(root: Path, member_name: str, link_target: str) -> None:
    """A link's *target* has to be inside the tree as well."""
    if not link_target:
        raise _unsafe(f"archive link {member_name!r} has no target")
    if Path(link_target).is_absolute():
        raise _unsafe(f"archive link {member_name!r} points outside: {link_target!r}")
    base = (root / Path(member_name)).parent
    resolved = (base / link_target).resolve()
    root_resolved = root.resolve()
    if root_resolved != resolved and root_resolved not in resolved.parents:
        raise _unsafe(f"archive link {member_name!r} points outside: {link_target!r}")


def extract_archive(archive: Path, destination: Path, *, archive_format: str) -> Path:
    """Unpack `archive` into `destination`, which is created fresh.

    Returns `destination`. Raises `ArchiveError` for anything the checks
    above reject - and leaves the partially extracted directory behind for
    the caller to remove, because deciding what to clean up is the
    installer's job (it knows whether a previous good version is in there).
    """
    destination.mkdir(parents=True, exist_ok=True)
    if archive_format == "tar.gz":
        _extract_tar(archive, destination)
    elif archive_format == "zip":
        _extract_zip(archive, destination)
    else:
        raise ArchiveError(
            SetupFailure(
                kind=FailureKind.ARCHIVE_UNSAFE,
                message="Syzygy doesn't know how to unpack that archive.",
                detail=f"unsupported archive format {archive_format!r}",
                actions=(RecoveryAction.COPY_DIAGNOSTICS,),
                retryable=False,
            )
        )
    return destination


def _extract_tar(archive: Path, destination: Path) -> None:
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            members = bundle.getmembers()
            if len(members) > MAX_MEMBERS:
                raise _unsafe(f"archive declares {len(members)} members")
            total = 0
            for member in members:
                if member.isdev():
                    raise _unsafe(f"archive contains a device node: {member.name!r}")
                if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                    raise _unsafe(f"archive contains an unsupported entry: {member.name!r}")
                _resolve_within(destination, member.name)
                if member.issym() or member.islnk():
                    _check_link(destination, member.name, member.linkname)
                total += max(0, member.size)
                if total > MAX_EXTRACTED_BYTES:
                    raise _unsafe("archive unpacks to more than Syzygy will accept")
            # `filter="data"` is a second, independent implementation of
            # the same policy, added in Python 3.12 and available on 3.11.4+.
            bundle.extractall(destination, filter="data")
    except tarfile.TarError as exc:
        raise _unsafe(f"archive could not be read: {exc}") from exc


def _extract_zip(archive: Path, destination: Path) -> None:
    try:
        with zipfile.ZipFile(archive) as bundle:
            infos = bundle.infolist()
            if len(infos) > MAX_MEMBERS:
                raise _unsafe(f"archive declares {len(infos)} members")
            total = 0
            for info in infos:
                mode = info.external_attr >> 16
                if mode and stat.S_ISLNK(mode):
                    # Windows release zips contain no symlinks; one showing
                    # up means this is not the archive we think it is.
                    raise _unsafe(f"archive contains a symbolic link: {info.filename!r}")
                target = _resolve_within(destination, info.filename)
                total += max(0, info.file_size)
                if total > MAX_EXTRACTED_BYTES:
                    raise _unsafe("archive unpacks to more than Syzygy will accept")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as source, target.open("wb") as handle:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
                # Zip carries Unix permissions in the high half of
                # `external_attr` when it was made on a Unix system; a
                # Windows-built zip has none, and the executable bit is set
                # later by the installer for the binaries it identifies.
                if mode and os.name == "posix":
                    target.chmod(stat.S_IMODE(mode))
    except zipfile.BadZipFile as exc:
        raise _unsafe(f"archive could not be read: {exc}") from exc


def find_executable(root: Path, names: tuple[str, ...]) -> Path | None:
    """The first of `names` found anywhere under `root`.

    A search rather than a fixed path because the official archives are not
    laid out alike: the macOS and Linux tarballs put everything under
    `llama-<tag>/`, and the Windows zips are flat. Names are matched
    case-insensitively, since Windows filesystems are.
    """
    wanted = {name.lower() for name in names}
    for candidate in sorted(root.rglob("*")):
        try:
            if candidate.is_file() and candidate.name.lower() in wanted:
                return candidate
        except OSError:
            continue
    return None


def make_executable(path: Path) -> None:
    """Add the owner execute bit, keeping everything else. No-op where the
    concept does not apply."""
    if os.name != "posix":
        return
    try:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IRUSR)
    except OSError:
        pass
