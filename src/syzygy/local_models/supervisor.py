"""Running the local model server, and owning that process safely (M16.7).

Outside the TUI on purpose: nothing here imports Textual, and the wizard's
"Starting the model…" step is a thin caller of `ServerSupervisor.start`.

The three hard parts, and how each is handled:

**Binding.** `--host 127.0.0.1`, always, with a port leased by binding to
port 0 and reading back what the OS gave us. Never `0.0.0.0`, never a
firewall change, never an advertisement on the network. A port collision
is handled by leasing a different one, not by trying harder on the same.

**Identity.** After a crash there is a PID in the state file, and a PID
alone is worthless - the number may have been reused by something
unrelated, and signalling that would be inexcusable. So
`verify_recorded_process` requires the process to exist *and* its command
line to still contain the executable and model path Syzygy recorded. If
the command line cannot be read on this platform, the answer is "cannot
verify", the state is cleaned up, and a fresh server is started on a new
port. Syzygy never signals a process it could not identify.

**Succession.** That verification is what makes the *next* run safe, and
`reclaim` is where it is spent (M25). A record whose process still
verifies, still answers, and was launched to serve exactly what this run
wants is adopted through `AdoptedProcess` and reused; one that verifies
but is wedged or serving something else is stopped before a replacement
binds; one that cannot be verified is forgotten and left alone. The
failure this replaced was quieter than a crash: nothing called for
recovery at all, so every run after an unclean exit started a second
multi-gigabyte server and erased the first one's record on the way past,
leaving a process nothing could find and nothing would ever stop.

**Diagnosis.** "It didn't start" is useless. The server's output is read
on a background thread, redacted line by line, kept to a bounded buffer,
and matched against the failure modes that actually occur - out of memory,
an architecture the build doesn't know, a backend or driver that failed,
a chat template that won't compile, a port that was taken. Each gets its
own `FailureKind`, and therefore its own remedy in the UI.
"""

from __future__ import annotations

import contextlib
import os
import secrets
import signal
import socket
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from syzygy.local_models.contracts import (
    Backend,
    FailureKind,
    RecoveryAction,
    SetupFailure,
)
from syzygy.local_models.diagnostics import redact, redact_argv
from syzygy.local_models.paths import LocalModelPaths
from syzygy.local_models.probe import Probe
from syzygy.local_models.runtime_state import (
    HealthRecord,
    ProcessIdentity,
    RecordedLaunch,
    load_runtime_state,
    now_iso,
    save_runtime_state,
)

#: How many redacted output lines to keep in memory for the failure card.
MAX_LOG_LINES = 400

#: Ceiling on the on-disk log. Small: these exist to explain a failure that
#: just happened, not to be a history of every run.
MAX_LOG_BYTES = 512 * 1024

#: Environment variable carrying the per-launch token. Read back on
#: platforms that expose a child's environment; advisory elsewhere.
START_TOKEN_ENV = "SYZYGY_LOCAL_MODEL_TOKEN"

#: A model can take a long time to load from a cold page cache on a slow
#: disk - nine gigabytes at 100 MB/s is a minute and a half before the
#: server even binds. The ceiling scales with the file so a small model on
#: a fast machine does not inherit a big model's patience.
BASE_STARTUP_TIMEOUT = 60.0
SECONDS_PER_GIB = 25.0
MAX_STARTUP_TIMEOUT = 900.0

#: How long a graceful stop is given before escalating, and before giving
#: up entirely. Bounded because quitting Syzygy must never hang on a wedged
#: child (M16.7b).
TERMINATE_GRACE_SECONDS = 5.0
KILL_GRACE_SECONDS = 3.0


class StartupPhase(StrEnum):
    """What to show while waiting. Each maps to one sentence in the UI."""

    LAUNCHING = "launching"
    LOADING_MODEL = "loading the model"
    READY = "ready"


class ServerProcess(Protocol):
    """The slice of `subprocess.Popen` this module uses. Tests provide a
    fake; nothing here needs the rest of `Popen`."""

    @property
    def pid(self) -> int: ...

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


Spawner = Callable[[Sequence[str], Mapping[str, str]], ServerProcess]

#: `(base_url) -> (ready, http_status, detail)`. Injected so the readiness
#: loop can be driven deterministically in tests.
ReadinessProbe = Callable[[str], tuple[bool, int | None, str | None]]


class ServerStartError(Exception):
    def __init__(self, failure: SetupFailure, log_tail: str = "") -> None:
        super().__init__(failure.message)
        self.failure = failure
        self.log_tail = log_tail


@dataclass(frozen=True)
class LaunchSpec:
    """Everything needed to start one server. No reading, profile, card, or
    prompt content appears here - and therefore none can appear on a
    command line visible in the process list (M16.7a)."""

    executable: Path
    model_path: Path
    port: int
    context_tokens: int
    max_output_tokens: int
    served_model_id: str = "local"
    threads: int | None = None
    gpu_layers: int | None = None
    backend: Backend = Backend.CPU
    start_token: str = field(default_factory=lambda: secrets.token_hex(16))


def build_argv(spec: LaunchSpec) -> tuple[str, ...]:
    """The exact argument array. Never a string, never a shell.

    `--host 127.0.0.1` and `--no-webui` are not configurable: the first is
    M16's binding rule, and the second keeps a browser UI Syzygy did not
    ask for off the port it just opened.
    """
    argv: list[str] = [
        str(spec.executable),
        "--model",
        str(spec.model_path),
        "--host",
        "127.0.0.1",
        "--port",
        str(spec.port),
        "--ctx-size",
        str(spec.context_tokens),
        "--n-predict",
        str(spec.max_output_tokens),
        "--alias",
        spec.served_model_id,
        "--no-webui",
    ]
    if spec.threads is not None:
        argv += ["--threads", str(spec.threads)]
    if spec.gpu_layers is not None:
        argv += ["--n-gpu-layers", str(spec.gpu_layers)]
    return tuple(argv)


def base_url_for(port: int) -> str:
    return f"http://127.0.0.1:{port}/v1"


def health_url_for(port: int) -> str:
    return f"http://127.0.0.1:{port}/health"


def startup_timeout_for(model_path: Path) -> float:
    """Scaled by model size, because that is what the wait is made of."""
    try:
        gibibytes = model_path.stat().st_size / 1024**3
    except OSError:
        gibibytes = 4.0
    return min(MAX_STARTUP_TIMEOUT, BASE_STARTUP_TIMEOUT + gibibytes * SECONDS_PER_GIB)


def lease_port(preferred: int | None = None) -> int:
    """Ask the OS for a free localhost port.

    Binding to port 0 and reading the assignment back is the only way to
    get one that is genuinely free; there is an unavoidable race between
    releasing it and the server binding it, which is why a collision at
    launch is a recoverable failure that leases again rather than an error.
    """
    if preferred is not None and _port_is_free(preferred):
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


# -- log capture -------------------------------------------------------------


class LogBuffer:
    """A bounded, redacted tail of the server's output.

    Redaction happens here, on the way in, so the file on disk is as safe
    as the copy in memory - a user who opens the log by hand gets the same
    treatment as one who presses "copy diagnostics".
    """

    def __init__(self, path: Path | None, *, max_lines: int = MAX_LOG_LINES) -> None:
        self._lines: deque[str] = deque(maxlen=max_lines)
        self._path = path
        self._written = 0
        self._lock = threading.Lock()

    def append(self, line: str) -> None:
        cleaned = redact(line.rstrip("\n"))
        with self._lock:
            self._lines.append(cleaned)
            if self._path is None or self._written >= MAX_LOG_BYTES:
                return
            try:
                with self._path.open("a", encoding="utf-8") as handle:
                    handle.write(cleaned + "\n")
                self._written += len(cleaned) + 1
            except OSError:
                # A log Syzygy cannot write is not a reason to fail a
                # start; the in-memory tail still explains what happened.
                self._path = None

    def tail(self, lines: int = 40) -> str:
        with self._lock:
            return "\n".join(list(self._lines)[-lines:])

    def text(self) -> str:
        with self._lock:
            return "\n".join(self._lines)


def _pump(stream: object, buffer: LogBuffer) -> None:
    try:
        for raw in stream:  # type: ignore[attr-defined]
            buffer.append(raw if isinstance(raw, str) else raw.decode("utf-8", "replace"))
    except (OSError, ValueError):
        pass


# -- failure classification --------------------------------------------------

#: Ordered: the first match wins, so the more specific patterns come
#: first. Matched against the whole redacted log, lowercased.
_FAILURE_SIGNATURES: tuple[tuple[tuple[str, ...], FailureKind, str], ...] = (
    (
        ("address already in use", "bind: address", "eaddrinuse"),
        FailureKind.PORT_UNAVAILABLE,
        "Another program took the port Syzygy reserved.",
    ),
    (
        ("out of memory", "failed to allocate", "insufficient memory", "cudamalloc failed"),
        FailureKind.OUT_OF_MEMORY,
        "The model needed more memory than this computer could give it.",
    ),
    (
        ("unknown model architecture", "unsupported model architecture", "unknown architecture"),
        FailureKind.MODEL_LOAD_FAILED,
        "The model runner doesn't recognise this model's architecture.",
    ),
    (
        ("failed to load model", "error loading model", "invalid model file"),
        FailureKind.MODEL_LOAD_FAILED,
        "The model file couldn't be loaded.",
    ),
    (
        ("chat template", "failed to apply template", "jinja"),
        FailureKind.CHAT_TEMPLATE_FAILED,
        "The model's chat template couldn't be used.",
    ),
    (
        ("no usable gpu", "vulkan", "cuda error", "hip error", "no devices found", "driver"),
        FailureKind.BACKEND_FAILED,
        "The graphics acceleration this build needs isn't working here.",
    ),
)


def classify_startup_failure(log_text: str, *, timed_out: bool) -> SetupFailure:
    """Turn the server's output into one remedy the user can act on."""
    lowered = log_text.lower()
    for markers, kind, message in _FAILURE_SIGNATURES:
        if any(marker in lowered for marker in markers):
            return SetupFailure(
                kind=kind,
                message=message,
                detail=_tail(log_text),
                actions=_actions_for(kind),
                retryable=kind is not FailureKind.OUT_OF_MEMORY,
            )
    if timed_out:
        return SetupFailure(
            kind=FailureKind.STARTUP_TIMEOUT,
            message="The model didn't finish starting in time.",
            detail=_tail(log_text),
            actions=(
                RecoveryAction.RETRY,
                RecoveryAction.CHOOSE_SMALLER,
                RecoveryAction.COPY_DIAGNOSTICS,
            ),
        )
    return SetupFailure(
        kind=FailureKind.PROCESS_CRASHED,
        message="The model runner stopped unexpectedly.",
        detail=_tail(log_text),
        actions=(
            RecoveryAction.RETRY,
            RecoveryAction.USE_EXISTING_SERVER,
            RecoveryAction.COPY_DIAGNOSTICS,
        ),
    )


def _actions_for(kind: FailureKind) -> tuple[RecoveryAction, ...]:
    if kind is FailureKind.OUT_OF_MEMORY:
        return (RecoveryAction.CHOOSE_SMALLER, RecoveryAction.COPY_DIAGNOSTICS)
    if kind is FailureKind.PORT_UNAVAILABLE:
        return (RecoveryAction.RETRY, RecoveryAction.COPY_DIAGNOSTICS)
    if kind is FailureKind.BACKEND_FAILED:
        return (
            RecoveryAction.RETRY,
            RecoveryAction.USE_EXISTING_SERVER,
            RecoveryAction.COPY_DIAGNOSTICS,
        )
    return (RecoveryAction.RETRY, RecoveryAction.COPY_DIAGNOSTICS)


def _tail(text: str, lines: int = 25) -> str:
    return "\n".join(text.splitlines()[-lines:])


# -- process identity --------------------------------------------------------


def process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "posix":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            # It exists and belongs to someone else - which already means
            # it is not ours, and `verify_recorded_process` will say so.
            return True
        return True
    try:  # pragma: no cover - Windows only
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # type: ignore[attr-defined]
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
        return True
    except Exception:
        return False


def command_line_for(pid: int, probe: Probe) -> str | None:
    """The process's command line, or `None` if this platform will not say.

    `None` is the conservative answer and it has teeth: a recorded process
    whose command line cannot be read is treated as unverifiable, and
    Syzygy will not signal it.
    """
    raw = probe.read_text(f"/proc/{pid}/cmdline")
    if raw is not None:
        return raw.replace("\0", " ").strip()
    if probe.is_darwin:
        result = probe.run(("ps", "-o", "command=", "-p", str(pid)), 5.0)
        return result.stdout.strip() if result.ok and result.stdout.strip() else None
    if probe.is_windows:  # pragma: no cover - Windows only
        result = probe.run(
            (
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine",
            ),
            20.0,
        )
        return result.stdout.strip() if result.ok and result.stdout.strip() else None
    return None


def verify_recorded_process(
    identity: ProcessIdentity, probe: Probe
) -> tuple[bool, str]:
    """Is the PID in the state file still *our* server? `(ok, reason)`.

    All of these must hold: the process exists, its command line is
    readable, and that command line still names both the executable and
    the model path Syzygy launched it with. Anything less and the answer
    is no - a stale record gets cleaned up, and nothing gets signalled.
    """
    if not process_exists(identity.pid):
        return False, "the recorded process is no longer running"
    command = command_line_for(identity.pid, probe)
    if command is None:
        return False, "this system won't say what that process is, so Syzygy won't touch it"
    if identity.executable not in command:
        return False, "a different program is now using that process id"
    if identity.model_path not in command:
        return False, "that process isn't serving the model Syzygy started"
    return True, "verified"


def _default_signal(pid: int, sig: int) -> None:
    os.kill(pid, sig)


#: `(pid) -> is it alive` and `(pid, signal) -> None`. Injected together
#: so a test can drive a fake process table: every `identity()` in the
#: suite names a PID that really exists (the test runner's own), and
#: signalling one for real would end the run.
LivenessCheck = Callable[[int], bool]
Signaller = Callable[[int, int], None]

_SIGTERM = signal.SIGTERM
#: Windows has no SIGKILL, and `os.kill` there is already `TerminateProcess`.
_SIGKILL = getattr(signal, "SIGKILL", signal.SIGTERM)


class AdoptedProcess:
    """A `ServerProcess` for a server this run did not spawn (M25.1).

    A previous run leaves a live server and a record of it. Without this,
    the only handle on that process was a PID in a JSON file, which no
    `Popen` can `poll` or `terminate` - so the next run started a *second*
    multi-gigabyte server and cleared the first one's record, which is
    precisely the orphan this module's own docstring says must not happen.

    Constructed only from an identity `verify_recorded_process` has just
    confirmed, so every signal it sends goes to a process proven to be
    Syzygy's own runner serving Syzygy's own model file. That proof is the
    analogue of the `OWNERSHIP.json` marker the file-level cleanup
    requires (ADR 0005): Syzygy signals what it can show is its own, and
    nothing else.
    """

    def __init__(
        self,
        pid: int,
        *,
        exists: LivenessCheck = process_exists,
        signal_: Signaller = _default_signal,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._pid = pid
        self._exists = exists
        self._signal = signal_
        self._sleep = sleep
        self._monotonic = monotonic

    @property
    def pid(self) -> int:
        return self._pid

    def poll(self) -> int | None:
        """`None` while it runs, `0` once it is gone.

        The exit *status* of a process this run did not spawn is not ours
        to read - no one is its parent here. `0` therefore means only
        "no longer running", which is all any caller checks.
        """
        return None if self._exists(self._pid) else 0

    def terminate(self) -> None:
        self._send(_SIGTERM)

    def kill(self) -> None:
        self._send(_SIGKILL)

    def wait(self, timeout: float | None = None) -> int:
        """Poll until it is gone. Raises `TimeoutError` if it outlives
        `timeout`, matching what `Popen.wait` does to a wedged child."""
        deadline = None if timeout is None else self._monotonic() + timeout
        while self._exists(self._pid):
            if deadline is not None and self._monotonic() >= deadline:
                raise TimeoutError(f"pid {self._pid} is still running")
            self._sleep(0.05)
        return 0

    def _send(self, sig: int) -> None:
        # Gone already, or someone else's to signal now: either way there
        # is nothing here to report and nothing to retry.
        with contextlib.suppress(OSError):
            self._signal(self._pid, sig)


# -- the supervisor ----------------------------------------------------------


@dataclass
class RunningServer:
    spec: LaunchSpec
    process: ServerProcess
    logs: LogBuffer
    started_at: float

    @property
    def base_url(self) -> str:
        return base_url_for(self.spec.port)

    @property
    def alive(self) -> bool:
        return self.process.poll() is None


def _default_spawn(argv: Sequence[str], env: Mapping[str, str]) -> ServerProcess:
    import subprocess

    return subprocess.Popen(  # noqa: S603 - argument array, shell=False
        list(argv),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        bufsize=1,
        env=dict(env),
        # Explicit and non-negotiable: no shell, ever.
        shell=False,
    )


def _default_readiness(url: str) -> tuple[bool, int | None, str | None]:
    import httpx

    try:
        response = httpx.get(url, timeout=3.0)
    except httpx.HTTPError as exc:
        return False, None, f"{type(exc).__name__}"
    if response.status_code == 200:
        return True, 200, None
    return False, response.status_code, response.text[:200]


class ServerSupervisor:
    """Owns at most one managed llama.cpp process for this application run.

    App-managed by default (M16.7b): started on demand, reused while
    Syzygy runs, and stopped on exit. There is deliberately no "leave it
    running" option - orphan handling differs on every platform, and an
    astrology program that leaves a multi-gigabyte process behind after
    quitting has done something the user did not ask for.
    """

    def __init__(
        self,
        paths: LocalModelPaths,
        *,
        probe: Probe | None = None,
        spawn: Spawner = _default_spawn,
        readiness: ReadinessProbe = _default_readiness,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        exists: LivenessCheck = process_exists,
        signal_: Signaller = _default_signal,
    ) -> None:
        self._paths = paths
        self._probe = probe or Probe.real()
        self._spawn = spawn
        self._readiness = readiness
        self._sleep = sleep
        self._monotonic = monotonic
        self._exists = exists
        self._signal = signal_
        self._server: RunningServer | None = None
        self._restarts = 0

    @property
    def running(self) -> RunningServer | None:
        if self._server is not None and not self._server.alive:
            self._server = None
        return self._server

    # -- starting ------------------------------------------------------------

    def start(
        self,
        spec: LaunchSpec,
        *,
        on_phase: Callable[[StartupPhase, str], None] | None = None,
        timeout: float | None = None,
        cancel: Callable[[], bool] | None = None,
    ) -> RunningServer:
        """Launch and wait until the server answers. Raises
        `ServerStartError` with a classified failure otherwise."""
        self._paths.ensure_exists()
        self.stop()
        # An explicit start replaces whatever was there. A server left by
        # an earlier run is stopped *before* this one binds, so the two
        # never hold the machine's memory at the same time - and it is
        # stopped only if it can still be proved to be ours (M25.2).
        self.release_recorded()

        argv = build_argv(spec)
        env = dict(os.environ)
        env[START_TOKEN_ENV] = spec.start_token

        log_path = self._paths.logs_dir / f"server-{spec.port}.log"
        with contextlib.suppress(OSError):
            log_path.unlink(missing_ok=True)
        logs = LogBuffer(log_path)
        logs.append(f"$ {redact_argv(argv)}")

        if on_phase:
            on_phase(StartupPhase.LAUNCHING, "Starting the model runner…")

        try:
            process = self._spawn(argv, env)
        except OSError as exc:
            raise ServerStartError(
                SetupFailure(
                    kind=FailureKind.PROCESS_CRASHED,
                    message="Syzygy couldn't start the model runner.",
                    detail=redact(str(exc)),
                    actions=(RecoveryAction.RETRY, RecoveryAction.COPY_DIAGNOSTICS),
                )
            ) from exc

        stdout = getattr(process, "stdout", None)
        if stdout is not None:
            reader = threading.Thread(
                target=_pump, args=(stdout, logs), name="syzygy-llama-logs", daemon=True
            )
            reader.start()

        server = RunningServer(
            spec=spec, process=process, logs=logs, started_at=self._monotonic()
        )
        self._server = server
        self._record(server, log_path)

        try:
            self._await_ready(
                server,
                timeout=timeout if timeout is not None else startup_timeout_for(spec.model_path),
                on_phase=on_phase,
                cancel=cancel,
            )
        except ServerStartError:
            self.stop()
            raise
        if on_phase:
            on_phase(StartupPhase.READY, "The model is loaded and answering.")
        return server

    def _await_ready(
        self,
        server: RunningServer,
        *,
        timeout: float,
        on_phase: Callable[[StartupPhase, str], None] | None,
        cancel: Callable[[], bool] | None,
    ) -> None:
        deadline = self._monotonic() + timeout
        url = health_url_for(server.spec.port)
        announced_loading = False

        while True:
            if cancel is not None and cancel():
                raise ServerStartError(
                    SetupFailure(
                        kind=FailureKind.CANCELLED,
                        message="Starting the model was cancelled.",
                        actions=(RecoveryAction.RETRY, RecoveryAction.SKIP_FOR_NOW),
                    ),
                    server.logs.text(),
                )

            exit_code = server.process.poll()
            if exit_code is not None:
                # The child is gone; its output is the whole explanation.
                self._sleep(0.05)
                text = server.logs.text()
                raise ServerStartError(
                    classify_startup_failure(text, timed_out=False), text
                )

            ready, status, _ = self._readiness(url)
            if ready:
                return
            if status == 503 and not announced_loading and on_phase:
                # llama.cpp answers 503 while the weights are still being
                # read: the server is up, the model is not. Two different
                # things to tell a person waiting.
                announced_loading = True
                on_phase(StartupPhase.LOADING_MODEL, "Loading the model into memory…")

            if self._monotonic() >= deadline:
                text = server.logs.text()
                raise ServerStartError(classify_startup_failure(text, timed_out=True), text)
            self._sleep(0.25)

    # -- health and restart --------------------------------------------------

    def is_healthy(self) -> bool:
        server = self.running
        if server is None:
            return False
        ready, _, detail = self._readiness(health_url_for(server.spec.port))
        state = load_runtime_state(self._paths.state_path)
        save_runtime_state(
            self._paths.state_path,
            state.model_copy(
                update={
                    "health": HealthRecord(
                        checked_at_utc=now_iso(), healthy=ready, detail=detail
                    )
                }
            ),
        )
        return ready

    def ensure_ready(
        self,
        spec: LaunchSpec,
        *,
        on_phase: Callable[[StartupPhase, str], None] | None = None,
    ) -> RunningServer:
        """The call a reading makes. Reuses a healthy server, and restarts
        a dead one exactly once (M16.7e).

        The bound matters: an interpretation that quietly restarts a
        crashing server forever turns one bad configuration into a machine
        that thrashes. One retry, then the failure is surfaced and the
        reading follows the established retryable path - card and transit
        snapshot untouched, never a redraw.
        """
        # `reclaim` first, so a server an earlier run left behind is
        # reused rather than duplicated: starting a second one would load
        # the same weights into the same machine twice (M25.2).
        server = self.running or self.reclaim(spec)
        if server is not None and server.spec.model_path == spec.model_path:
            if self.is_healthy():
                return server
        self._restarts += 1
        if self._restarts > 2:
            raise ServerStartError(
                SetupFailure(
                    kind=FailureKind.PROCESS_CRASHED,
                    message="The local model keeps stopping, so Syzygy stopped restarting it.",
                    detail="two consecutive start attempts failed",
                    actions=(
                        RecoveryAction.REPAIR,
                        RecoveryAction.USE_EXISTING_SERVER,
                        RecoveryAction.COPY_DIAGNOSTICS,
                    ),
                )
            )
        started = self.start(spec, on_phase=on_phase)
        self._restarts = 0
        return started

    # -- stopping ------------------------------------------------------------

    def stop(self) -> None:
        """Terminate the server *this run owns*, gracefully then not.

        Bounded at every step. Quitting Syzygy must not wait on a wedged
        child, so a process that ignores both signals is abandoned with the
        state cleared rather than waited on forever.

        Owning it is the precondition, and it is what this used to get
        wrong: with nothing running it cleared the record anyway, which
        erased the only handle anyone had on a server a previous run left
        behind - `syzygy model local status` stopped seeing it and
        `syzygy model local stop` could no longer stop it. A record this
        run did not put there is left alone here and dealt with where
        there is a `LaunchSpec` to compare it against (`reclaim`), or on
        request (`release_recorded`).
        """
        server = self._server
        self._server = None
        if server is None:
            return
        if server.process.poll() is None:
            self._terminate(server.process)
        self._clear_record_for(server)

    def _terminate(self, process: ServerProcess) -> None:
        """SIGTERM, then SIGKILL, then give up. Never waits unbounded."""
        with contextlib.suppress(Exception):
            process.terminate()
        with contextlib.suppress(Exception):
            process.wait(timeout=TERMINATE_GRACE_SECONDS)
        if process.poll() is None:
            with contextlib.suppress(Exception):
                process.kill()
            with contextlib.suppress(Exception):
                process.wait(timeout=KILL_GRACE_SECONDS)

    # -- crash recovery ------------------------------------------------------

    def reclaim(self, spec: LaunchSpec) -> RunningServer | None:
        """Take responsibility for a server an earlier run left behind.

        One of three things happens to a record, and the process it names
        is never simply forgotten:

        * **it verifies, answers, and was launched to serve exactly what
          `spec` asks for** - adopt it as this run's server, so the model
          is not loaded into memory a second time and quitting Syzygy
          still stops it;
        * **it verifies but is wedged, or is serving something else** -
          stop it, then clear the record. It is provably Syzygy's own
          process and this run is replacing it; leaving it is the orphan
          the class docstring forbids;
        * **it cannot be verified** - clear the record and signal nothing.
          A PID that has been reused belongs to someone else now.

        Returns the adopted server, or `None` in the other two cases (the
        caller starts a fresh one). The adopted `LaunchSpec` is rebuilt
        from the *record*, not from `spec`: the port and start token
        belong to the process that is actually running, and describing it
        with the arguments we would have used is how a supervisor comes to
        believe a server has a context size it was never given.
        """
        state = load_runtime_state(self._paths.state_path)
        identity = state.process
        if identity is None:
            return None

        verified, _reason = verify_recorded_process(identity, self._probe)
        if not verified:
            self._clear_record()
            return None

        adopted = self._adopted_spec(identity, spec)
        if adopted is None or not self._readiness(health_url_for(identity.port))[0]:
            self.release_recorded()
            return None

        server = RunningServer(
            spec=adopted,
            process=self._adopt(identity.pid),
            # The earlier run's log file, if it named one: an adopted
            # server's history is on disk, not in this process's memory.
            logs=LogBuffer(Path(identity.log_path) if identity.log_path else None),
            started_at=self._monotonic(),
        )
        self._server = server
        return server

    def _adopted_spec(self, identity: ProcessIdentity, spec: LaunchSpec) -> LaunchSpec | None:
        """The recorded server as a `LaunchSpec`, or `None` if it is not
        serving what `spec` asks for.

        An older record carries no launch shape at all. That is not a
        failure to report, but it cannot be shown to match either, so it
        takes the same route as a mismatch: stopped and replaced.
        """
        launch = identity.launch
        if launch is None:
            return None
        if identity.executable != str(spec.executable) or identity.model_path != str(
            spec.model_path
        ):
            return None
        if (
            launch.context_tokens != spec.context_tokens
            or launch.max_output_tokens != spec.max_output_tokens
            or launch.served_model_id != spec.served_model_id
            or launch.threads != spec.threads
            or launch.gpu_layers != spec.gpu_layers
        ):
            return None
        return LaunchSpec(
            executable=Path(identity.executable),
            model_path=Path(identity.model_path),
            port=identity.port,
            context_tokens=launch.context_tokens,
            max_output_tokens=launch.max_output_tokens,
            served_model_id=launch.served_model_id,
            threads=launch.threads,
            gpu_layers=launch.gpu_layers,
            backend=Backend(launch.backend) if launch.backend else spec.backend,
            start_token=identity.start_token,
        )

    def release_recorded(self) -> None:
        """Stop the process named in the state file if it is provably ours,
        then clear the record. Signals nothing it could not identify.

        Public because `syzygy model local stop` is exactly this operation
        and must not grow a second implementation of it.
        """
        state = load_runtime_state(self._paths.state_path)
        identity = state.process
        if identity is None:
            return
        verified, _reason = verify_recorded_process(identity, self._probe)
        if verified:
            self._terminate(self._adopt(identity.pid))
        self._clear_record()

    def _adopt(self, pid: int) -> AdoptedProcess:
        return AdoptedProcess(
            pid,
            exists=self._exists,
            signal_=self._signal,
            sleep=self._sleep,
            monotonic=self._monotonic,
        )

    def _record(self, server: RunningServer, log_path: Path) -> None:
        state = load_runtime_state(self._paths.state_path)
        save_runtime_state(
            self._paths.state_path,
            state.model_copy(
                update={
                    "process": ProcessIdentity(
                        pid=server.process.pid,
                        executable=str(server.spec.executable),
                        start_token=server.spec.start_token,
                        started_at_utc=now_iso(),
                        port=server.spec.port,
                        model_path=str(server.spec.model_path),
                        log_path=str(log_path),
                        launch=RecordedLaunch(
                            context_tokens=server.spec.context_tokens,
                            max_output_tokens=server.spec.max_output_tokens,
                            served_model_id=server.spec.served_model_id,
                            threads=server.spec.threads,
                            gpu_layers=server.spec.gpu_layers,
                            backend=server.spec.backend.value,
                        ),
                    )
                }
            ),
        )

    def _clear_record_for(self, server: RunningServer) -> None:
        """Clear the record only while it still names `server`.

        Two Syzygys can be open at once. Whichever quits second must not
        erase the record of the one still running.
        """
        state = load_runtime_state(self._paths.state_path)
        if state.process is None or state.process.start_token != server.spec.start_token:
            return
        save_runtime_state(self._paths.state_path, state.model_copy(update={"process": None}))

    def _clear_record(self) -> None:
        state = load_runtime_state(self._paths.state_path)
        if state.process is None:
            return
        save_runtime_state(self._paths.state_path, state.model_copy(update={"process": None}))
