"""The seam between inventory code and the actual computer (M16.2a/e).

Every OS touchpoint the detectors use - running a command, reading
`/proc`, listing `/sys`, asking for free disk, looking something up on
`PATH` - goes through one injectable `Probe`. `Probe.real()` is the
production wiring; tests build a `Probe` from a captured, redacted fixture
and never learn anything about the machine running them.

That constraint is M16.2e's, and it is not merely tidiness: a test that
called `nvidia-smi` for real would pass on a maintainer's workstation,
fail in CI, and tell neither of them anything about whether the *parser*
is correct.

Two rules every command in this package follows, enforced here rather
than remembered at each call site:

* a timeout, always - `nvidia-smi` on a wedged driver hangs forever, and a
  setup wizard that hangs at "checking this computer" is worse than one
  that says "could not determine";
* an argument array, never a shell - nothing in this package interpolates
  a discovered path into a command string (M16's safety contract).
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

#: Ceiling for any single inventory command. Generous enough for a cold
#: `nvidia-smi`, short enough that the worst case for a machine with three
#: broken vendor tools is still a few seconds.
DEFAULT_COMMAND_TIMEOUT: Final = 5.0


@dataclass(frozen=True)
class CommandResult:
    """What a probe command did. Never raises out to the caller: a missing
    executable, a timeout, and a non-zero exit are all *data*, because at
    least one of them is the normal case on every platform."""

    argv: tuple[str, ...]
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    missing: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and not self.missing

    @property
    def failure_note(self) -> str:
        name = self.argv[0] if self.argv else "command"
        if self.missing:
            return f"{name} not found"
        if self.timed_out:
            return f"{name} timed out"
        if self.error:
            return f"{name} failed: {self.error}"
        return f"{name} exited {self.returncode}"


CommandRunner = Callable[[Sequence[str], float], CommandResult]


def run_command(argv: Sequence[str], timeout: float = DEFAULT_COMMAND_TIMEOUT) -> CommandResult:
    """Run `argv` with no shell, capturing output under a timeout."""
    args = tuple(argv)
    try:
        completed = subprocess.run(  # noqa: S603 - argument array, never a shell
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            # An inventory command must never wait on a human.
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return CommandResult(argv=args, missing=True)
    except subprocess.TimeoutExpired:
        return CommandResult(argv=args, timed_out=True)
    except OSError as exc:
        # Permission denied, exec format error, no fork available.
        return CommandResult(argv=args, error=str(exc))
    return CommandResult(
        argv=args,
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


def _read_text(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _glob(pattern: str) -> list[str]:
    try:
        return sorted(str(match) for match in Path("/").glob(pattern.lstrip("/")))
    except OSError:
        return []


def _disk_usage(path: Path) -> tuple[int, int, int] | None:
    """`(total, used, free)`, or `None` if the path cannot be interrogated
    (it may not exist yet - a first setup creates the model directory only
    after the user consents)."""
    probe_path = path
    while True:
        try:
            usage = shutil.disk_usage(probe_path)
        except OSError:
            parent = probe_path.parent
            if parent == probe_path:
                return None
            probe_path = parent
            continue
        return (usage.total, usage.used, usage.free)


def _sysconf(name: str) -> int | None:
    try:
        value = os.sysconf(name)
    except (ValueError, OSError, AttributeError):
        return None
    return value if isinstance(value, int) and value > 0 else None


@dataclass(frozen=True)
class Probe:
    """One machine, as the detectors are allowed to see it."""

    system: str
    release: str
    version: str
    machine: str
    processor: str
    environ: Mapping[str, str]
    run: CommandRunner
    read_text: Callable[[str], str | None]
    glob: Callable[[str], list[str]]
    which: Callable[[str], str | None]
    disk_usage: Callable[[Path], tuple[int, int, int] | None]
    sysconf: Callable[[str], int | None]
    cpu_count: Callable[[], int | None]
    #: Set by fixtures to make an inventory reproducible in tests.
    notes: tuple[str, ...] = field(default=())

    @classmethod
    def real(cls) -> Probe:
        return cls(
            system=platform.system(),
            release=platform.release(),
            version=platform.version(),
            machine=platform.machine(),
            processor=platform.processor(),
            environ=dict(os.environ),
            run=run_command,
            read_text=_read_text,
            glob=_glob,
            which=shutil.which,
            disk_usage=_disk_usage,
            sysconf=_sysconf,
            cpu_count=os.cpu_count,
        )

    # Convenience predicates every detector wants.

    @property
    def is_darwin(self) -> bool:
        return self.system == "Darwin"

    @property
    def is_windows(self) -> bool:
        return self.system == "Windows"

    @property
    def is_linux(self) -> bool:
        return self.system == "Linux"
