"""Where Syzygy keeps the things it manages (M16.1d).

Ownership is the point of this module. Cleanup (`syzygy model local
remove`, M16.6e) may delete a runtime or a model file only if it can
*prove* Syzygy put it there, and "it is under our data directory" is not
proof on its own - a user can symlink anything anywhere. So every managed
artifact gets an `OWNERSHIP.json` marker next to it recording what it is,
when it arrived, and which catalog entry it came from; `is_syzygy_owned`
answers the question by reading that marker and confirming the file really
lives inside the directory it claims to (`Path.resolve` first, so a
symlink out of the tree fails the check).

Layout, under `AppPaths.data_dir`::

    local_models/
    ├── runtime/            unpacked llama.cpp builds, one dir per version
    │   └── b4667/
    │       ├── OWNERSHIP.json
    │       └── bin/llama-server
    ├── gguf/               downloaded model files
    │   ├── OWNERSHIP.json
    │   └── qwen3-8b-q4_k_m.gguf
    ├── partial/            in-flight downloads (never executed, never loaded)
    ├── logs/               bounded, redacted server logs
    └── state.json          runtime state: pid, port, health, progress

`AppPaths.models_dir` predates this and is left alone; it was never
populated, and pointing new code at a directory whose ownership rules are
undocumented would defeat the purpose.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from syzygy.config import AppPaths, default_app_paths

#: Written into every directory Syzygy owns.
OWNERSHIP_MARKER: Final = "OWNERSHIP.json"

#: Bumped if the marker's shape ever changes; an unrecognized version means
#: "not provably ours", which fails safe (we refuse to delete).
OWNERSHIP_SCHEMA: Final = "local-model-ownership-v1"


@dataclass(frozen=True)
class LocalModelPaths:
    """Resolved layout for one installation's managed local models."""

    root: Path
    runtime_dir: Path
    models_dir: Path
    partial_dir: Path
    logs_dir: Path
    state_path: Path

    @classmethod
    def from_app_paths(cls, paths: AppPaths) -> LocalModelPaths:
        root = paths.data_dir / "local_models"
        return cls(
            root=root,
            runtime_dir=root / "runtime",
            models_dir=root / "gguf",
            partial_dir=root / "partial",
            logs_dir=root / "logs",
            state_path=root / "state.json",
        )

    def ensure_exists(self) -> None:
        """Create the layout. `0o700` because everything here is one
        user's data, and the logs - bounded and redacted though they are -
        are still this person's business alone."""
        for directory in (
            self.root,
            self.runtime_dir,
            self.models_dir,
            self.partial_dir,
            self.logs_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
            _restrict_permissions(directory)

    def contains(self, candidate: Path) -> bool:
        """Is `candidate` genuinely inside this tree? Resolves both sides
        first, so a symlink pointing outward is not "inside"."""
        try:
            resolved = candidate.resolve()
            root = self.root.resolve()
        except OSError:
            return False
        return resolved == root or root in resolved.parents


def default_local_model_paths() -> LocalModelPaths:
    return LocalModelPaths.from_app_paths(default_app_paths())


def _restrict_permissions(path: Path) -> None:
    """Best effort. Windows has no POSIX mode bits worth setting here, and
    a filesystem that refuses `chmod` is not a reason to fail setup."""
    if os.name != "posix":
        return
    try:
        path.chmod(0o700 if path.is_dir() else 0o600)
    except OSError:
        pass


# -- ownership ---------------------------------------------------------------


@dataclass(frozen=True)
class Ownership:
    """The proof that Syzygy created something, read back from disk."""

    schema: str
    kind: str
    created_at_utc: str
    #: Filenames (not paths) this marker vouches for. A file that appeared
    #: in a managed directory by other means is not covered by it.
    entries: tuple[str, ...]
    #: Catalog artifact id / runtime build, for the "what is this?" column.
    identity: str | None = None

    @property
    def recognized(self) -> bool:
        return self.schema == OWNERSHIP_SCHEMA


def write_ownership(
    directory: Path, *, kind: str, entries: tuple[str, ...], identity: str | None = None
) -> None:
    """Mark `directory` as Syzygy-owned. Merges with an existing marker so
    a second download into `gguf/` does not disown the first."""
    directory.mkdir(parents=True, exist_ok=True)
    existing = read_ownership(directory)
    merged = tuple(sorted(set(entries) | set(existing.entries if existing else ())))
    atomic_write_json(
        directory / OWNERSHIP_MARKER,
        {
            "schema": OWNERSHIP_SCHEMA,
            "kind": kind,
            "created_at_utc": (
                existing.created_at_utc
                if existing
                else datetime.now(UTC).isoformat(timespec="seconds")
            ),
            "entries": list(merged),
            "identity": (
                identity
                if identity is not None
                else (existing.identity if existing else None)
            ),
        },
    )


def read_ownership(directory: Path) -> Ownership | None:
    """`None` for a missing, unreadable, or malformed marker - all of which
    mean "cannot prove we own this", which is the safe answer."""
    try:
        raw = (directory / OWNERSHIP_MARKER).read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    entries = payload.get("entries")
    return Ownership(
        schema=str(payload.get("schema", "")),
        kind=str(payload.get("kind", "")),
        created_at_utc=str(payload.get("created_at_utc", "")),
        entries=tuple(str(entry) for entry in entries) if isinstance(entries, list) else (),
        identity=payload.get("identity"),
    )


def forget_ownership(directory: Path, entry: str) -> None:
    """Drop one filename from the marker (it was just removed)."""
    existing = read_ownership(directory)
    if existing is None:
        return
    remaining = tuple(name for name in existing.entries if name != entry)
    atomic_write_json(
        directory / OWNERSHIP_MARKER,
        {
            "schema": OWNERSHIP_SCHEMA,
            "kind": existing.kind,
            "created_at_utc": existing.created_at_utc,
            "entries": list(remaining),
            "identity": existing.identity,
        },
    )


def is_syzygy_owned(paths: LocalModelPaths, target: Path) -> bool:
    """The whole authorization check for destructive operations.

    Three conditions, all required: the path resolves inside the managed
    tree, its directory carries a marker Syzygy recognizes, and that marker
    names this exact file. An external model referenced by the user, a
    system `llama-server`, and another application's Hugging Face cache all
    fail at the first condition and can never be deleted.
    """
    if not paths.contains(target):
        return False
    marker = read_ownership(target.parent)
    if marker is None or not marker.recognized:
        return False
    return target.name in marker.entries


# -- atomic writes -----------------------------------------------------------


def atomic_write_json(path: Path, payload: Any) -> None:
    """Write JSON so a crash mid-write cannot leave a truncated file.

    Same-directory temporary file, flush, `fsync`, then `os.replace`, which
    is atomic on POSIX and on Windows. Every settings/state document in
    this package goes through here - these files are read on startup, and a
    half-written one would turn a power cut into a broken installation.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        _restrict_permissions(temp_path)
        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def read_json(path: Path) -> dict[str, Any]:
    """`{}` for missing/unreadable/corrupt - never raises. Same reasoning
    as `syzygy.settings.load_document`: refusing to start because a cache
    file has a stray comma would be absurd."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        loaded = json.loads(raw)
    except ValueError:
        return {}
    return loaded if isinstance(loaded, dict) else {}
