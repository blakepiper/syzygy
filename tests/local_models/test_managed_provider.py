"""On-demand start, and the shutdown contract (M16.7b/e, M16.8d).

The provider is exercised with a fake supervisor: no process is spawned,
and no HTTP happens beyond a `MockTransport`.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from syzygy.local_models.managed_provider import ManagedLocalProvider
from syzygy.local_models.settings import (
    LaunchProfile,
    LocalModelSettings,
    ManagementMode,
    ModelRecord,
    RuntimeRecord,
    save_local_model_settings,
)
from syzygy.local_models.supervisor import LaunchSpec, ServerStartError


class FakeSupervisor:
    def __init__(self, *, base_url: str = "http://127.0.0.1:18080/v1") -> None:
        self.specs: list[LaunchSpec] = []
        self.stopped = 0
        self.running = None
        self._base_url = base_url
        self.raises: Exception | None = None

    def ensure_ready(self, spec: LaunchSpec, *, on_phase=None):
        if self.raises is not None:
            raise self.raises
        self.specs.append(spec)

        class _Server:
            base_url = self._base_url

        return _Server()

    def stop(self) -> None:
        self.stopped += 1


def configure(settings_path: Path, tmp_path: Path, *, external: str | None = None) -> None:
    model = tmp_path / "model.gguf"
    model.write_bytes(b"\0" * 64)
    runtime = tmp_path / "llama-server"
    runtime.write_text("x")
    save_local_model_settings(
        settings_path,
        LocalModelSettings(
            mode=ManagementMode.MANAGED,
            runtime=RuntimeRecord(
                path=None if external else str(runtime),
                base_url=external,
                version="b10331",
            ),
            model=ModelRecord(
                path="" if external else str(model),
                size_bytes=64,
                served_model_id="qwen3-4b",
            ),
            launch=LaunchProfile(
                context_tokens=8192, max_output_tokens=1536, threads=6, gpu_layers=99
            ),
        ),
    )


def test_the_server_is_started_with_the_approved_launch_profile(
    settings_path, local_paths, tmp_path
) -> None:
    configure(settings_path, tmp_path)
    supervisor = FakeSupervisor()
    provider = ManagedLocalProvider(settings_path, local_paths, supervisor=supervisor)

    base_url = provider._ensure_running()

    assert base_url == "http://127.0.0.1:18080/v1"
    spec = supervisor.specs[0]
    # The persisted profile, not a freshly recomputed one: the user
    # approved these numbers.
    assert spec.threads == 6
    assert spec.gpu_layers == 99
    assert spec.context_tokens == 8192
    assert spec.served_model_id == "qwen3-4b"


def test_an_external_server_is_never_started(settings_path, local_paths, tmp_path) -> None:
    configure(settings_path, tmp_path, external="http://127.0.0.1:9999/v1")
    supervisor = FakeSupervisor()
    provider = ManagedLocalProvider(settings_path, local_paths, supervisor=supervisor)

    assert provider._ensure_running() == "http://127.0.0.1:9999/v1"
    assert supervisor.specs == []


def test_an_unconfigured_setup_refuses_rather_than_guessing(
    settings_path, local_paths
) -> None:
    provider = ManagedLocalProvider(settings_path, local_paths, supervisor=FakeSupervisor())

    with pytest.raises(RuntimeError, match="no local model is configured"):
        provider._ensure_running()


async def test_interpret_starts_the_server_then_delegates(
    settings_path, local_paths, tmp_path, monkeypatch
) -> None:
    from syzygy.local_models.verification import smoke_test_contexts

    configure(settings_path, tmp_path)
    supervisor = FakeSupervisor()
    provider = ManagedLocalProvider(settings_path, local_paths, supervisor=supervisor)

    reply = {
        "alignment_title": "t",
        "esoteric": {"summary": "s", "body": "b"},
        "conventional": {"summary": "s", "body": "b", "watch_for": [], "reflection": "r"},
        "source_chunk_ids": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(reply)}}]}
        )

    from syzygy.interpretation.providers import llama_cpp

    original = llama_cpp.LlamaCppProvider

    def with_transport(**kwargs):
        return original(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(llama_cpp, "LlamaCppProvider", with_transport)

    result = await provider.interpret(smoke_test_contexts()[0])

    assert result.alignment_title == "t"
    assert len(supervisor.specs) == 1


def test_a_start_failure_propagates_rather_than_degrading(
    settings_path, local_paths, tmp_path
) -> None:
    """The reading then follows the established retryable path: the card
    and transit snapshot stay committed, and nothing redraws."""
    from syzygy.local_models.contracts import FailureKind, SetupFailure

    configure(settings_path, tmp_path)
    supervisor = FakeSupervisor()
    supervisor.raises = ServerStartError(
        SetupFailure(kind=FailureKind.OUT_OF_MEMORY, message="not enough memory")
    )
    provider = ManagedLocalProvider(settings_path, local_paths, supervisor=supervisor)

    with pytest.raises(ServerStartError):
        provider._ensure_running()


def test_stopping_is_idempotent(settings_path, local_paths, tmp_path) -> None:
    configure(settings_path, tmp_path)
    supervisor = FakeSupervisor()
    provider = ManagedLocalProvider(settings_path, local_paths, supervisor=supervisor)

    provider.stop()
    provider.stop()

    assert supervisor.stopped == 2


# -- app wiring ---------------------------------------------------------------


def test_the_shutdown_hook_ignores_providers_that_have_no_server() -> None:
    from syzygy.interpretation.providers.fixture import FixtureProvider
    from syzygy.tui.app import stop_managed_model

    stop_managed_model(FixtureProvider())  # must not raise


def test_the_shutdown_hook_stops_a_managed_provider(
    settings_path, local_paths, tmp_path
) -> None:
    from syzygy.tui.app import stop_managed_model

    configure(settings_path, tmp_path)
    supervisor = FakeSupervisor()
    provider = ManagedLocalProvider(settings_path, local_paths, supervisor=supervisor)

    stop_managed_model(provider)

    assert supervisor.stopped == 1


def test_the_shutdown_hook_swallows_a_failing_stop() -> None:
    from syzygy.tui.app import stop_managed_model

    class Explodes:
        def stop(self):
            raise OSError("no")

    stop_managed_model(Explodes())  # quitting must not become a traceback


def test_startup_ignores_a_setup_that_needs_repair(tmp_path, monkeypatch) -> None:
    """M16.8d: a broken managed model falls back to fixture with a reason,
    and never blocks startup."""
    from syzygy.tui.app import _managed_local_provider

    settings = tmp_path / "settings.json"
    configure(settings, tmp_path)
    (tmp_path / "model.gguf").unlink()

    provider, reason = _managed_local_provider(settings)

    assert provider is None
    assert reason is not None and "repair" in reason


def test_startup_reports_nothing_when_no_local_model_was_ever_set_up(tmp_path) -> None:
    from syzygy.tui.app import _managed_local_provider

    provider, reason = _managed_local_provider(tmp_path / "settings.json")

    assert provider is None
    assert reason is None
