"""The managed server process (M16.7f).

Every case uses a fake process and a fake readiness probe. Nothing here
spawns anything, binds anything (beyond asking the OS for a free port),
or signals a real PID.
"""

from __future__ import annotations

import os
import signal
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from syzygy.local_models.contracts import FailureKind
from syzygy.local_models.runtime_state import ProcessIdentity, load_runtime_state
from syzygy.local_models.supervisor import (
    LaunchSpec,
    LogBuffer,
    ServerStartError,
    ServerSupervisor,
    StartupPhase,
    build_argv,
    classify_startup_failure,
    health_url_for,
    lease_port,
    startup_timeout_for,
    verify_recorded_process,
)

from .machines import make_probe, ok


class FakeProcess:
    """A `ServerProcess` that does exactly what a test tells it to."""

    def __init__(self, *, exit_after: int | None = None, output: str = "") -> None:
        self.pid = 4242
        self._polls = 0
        self._exit_after = exit_after
        self.terminated = False
        self.killed = False
        self._returncode: int | None = None
        self.stdout = iter(output.splitlines(keepends=True)) if output else None

    def poll(self) -> int | None:
        self._polls += 1
        if self._exit_after is not None and self._polls > self._exit_after:
            self._returncode = 1
        return self._returncode

    def terminate(self) -> None:
        self.terminated = True
        self._returncode = -15

    def kill(self) -> None:
        self.killed = True
        self._returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        return self._returncode if self._returncode is not None else 0


class IgnoresSignals(FakeProcess):
    """A wedged child: terminate does nothing, kill does nothing. Quitting
    must still return promptly."""

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float | None = None) -> int:
        raise TimeoutError("still running")

    def poll(self) -> int | None:
        return None


def spec_for(tmp_path: Path, **overrides) -> LaunchSpec:
    model = tmp_path / "model.gguf"
    model.write_bytes(b"\0" * 1024)
    executable = tmp_path / "llama-server"
    executable.write_text("#!/bin/sh\n")
    defaults = dict(
        executable=executable,
        model_path=model,
        port=18080,
        context_tokens=8192,
        max_output_tokens=1536,
        threads=4,
        gpu_layers=0,
        start_token="token-abc",
    )
    defaults.update(overrides)
    return LaunchSpec(**defaults)


def supervisor_with(local_paths, process, *, ready_after: int = 1, statuses=None, **kwargs):
    spawned: list[tuple[tuple[str, ...], Mapping[str, str]]] = []

    def spawn(argv: Sequence[str], env: Mapping[str, str]):
        spawned.append((tuple(argv), dict(env)))
        return process

    calls = {"n": 0}
    sequence = list(statuses or [])

    def readiness(url: str) -> tuple[bool, int | None, str | None]:
        calls["n"] += 1
        if sequence:
            return sequence.pop(0)
        return (calls["n"] >= ready_after, 200 if calls["n"] >= ready_after else 503, None)

    supervisor = ServerSupervisor(
        local_paths,
        probe=make_probe(),
        spawn=spawn,
        readiness=readiness,
        sleep=lambda _seconds: None,
        monotonic=_ticking(),
        **kwargs,
    )
    return supervisor, spawned


def _ticking(step: float = 0.5):
    state = {"t": 0.0}

    def monotonic() -> float:
        state["t"] += step
        return state["t"]

    return monotonic


# -- argv --------------------------------------------------------------------


def test_argv_binds_to_localhost_and_carries_no_reading_content(tmp_path) -> None:
    argv = build_argv(spec_for(tmp_path, served_model_id="qwen3-8b"))

    assert "--host" in argv and argv[argv.index("--host") + 1] == "127.0.0.1"
    assert "0.0.0.0" not in argv
    assert "--ctx-size" in argv and argv[argv.index("--ctx-size") + 1] == "8192"
    assert "--n-predict" in argv and argv[argv.index("--n-predict") + 1] == "1536"
    assert "--no-webui" in argv
    assert argv[argv.index("--alias") + 1] == "qwen3-8b"
    # No prompt, profile, card, or date reaches the process list.
    joined = " ".join(argv).lower()
    for forbidden in ("prompt", "profile", "card", "tarot", "reading"):
        assert forbidden not in joined


def test_optional_flags_are_omitted_rather_than_passed_as_none(tmp_path) -> None:
    argv = build_argv(spec_for(tmp_path, threads=None, gpu_layers=None))

    assert "--threads" not in argv
    assert "--n-gpu-layers" not in argv


def test_the_startup_timeout_scales_with_the_model(tmp_path) -> None:
    small = tmp_path / "small.gguf"
    small.write_bytes(b"\0" * 1024)
    assert startup_timeout_for(small) < startup_timeout_for(Path("/nonexistent"))


def test_leasing_a_port_gives_something_usable() -> None:
    port = lease_port()
    assert 1024 < port < 65536


# -- starting ----------------------------------------------------------------


def test_a_successful_start_records_a_verifiable_identity(local_paths, tmp_path) -> None:
    process = FakeProcess()
    supervisor, spawned = supervisor_with(local_paths, process)
    phases: list[StartupPhase] = []

    server = supervisor.start(
        spec_for(tmp_path), on_phase=lambda phase, _text: phases.append(phase)
    )

    assert server.base_url == "http://127.0.0.1:18080/v1"
    assert phases[0] is StartupPhase.LAUNCHING
    assert phases[-1] is StartupPhase.READY

    identity = load_runtime_state(local_paths.state_path).process
    assert identity is not None
    assert identity.pid == 4242
    assert identity.start_token == "token-abc"
    assert identity.port == 18080

    # The token reaches the child, and no shell is involved.
    _argv, env = spawned[0]
    assert env["SYZYGY_LOCAL_MODEL_TOKEN"] == "token-abc"


def test_a_loading_server_announces_the_loading_phase(local_paths, tmp_path) -> None:
    supervisor, _ = supervisor_with(
        local_paths,
        FakeProcess(),
        statuses=[(False, 503, "loading"), (False, 503, "loading"), (True, 200, None)],
    )
    phases: list[StartupPhase] = []

    supervisor.start(spec_for(tmp_path), on_phase=lambda phase, _t: phases.append(phase))

    assert StartupPhase.LOADING_MODEL in phases


def test_a_process_that_exits_is_diagnosed_from_its_output(local_paths, tmp_path) -> None:
    process = FakeProcess(exit_after=0, output="ggml_backend_alloc: out of memory\n")
    supervisor, _ = supervisor_with(local_paths, process, ready_after=99)

    with pytest.raises(ServerStartError) as caught:
        supervisor.start(spec_for(tmp_path))

    assert caught.value.failure.kind is FailureKind.OUT_OF_MEMORY
    assert caught.value.failure.retryable is False


def test_a_startup_timeout_is_reported_as_a_timeout(local_paths, tmp_path) -> None:
    supervisor, _ = supervisor_with(local_paths, FakeProcess(), ready_after=10**6)

    with pytest.raises(ServerStartError) as caught:
        supervisor.start(spec_for(tmp_path), timeout=2.0)

    assert caught.value.failure.kind is FailureKind.STARTUP_TIMEOUT


def test_cancelling_a_start_stops_promptly_and_leaves_nothing_running(
    local_paths, tmp_path
) -> None:
    process = FakeProcess()
    supervisor, _ = supervisor_with(local_paths, process, ready_after=10**6)

    with pytest.raises(ServerStartError) as caught:
        supervisor.start(spec_for(tmp_path), cancel=lambda: True)

    assert caught.value.failure.kind is FailureKind.CANCELLED
    assert process.terminated is True
    assert load_runtime_state(local_paths.state_path).process is None


def test_a_failed_spawn_is_a_typed_failure(local_paths, tmp_path) -> None:
    def refuse(argv, env):
        raise OSError("exec format error")

    supervisor = ServerSupervisor(
        local_paths,
        probe=make_probe(),
        spawn=refuse,
        readiness=lambda _url: (False, None, None),
        sleep=lambda _s: None,
    )

    with pytest.raises(ServerStartError) as caught:
        supervisor.start(spec_for(tmp_path))

    assert caught.value.failure.kind is FailureKind.PROCESS_CRASHED


# -- stopping ----------------------------------------------------------------


def test_stopping_terminates_gracefully_and_clears_the_record(local_paths, tmp_path) -> None:
    process = FakeProcess()
    supervisor, _ = supervisor_with(local_paths, process)
    supervisor.start(spec_for(tmp_path))

    supervisor.stop()

    assert process.terminated is True
    assert process.killed is False
    assert load_runtime_state(local_paths.state_path).process is None


def test_a_wedged_child_is_killed_and_never_waited_on_forever(local_paths, tmp_path) -> None:
    process = IgnoresSignals()
    supervisor, _ = supervisor_with(local_paths, process)
    supervisor.start(spec_for(tmp_path))

    supervisor.stop()  # must return; a hang here would hang quitting Syzygy

    assert process.terminated is True
    assert process.killed is True
    assert load_runtime_state(local_paths.state_path).process is None


def test_stopping_when_nothing_runs_is_a_no_op(local_paths) -> None:
    supervisor, _ = supervisor_with(local_paths, FakeProcess())
    supervisor.stop()


# -- health and restart ------------------------------------------------------


def test_ensure_ready_reuses_a_healthy_server(local_paths, tmp_path) -> None:
    supervisor, spawned = supervisor_with(local_paths, FakeProcess())
    spec = spec_for(tmp_path)
    supervisor.start(spec)

    supervisor.ensure_ready(spec)

    assert len(spawned) == 1


def test_ensure_ready_restarts_a_dead_server_once(local_paths, tmp_path) -> None:
    supervisor, spawned = supervisor_with(local_paths, FakeProcess())
    spec = spec_for(tmp_path)
    supervisor.start(spec)
    supervisor._server = None  # the process went away between readings

    supervisor.ensure_ready(spec)

    assert len(spawned) == 2


def test_repeated_start_failures_stop_being_retried(local_paths, tmp_path) -> None:
    supervisor, _ = supervisor_with(local_paths, FakeProcess(exit_after=0), ready_after=10**6)
    spec = spec_for(tmp_path)

    for _ in range(2):
        with pytest.raises(ServerStartError):
            supervisor.ensure_ready(spec)

    with pytest.raises(ServerStartError) as caught:
        supervisor.ensure_ready(spec)
    assert "keeps stopping" in caught.value.failure.message


# -- crash recovery ----------------------------------------------------------


def identity(**overrides) -> ProcessIdentity:
    defaults = dict(
        pid=os.getpid(),
        executable="/opt/syzygy/llama-server",
        start_token="token",
        started_at_utc="2026-01-01T00:00:00+00:00",
        port=18080,
        model_path="/models/model.gguf",
    )
    defaults.update(overrides)
    return ProcessIdentity(**defaults)


def test_a_matching_command_line_verifies() -> None:
    probe = make_probe(
        files={
            f"/proc/{os.getpid()}/cmdline": (
                "/opt/syzygy/llama-server\0--model\0/models/model.gguf\0--port\018080"
            )
        }
    )
    verified, _ = verify_recorded_process(identity(), probe)
    assert verified is True


def test_a_reused_pid_running_something_else_is_refused() -> None:
    probe = make_probe(files={f"/proc/{os.getpid()}/cmdline": "/usr/bin/some-other-program"})
    verified, reason = verify_recorded_process(identity(), probe)

    assert verified is False
    assert "different program" in reason


def test_a_process_serving_a_different_model_is_refused() -> None:
    probe = make_probe(
        files={
            f"/proc/{os.getpid()}/cmdline": "/opt/syzygy/llama-server\0--model\0/other.gguf"
        }
    )
    verified, _ = verify_recorded_process(identity(), probe)
    assert verified is False


def test_an_unreadable_command_line_means_we_will_not_touch_it() -> None:
    """The conservative answer, and it has teeth: an unverifiable process
    is never signalled, and its state is cleaned up instead."""
    verified, reason = verify_recorded_process(identity(), make_probe())

    assert verified is False
    assert "won't touch it" in reason


def test_a_dead_pid_is_refused() -> None:
    verified, reason = verify_recorded_process(identity(pid=2**30), make_probe())

    assert verified is False
    assert "no longer running" in reason


# -- succession: what happens to a server a previous run left behind ---------


class FakeMachine:
    """A process table the test owns.

    Every signal in these cases goes here. The verified fixtures record
    the test runner's own PID (it is the one process guaranteed to exist),
    so a case that reached the real `os.kill` would end the run.
    """

    def __init__(self, *alive: int, wedged: tuple[int, ...] = ()) -> None:
        self.alive = set(alive)
        self.wedged = set(wedged)
        self.signals: list[tuple[int, int]] = []

    def exists(self, pid: int) -> bool:
        return pid in self.alive

    def signal(self, pid: int, sig: int) -> None:
        self.signals.append((pid, sig))
        if pid not in self.wedged:
            self.alive.discard(pid)

    @property
    def signalled(self) -> list[int]:
        return [pid for pid, _sig in self.signals]


def recorded_launch(**overrides):
    from syzygy.local_models.runtime_state import RecordedLaunch

    defaults = dict(
        context_tokens=8192,
        max_output_tokens=1536,
        served_model_id="local",
        threads=4,
        gpu_layers=0,
        backend="cpu",
    )
    defaults.update(overrides)
    return RecordedLaunch(**defaults)


def _record(local_paths, identity_) -> None:
    from syzygy.local_models.runtime_state import LocalRuntimeState, save_runtime_state

    save_runtime_state(local_paths.state_path, LocalRuntimeState(process=identity_))


def _left_running(tmp_path, **overrides):
    """A record of a server an earlier run started and never stopped."""
    model = tmp_path / "model.gguf"
    executable = tmp_path / "llama-server"
    defaults = dict(
        pid=os.getpid(),
        executable=str(executable),
        model_path=str(model),
        port=18081,
        start_token="token-earlier-run",
        launch=recorded_launch(),
    )
    defaults.update(overrides)
    return identity(**defaults)


def _sees(tmp_path, pid: int = None):
    """A probe whose `/proc` says that PID is the recorded server."""
    pid = os.getpid() if pid is None else pid
    return make_probe(
        files={
            f"/proc/{pid}/cmdline": (
                f"{tmp_path / 'llama-server'}\0--model\0{tmp_path / 'model.gguf'}"
            )
        }
    )


def _supervisor(local_paths, tmp_path, machine, *, ready: bool = True, process=None):
    spawned: list[tuple[str, ...]] = []

    def spawn(argv, _env):
        spawned.append(tuple(argv))
        return process or FakeProcess()

    supervisor = ServerSupervisor(
        local_paths,
        probe=_sees(tmp_path),
        spawn=spawn,
        readiness=lambda _url: (ready, 200 if ready else 503, None),
        sleep=lambda _s: None,
        monotonic=_ticking(),
        exists=machine.exists,
        signal_=machine.signal,
    )
    return supervisor, spawned


def test_reclaim_adopts_a_healthy_server_launched_the_way_this_run_wants(
    local_paths, tmp_path
) -> None:
    """The whole point: the weights are already in memory, so use them."""
    _record(local_paths, _left_running(tmp_path))
    machine = FakeMachine(os.getpid())
    supervisor, spawned = _supervisor(local_paths, tmp_path, machine)

    server = supervisor.reclaim(spec_for(tmp_path, port=19999))

    assert server is not None
    assert spawned == []
    assert machine.signals == []
    # The adopted server is described by the record, not by what this run
    # would have launched: it is listening where it is listening.
    assert server.spec.port == 18081
    assert server.base_url == "http://127.0.0.1:18081/v1"
    assert supervisor.running is server


def test_reclaim_stops_a_wedged_server_rather_than_leaving_it_behind(
    local_paths, tmp_path
) -> None:
    _record(local_paths, _left_running(tmp_path))
    machine = FakeMachine(os.getpid())
    supervisor, _ = _supervisor(local_paths, tmp_path, machine, ready=False)

    assert supervisor.reclaim(spec_for(tmp_path)) is None
    assert machine.signalled == [os.getpid()]
    assert not machine.exists(os.getpid())
    assert load_runtime_state(local_paths.state_path).process is None


def test_reclaim_replaces_a_server_launched_with_a_different_context(
    local_paths, tmp_path
) -> None:
    """M24's failure mode, from the other side: reusing an 8192-token
    server while believing it has 16384 puts prompts back over the line."""
    _record(local_paths, _left_running(tmp_path, launch=recorded_launch(context_tokens=4096)))
    machine = FakeMachine(os.getpid())
    supervisor, _ = _supervisor(local_paths, tmp_path, machine)

    assert supervisor.reclaim(spec_for(tmp_path, context_tokens=8192)) is None
    assert machine.signalled == [os.getpid()]
    assert load_runtime_state(local_paths.state_path).process is None


def test_a_record_with_no_launch_shape_is_replaced_not_reused(local_paths, tmp_path) -> None:
    """Written before the shape was recorded: it cannot be shown to match,
    so it takes the same route as a mismatch."""
    _record(local_paths, _left_running(tmp_path, launch=None))
    machine = FakeMachine(os.getpid())
    supervisor, _ = _supervisor(local_paths, tmp_path, machine)

    assert supervisor.reclaim(spec_for(tmp_path)) is None
    assert machine.signalled == [os.getpid()]


def test_reclaim_never_signals_a_process_it_cannot_verify(local_paths, tmp_path) -> None:
    """A PID that has been reused belongs to someone else now."""
    _record(local_paths, _left_running(tmp_path, pid=2**30))
    machine = FakeMachine(2**30)
    supervisor, _ = _supervisor(local_paths, tmp_path, machine)

    assert supervisor.reclaim(spec_for(tmp_path)) is None
    assert machine.signals == []
    assert load_runtime_state(local_paths.state_path).process is None


def test_ensure_ready_reuses_the_adopted_server_instead_of_starting_a_second(
    local_paths, tmp_path
) -> None:
    """The defect this milestone exists for: one machine, one server."""
    _record(local_paths, _left_running(tmp_path))
    machine = FakeMachine(os.getpid())
    supervisor, spawned = _supervisor(local_paths, tmp_path, machine)

    server = supervisor.ensure_ready(spec_for(tmp_path, port=19999))

    assert spawned == []
    assert server.spec.port == 18081
    assert machine.signals == []


def test_starting_stops_the_server_a_previous_run_left_running(local_paths, tmp_path) -> None:
    """An explicit start replaces it - and the old one goes down before
    the new one comes up, so the machine never holds both."""
    _record(local_paths, _left_running(tmp_path))
    machine = FakeMachine(os.getpid())
    fresh = FakeProcess()
    supervisor, spawned = _supervisor(local_paths, tmp_path, machine, process=fresh)

    supervisor.start(spec_for(tmp_path, port=19999))

    assert machine.signalled == [os.getpid()]
    assert len(spawned) == 1
    record = load_runtime_state(local_paths.state_path).process
    assert record is not None and record.pid == fresh.pid


def test_a_wedged_process_is_escalated_to_kill_and_never_waited_on_forever(
    local_paths, tmp_path
) -> None:
    _record(local_paths, _left_running(tmp_path))
    machine = FakeMachine(os.getpid(), wedged=(os.getpid(),))
    supervisor, _ = _supervisor(local_paths, tmp_path, machine, ready=False)

    supervisor.reclaim(spec_for(tmp_path))

    signals = [sig for _pid, sig in machine.signals]
    assert signal.SIGTERM in signals
    assert signal.SIGKILL in signals
    # It ignored both, so the record is cleared rather than waited on.
    assert load_runtime_state(local_paths.state_path).process is None


def test_stopping_leaves_alone_a_record_this_run_did_not_create(local_paths, tmp_path) -> None:
    """The erasure that made an orphan untraceable: with nothing of its
    own running, `stop` used to clear the record anyway - after which
    `model local status` could not see the process and `model local stop`
    could not stop it."""
    _record(local_paths, _left_running(tmp_path))
    machine = FakeMachine(os.getpid())
    supervisor, _ = _supervisor(local_paths, tmp_path, machine)

    supervisor.stop()

    assert machine.signals == []
    record = load_runtime_state(local_paths.state_path).process
    assert record is not None and record.pid == os.getpid()


def test_stopping_an_adopted_server_stops_it_and_clears_the_record(
    local_paths, tmp_path
) -> None:
    """Adoption is ownership: quitting Syzygy stops the server it took
    over, exactly as it stops one it spawned."""
    _record(local_paths, _left_running(tmp_path))
    machine = FakeMachine(os.getpid())
    supervisor, _ = _supervisor(local_paths, tmp_path, machine)
    supervisor.reclaim(spec_for(tmp_path))

    supervisor.stop()

    assert machine.signalled == [os.getpid()]
    assert load_runtime_state(local_paths.state_path).process is None


def test_quitting_does_not_erase_another_instances_record(local_paths, tmp_path) -> None:
    """Two Syzygys can be open at once. Whichever quits second must not
    erase the record of the one still running."""
    machine = FakeMachine(os.getpid())
    ours = FakeProcess()
    supervisor, _ = _supervisor(local_paths, tmp_path, machine, process=ours)
    supervisor.start(spec_for(tmp_path, port=19999))
    # Another instance starts its own server and records it.
    _record(local_paths, _left_running(tmp_path, start_token="token-other-instance"))

    supervisor.stop()

    record = load_runtime_state(local_paths.state_path).process
    assert record is not None and record.start_token == "token-other-instance"


def test_release_recorded_clears_a_stale_record_without_signalling(
    local_paths, tmp_path
) -> None:
    """What `syzygy model local stop` runs. Same rule, one implementation."""
    _record(local_paths, _left_running(tmp_path, pid=2**30))
    machine = FakeMachine(2**30)
    supervisor, _ = _supervisor(local_paths, tmp_path, machine)

    supervisor.release_recorded()

    assert machine.signals == []
    assert load_runtime_state(local_paths.state_path).process is None


# -- logs and classification -------------------------------------------------


def test_the_log_buffer_is_bounded_and_redacted(tmp_path) -> None:
    log = tmp_path / "server.log"
    buffer = LogBuffer(log, max_lines=5)
    for index in range(50):
        buffer.append(f"line {index} token hf_abcdefghijklmnop\n")

    text = buffer.text()
    assert len(text.splitlines()) == 5
    assert "hf_abcdefghijklmnop" not in text
    assert "hf_abcdefghijklmnop" not in log.read_text()


def test_the_log_file_stops_growing_at_the_cap(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("syzygy.local_models.supervisor.MAX_LOG_BYTES", 200)
    log = tmp_path / "server.log"
    buffer = LogBuffer(log)
    for index in range(200):
        buffer.append(f"a line of server output number {index}\n")

    assert log.stat().st_size < 400


@pytest.mark.parametrize(
    ("output", "kind"),
    [
        ("bind: address already in use", FailureKind.PORT_UNAVAILABLE),
        ("ggml: failed to allocate 8 GiB", FailureKind.OUT_OF_MEMORY),
        ("error: unknown model architecture 'wat'", FailureKind.MODEL_LOAD_FAILED),
        ("failed to apply template: jinja error", FailureKind.CHAT_TEMPLATE_FAILED),
        ("vulkan: no devices found", FailureKind.BACKEND_FAILED),
        ("something entirely unexpected", FailureKind.PROCESS_CRASHED),
    ],
)
def test_each_startup_failure_gets_its_own_kind(output: str, kind: FailureKind) -> None:
    failure = classify_startup_failure(output, timed_out=False)

    assert failure.kind is kind
    assert failure.actions


def test_a_timeout_with_no_signature_is_a_timeout() -> None:
    assert (
        classify_startup_failure("loading model...", timed_out=True).kind
        is FailureKind.STARTUP_TIMEOUT
    )


def test_health_url_is_localhost() -> None:
    assert health_url_for(9999) == "http://127.0.0.1:9999/health"


def test_ok_helper_is_available_for_other_modules() -> None:
    assert ok("x").ok is True
