"""The provider a reading actually calls when a managed local model is
configured (M16.7b, M16.7e).

`LlamaCppProvider` talks to a server that is already listening. Nothing
was listening a moment ago, because Syzygy starts the model *on demand* -
so this sits in front of it and makes sure there is one, then delegates.

That is the whole of the class. It adds no prompt, sees no extra context,
and returns exactly what the underlying provider returns:
`InterpretationContext` remains the entire input surface, and the
transport stays in `syzygy.interpretation.providers`.

**One restart, then stop.** If the server has died, `ensure_ready`
restarts it once. If that fails too, the error propagates and the reading
takes the path it already has for a provider failure - the card and the
transit snapshot stay exactly as committed, `INTERPRETATION_FAILED` is
retryable, and nothing redraws (`AGENTS.md`'s first invariant).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from syzygy.domain.interpretation import (
    InterpretationContext,
    InterpretationResult,
    SummaryResult,
)
from syzygy.local_models.contracts import Backend
from syzygy.local_models.paths import LocalModelPaths
from syzygy.local_models.settings import LocalModelSettings, load_local_model_settings
from syzygy.local_models.supervisor import LaunchSpec, ServerSupervisor, lease_port


class ManagedLocalProvider:
    """Starts the configured local server if needed, then delegates."""

    provider_id = "llama_cpp"

    def __init__(
        self,
        settings_path: Path,
        paths: LocalModelPaths,
        *,
        supervisor: ServerSupervisor | None = None,
    ) -> None:
        self._settings_path = settings_path
        self._paths = paths
        self._supervisor = supervisor or ServerSupervisor(paths)
        settings = load_local_model_settings(settings_path)
        self.model_id = settings.model.served_model_id if settings.model else "local"

    @property
    def supervisor(self) -> ServerSupervisor:
        return self._supervisor

    async def interpret(self, context: InterpretationContext) -> InterpretationResult:
        provider = await self._ready_provider()
        return await provider.interpret(context)

    async def summarize(self, context: InterpretationContext) -> SummaryResult:
        provider = await self._ready_provider()
        return await provider.summarize(context)

    async def _ready_provider(self):
        from syzygy.interpretation.providers.llama_cpp import (
            LOCAL_TIMEOUT_SECONDS,
            LlamaCppProvider,
        )

        base_url = await asyncio.to_thread(self._ensure_running)
        return LlamaCppProvider(
            model_id=self.model_id, base_url=base_url, timeout=LOCAL_TIMEOUT_SECONDS
        )

    def _ensure_running(self) -> str:
        """Blocking, and deliberately run off the event loop.

        Starting a server means waiting for gigabytes of weights to be read
        from disk. Doing that on the loop would freeze the interface,
        including the animation that is meant to be covering the wait.
        """
        settings = load_local_model_settings(self._settings_path)
        if settings.runtime is not None and settings.runtime.base_url:
            # External mode: the user runs the server, Syzygy only talks
            # to it. Nothing to start, and nothing to stop later.
            return settings.runtime.base_url

        spec = self._launch_spec(settings)
        server = self._supervisor.ensure_ready(spec)
        return server.base_url

    def _launch_spec(self, settings: LocalModelSettings) -> LaunchSpec:
        from syzygy.local_models.fit import SYZYGY_CONTEXT_TOKENS, SYZYGY_MAX_OUTPUT_TOKENS

        if settings.model is None or settings.runtime is None or not settings.runtime.path:
            raise RuntimeError("no local model is configured")
        launch = settings.launch
        running = self._supervisor.running
        return LaunchSpec(
            executable=Path(settings.runtime.path),
            model_path=Path(settings.model.path),
            # Reuse the port a live server already holds; otherwise lease.
            port=running.spec.port if running is not None else lease_port(),
            context_tokens=launch.context_tokens if launch else SYZYGY_CONTEXT_TOKENS,
            max_output_tokens=(
                launch.max_output_tokens if launch else SYZYGY_MAX_OUTPUT_TOKENS
            ),
            served_model_id=settings.model.served_model_id,
            threads=launch.threads if launch else None,
            gpu_layers=launch.gpu_layers if launch else None,
            backend=settings.runtime.backend or Backend.CPU,
        )

    def stop(self) -> None:
        """Called when Syzygy exits. Idempotent, and bounded - the app must
        quit promptly even if the child ignores its signals."""
        self._supervisor.stop()
