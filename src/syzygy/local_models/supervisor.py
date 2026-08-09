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
    ) -> None:
        self._paths = paths
        self._probe = probe or Probe.real()
        self._spawn = spawn
        self._readiness = readiness
        self._sleep = sleep
        self._monotonic = monotonic
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
        server = self.running
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
        """Terminate the managed server, gracefully then not.

        Bounded at every step. Quitting Syzygy must not wait on a wedged
        child, so a process that ignores both signals is abandoned with the
        state cleared rather than waited on forever.
        """
        server = self._server
        self._server = None
        if server is None:
            self._clear_record()
            return
        if server.process.poll() is not None:
            self._clear_record()
            return
        with contextlib.suppress(Exception):
            server.process.terminate()
        with contextlib.suppress(Exception):
            server.process.wait(timeout=TERMINATE_GRACE_SECONDS)
        if server.process.poll() is None:
            with contextlib.suppress(Exception):
                server.process.kill()
            with contextlib.suppress(Exception):
                server.process.wait(timeout=KILL_GRACE_SECONDS)
        self._clear_record()

    # -- crash recovery ------------------------------------------------------

    def adopt_or_clean(self) -> ProcessIdentity | None:
        """At startup: is the recorded process still ours?

        Returns the identity if it verified (so the app can reuse the
        server instead of starting another), or `None` after clearing a
        record it could not verify. Never signals anything - reclaiming
        and killing are different operations, and only the first is safe
        to do without asking.
        """
        state = load_runtime_state(self._paths.state_path)
        identity = state.process
        if identity is None:
            return None
        verified, _reason = verify_recorded_process(identity, self._probe)
        if not verified:
            self._clear_record()
            return None
        ready, _, _ = self._readiness(health_url_for(identity.port))
        if not ready:
            self._clear_record()
            return None
        return identity

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
                    )
                }
            ),
        )

    def _clear_record(self) -> None:
        state = load_runtime_state(self._paths.state_path)
        if state.process is None:
            return
        save_runtime_state(self._paths.state_path, state.model_copy(update={"process": None}))
