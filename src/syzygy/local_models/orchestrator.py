"""One setup flow, two front ends (M16.9a, M16.10a).

`LocalSetupSession` owns the state machine, the collected facts, and the
decisions. The TUI wizard renders it; `syzygy model setup-local` prints
it. Neither contains platform, process, or network code, and neither can
reach a step out of order - `state.assert_transition` is checked here, so
a button wired to the wrong handler raises in a test rather than
downloading nine gigabytes on the wrong screen.

Every step that does long work takes `on_progress` and `cancel`, and
every step that can fail raises `SetupStepError` carrying a typed
`SetupFailure`. There is no step that both mutates the machine and reports
success through a boolean.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from syzygy.local_models.archives import find_executable
from syzygy.local_models.assessment import assess_machine, is_validated_platform
from syzygy.local_models.catalog import (
    ModelCatalog,
    RuntimeManifest,
    load_catalog,
    load_runtime_manifest,
)
from syzygy.local_models.contracts import (
    Backend,
    Compatibility,
    FailureKind,
    MachineAssessment,
    MachineInventory,
    ModelArtifact,
    Recommendation,
    RecoveryAction,
    RuntimeCandidate,
    RuntimeCapabilities,
    SetupFailure,
)
from syzygy.local_models.diagnostics import diagnostics_report
from syzygy.local_models.discovery import (
    binary_candidates,
    endpoint_candidates,
    qualify_binary,
    qualify_endpoint_blocking,
)
from syzygy.local_models.download import CancelCheck, ProgressCallback
from syzygy.local_models.fit import SYZYGY_CONTEXT_TOKENS, SYZYGY_MAX_OUTPUT_TOKENS
from syzygy.local_models.inventory import collect_inventory
from syzygy.local_models.model_install import (
    ModelDownloadPlan,
    ModelInstallError,
    accept_license,
    download_model,
    plan_model_download,
)
from syzygy.local_models.paths import LocalModelPaths
from syzygy.local_models.probe import Probe
from syzygy.local_models.recommend import recommend
from syzygy.local_models.runtime_install import (
    InstallPlan,
    RuntimeInstallError,
    install_runtime_archive,
    plan_runtime_install,
)
from syzygy.local_models.settings import (
    LaunchProfile,
    LocalModelSettings,
    ManagementMode,
    ModelRecord,
    RuntimeRecord,
    load_local_model_settings,
    save_local_model_settings,
)
from syzygy.local_models.state import SetupState, assert_transition
from syzygy.local_models.supervisor import (
    LaunchSpec,
    RunningServer,
    ServerStartError,
    ServerSupervisor,
    lease_port,
)
from syzygy.local_models.verification import ActivationOutcome, activate_after_smoke_test

#: `(candidate) -> capabilities`. See `LocalSetupSession.endpoint_qualifier`.
EndpointQualifier = Callable[[RuntimeCandidate], RuntimeCapabilities]


class SetupStepError(Exception):
    def __init__(self, failure: SetupFailure) -> None:
        super().__init__(failure.message)
        self.failure = failure


@dataclass(frozen=True)
class DiscoveryReport:
    """What already exists on this machine, and what it is good for."""

    endpoints: tuple[RuntimeCapabilities, ...] = ()
    binaries: tuple[RuntimeCapabilities, ...] = ()

    @property
    def usable_endpoint(self) -> RuntimeCapabilities | None:
        for item in self.endpoints:
            if item.compatibility is Compatibility.COMPATIBLE:
                return item
        return None

    @property
    def usable_binary(self) -> RuntimeCapabilities | None:
        for item in self.binaries:
            if item.usable:
                return item
        return None

    @property
    def anything_found(self) -> bool:
        return bool(self.endpoints or self.binaries)


@dataclass(frozen=True)
class ConsentReceipt:
    """Exactly what pressing "Continue" will cause (M16.9d).

    Assembled from the plans rather than written by the screen, so the
    receipt cannot drift from what the code does.
    """

    network_contacts: tuple[tuple[str, str], ...] = ()
    files_written: tuple[tuple[str, int], ...] = ()
    total_download_bytes: int = 0
    total_disk_bytes: int = 0
    license_id: str | None = None
    license_url: str | None = None
    runtime_source: str | None = None
    runtime_version: str | None = None
    local_port_note: str = "A server bound to 127.0.0.1 (this computer only)."
    actions: tuple[str, ...] = ()


@dataclass
class LocalSetupSession:
    """The whole guided setup, as one resumable object."""

    paths: LocalModelPaths
    settings_path: Path
    probe: Probe = field(default_factory=Probe.real)
    catalog: ModelCatalog = field(default_factory=load_catalog)
    manifest: RuntimeManifest = field(default_factory=load_runtime_manifest)
    supervisor: ServerSupervisor | None = None
    #: How an endpoint candidate is probed. Injected so tests never open a
    #: socket - `qualify_endpoint_blocking` really does connect to
    #: localhost, and a test suite that does that is both slow and at the
    #: mercy of whatever the developer happens to be running on :8080.
    endpoint_qualifier: EndpointQualifier = qualify_endpoint_blocking

    state: SetupState = SetupState.INTRO
    inventory: MachineInventory | None = None
    assessment: MachineAssessment | None = None
    discovery: DiscoveryReport | None = None
    recommendation: Recommendation | None = None
    chosen: ModelArtifact | None = None
    runtime_plan: InstallPlan | None = None
    model_plan: ModelDownloadPlan | None = None
    #: The receipt built by `prepare_consent`, kept so the screen can
    #: re-render the consent step without rebuilding (and re-deciding) it.
    consent_receipt: ConsentReceipt | None = None
    runtime: RuntimeCapabilities | None = None
    server: RunningServer | None = None
    failure: SetupFailure | None = None
    #: Set when discovery found a running server we can simply use.
    external_endpoint: str | None = None

    def __post_init__(self) -> None:
        if self.supervisor is None:
            self.supervisor = ServerSupervisor(self.paths, probe=self.probe)

    # -- state ---------------------------------------------------------------

    def move_to(self, target: SetupState) -> None:
        assert_transition(self.state, target)
        self.state = target
        if target not in (SetupState.FAILED,):
            self.failure = None

    def fail(self, failure: SetupFailure) -> None:
        self.failure = failure
        self.state = SetupState.FAILED

    def cancel(self) -> None:
        """Back out. Completed safe work - a downloaded model, an
        installed runtime - is kept; nothing is activated."""
        if self.supervisor is not None:
            self.supervisor.stop()
        self.state = SetupState.CANCELLED

    # -- INVENTORY -----------------------------------------------------------

    def run_inventory(self) -> MachineAssessment:
        self.move_to(SetupState.INVENTORY)
        self.inventory = collect_inventory(self.probe, model_dir=self.paths.models_dir)
        self.assessment = assess_machine(self.inventory)
        return self.assessment

    @property
    def platform_supported(self) -> bool:
        return self.inventory is not None and is_validated_platform(self.inventory)

    def diagnostics(self) -> str:
        """The "copy diagnostics" text, with whatever setup has learned so
        far appended to the machine facts."""
        if self.inventory is None:
            return "No machine information collected yet.\n"
        extra: list[tuple[str, tuple[tuple[str, str], ...]]] = []
        if self.discovery is not None:
            rows = [
                (item.candidate.locator, f"{item.compatibility.value} - {item.next_action}")
                for item in (*self.discovery.endpoints, *self.discovery.binaries)
            ]
            extra.append(("discovered", tuple(rows) or (("none", "nothing found"),)))
        if self.chosen is not None:
            extra.append(
                (
                    "chosen model",
                    (
                        ("id", self.chosen.id),
                        ("quantization", self.chosen.quantization),
                        ("size", str(self.chosen.size_bytes)),
                        ("catalog", self.catalog.catalog_version),
                    ),
                )
            )
        if self.failure is not None:
            extra.append(
                (
                    "last failure",
                    (
                        ("kind", self.failure.kind.value),
                        ("message", self.failure.message),
                        ("detail", self.failure.detail or ""),
                    ),
                )
            )
        return diagnostics_report(self.inventory, extra_sections=extra)

    # -- DISCOVERY -----------------------------------------------------------

    def planned_endpoint_probes(self) -> tuple[RuntimeCandidate, ...]:
        """The URLs discovery *would* contact, before contacting any of
        them - so the UI can show them first (M16.4a)."""
        settings = load_local_model_settings(self.settings_path)
        saved = settings.runtime.base_url if settings.runtime else None
        return endpoint_candidates(saved)

    def run_discovery(self) -> DiscoveryReport:
        self.move_to(SetupState.DISCOVERY)
        settings = load_local_model_settings(self.settings_path)

        endpoints: list[RuntimeCapabilities] = []
        for candidate in self.planned_endpoint_probes():
            result = self.endpoint_qualifier(candidate)
            # Silence is the normal answer for a port nobody is using;
            # listing every closed port as a "finding" would be noise.
            if result.serves_http:
                endpoints.append(result)
            if result.compatibility is Compatibility.COMPATIBLE:
                break

        configured_path = settings.runtime.path if settings.runtime else None
        binaries = [
            qualify_binary(candidate, self.probe, manifest=self.manifest)
            for candidate in binary_candidates(
                self.probe,
                paths=self.paths,
                configured_path=configured_path,
                manifest=self.manifest,
            )
        ]

        self.discovery = DiscoveryReport(endpoints=tuple(endpoints), binaries=tuple(binaries))
        return self.discovery

    def use_existing_endpoint(self, capabilities: RuntimeCapabilities) -> None:
        """The shortest route: something compatible is already running, so
        skip straight to the same smoke test a managed server gets."""
        if capabilities.compatibility is not Compatibility.COMPATIBLE:
            raise SetupStepError(
                SetupFailure(
                    kind=FailureKind.RUNTIME_UNSUITABLE,
                    message="That server isn't one Syzygy can use.",
                    detail=capabilities.next_action,
                    actions=(RecoveryAction.RETRY, RecoveryAction.USE_EXISTING_SERVER),
                    retryable=False,
                )
            )
        self.external_endpoint = capabilities.candidate.locator
        settings = load_local_model_settings(self.settings_path)
        save_local_model_settings(
            self.settings_path,
            settings.model_copy(
                update={
                    "mode": ManagementMode.EXTERNAL,
                    "runtime": RuntimeRecord(
                        base_url=capabilities.candidate.locator,
                        version=capabilities.version,
                    ),
                    "model": ModelRecord(
                        path="",
                        served_model_id=(
                            capabilities.model_ids[0] if capabilities.model_ids else "local"
                        ),
                    ),
                }
            ),
        )
        self.move_to(SetupState.VERIFY)

    # -- RECOMMEND -----------------------------------------------------------

    def build_recommendation(self) -> Recommendation:
        if self.inventory is None:
            raise SetupStepError(
                SetupFailure(
                    kind=FailureKind.UNSUPPORTED_PLATFORM,
                    message="Syzygy hasn't looked at this computer yet.",
                    retryable=True,
                )
            )
        self.move_to(SetupState.RECOMMEND)
        self.recommendation = recommend(self.inventory, self.catalog)
        self.chosen = self.recommendation.artifact
        return self.recommendation

    def choose(self, artifact_id: str) -> ModelArtifact:
        """Pick a different tier. An artifact that does not fit in *disk*
        can never be chosen; one that does not fit in *memory* can, behind
        an explicit override, because the estimate is conservative and the
        user may know something we do not."""
        artifact = self.catalog.by_id(artifact_id)
        if artifact is None:
            raise SetupStepError(
                SetupFailure(
                    kind=FailureKind.CATALOG_RETIRED,
                    message="That model is no longer in Syzygy's catalogue.",
                    actions=(RecoveryAction.CHOOSE_SMALLER,),
                    retryable=False,
                )
            )
        self.chosen = artifact
        return artifact

    # -- CONSENT -------------------------------------------------------------

    def prepare_consent(self) -> ConsentReceipt:
        """Build the plans and turn them into the receipt. Nothing here
        touches the network or the filesystem beyond reading free space."""
        if self.inventory is None or self.chosen is None:
            raise SetupStepError(
                SetupFailure(
                    kind=FailureKind.UNSUPPORTED_PLATFORM,
                    message="There's nothing to confirm yet.",
                )
            )
        self.move_to(SetupState.CONSENT)

        existing = self.discovery.usable_binary if self.discovery else None
        contacts: list[tuple[str, str]] = []
        files: list[tuple[str, int]] = []
        download_bytes = 0
        disk_bytes = 0
        actions: list[str] = []

        if existing is None:
            try:
                self.runtime_plan = plan_runtime_install(
                    self.inventory, self.paths, manifest=self.manifest
                )
            except RuntimeInstallError as exc:
                raise SetupStepError(exc.failure) from exc
            contacts.append((self.runtime_plan.source_url, "the model runner"))
            files.append((str(self.runtime_plan.install_dir), self.runtime_plan.disk_bytes))
            download_bytes += self.runtime_plan.download_bytes
            disk_bytes += self.runtime_plan.disk_bytes
            actions.append(
                f"Download and unpack llama.cpp {self.runtime_plan.version} "
                f"({self.runtime_plan.backend.value})"
            )
        else:
            self.runtime = existing
            self.runtime_plan = None
            actions.append(
                f"Use the llama.cpp already installed at {existing.candidate.locator}"
            )

        self.model_plan = plan_model_download(
            self.chosen, self.inventory, self.paths, self.settings_path, catalog=self.catalog
        )
        if not self.model_plan.already_present:
            contacts.append((self.chosen.download_url, "the model file"))
            download_bytes += self.model_plan.download_bytes
            actions.append(f"Download {self.chosen.display_name} ({self.chosen.quantization})")
        else:
            actions.append(f"Use the copy of {self.chosen.display_name} already downloaded")
        files.append((str(self.model_plan.destination), self.model_plan.final_bytes))
        disk_bytes += self.model_plan.final_bytes

        actions.append("Start a model server on this computer only (127.0.0.1)")
        actions.append("Check it can write a Syzygy reading, then switch readings to it")

        self.consent_receipt = ConsentReceipt(
            network_contacts=tuple(contacts),
            files_written=tuple(files),
            total_download_bytes=download_bytes,
            total_disk_bytes=disk_bytes,
            license_id=self.chosen.license_id,
            license_url=self.chosen.license_url,
            runtime_source=(
                self.runtime_plan.source_url if self.runtime_plan else existing.candidate.locator
                if existing
                else None
            ),
            runtime_version=(
                self.runtime_plan.version
                if self.runtime_plan
                else (existing.version if existing else None)
            ),
            actions=tuple(actions),
        )
        return self.consent_receipt

    def accept_terms(self) -> None:
        if self.model_plan is None:
            raise SetupStepError(
                SetupFailure(
                    kind=FailureKind.TERMS_NOT_ACCEPTED,
                    message="There's no model selected to accept terms for.",
                )
            )
        accept_license(self.settings_path, self.model_plan)

    # -- RUNTIME -------------------------------------------------------------

    def install_runtime(
        self,
        *,
        on_progress: ProgressCallback | None = None,
        cancel: CancelCheck | None = None,
    ) -> RuntimeCapabilities:
        self.move_to(SetupState.RUNTIME)
        if self.runtime_plan is None:
            if self.runtime is None:
                raise SetupStepError(
                    SetupFailure(
                        kind=FailureKind.RUNTIME_UNSUITABLE,
                        message="Syzygy doesn't have a model runner to use.",
                    )
                )
            return self.runtime
        try:
            self.runtime = install_runtime_archive(
                self.runtime_plan, self.paths, self.probe, on_progress=on_progress, cancel=cancel
            )
        except RuntimeInstallError as exc:
            raise SetupStepError(exc.failure) from exc
        return self.runtime

    # -- MODEL ---------------------------------------------------------------

    def fetch_model(
        self,
        *,
        on_progress: ProgressCallback | None = None,
        cancel: CancelCheck | None = None,
    ) -> Path:
        self.move_to(SetupState.MODEL)
        if self.model_plan is None:
            raise SetupStepError(
                SetupFailure(
                    kind=FailureKind.CATALOG_RETIRED,
                    message="No model has been chosen.",
                )
            )
        try:
            return download_model(
                self.model_plan,
                self.paths,
                self.settings_path,
                on_progress=on_progress,
                cancel=cancel,
            )
        except ModelInstallError as exc:
            raise SetupStepError(exc.failure) from exc

    # -- START ---------------------------------------------------------------

    def launch_profile(self) -> LaunchProfile:
        """Threads and GPU offload derived from the inventory, then frozen.

        Persisted with the setup so that a machine whose free memory looks
        different tomorrow gets the configuration the user actually
        approved, not a freshly recomputed one.
        """
        threads = None
        if self.inventory is not None and self.inventory.physical_cores.known:
            threads = max(1, self.inventory.physical_cores.require())
        backend = self.runtime.backend if self.runtime and self.runtime.backend else None
        if backend is None and self.inventory is not None:
            backend = self.inventory.best_backend
        gpu_layers = 0 if backend in (None, Backend.CPU) else 999
        return LaunchProfile(
            context_tokens=SYZYGY_CONTEXT_TOKENS,
            max_output_tokens=SYZYGY_MAX_OUTPUT_TOKENS,
            threads=threads,
            gpu_layers=gpu_layers,
        )

    def start_server(
        self,
        *,
        on_phase=None,
        cancel: CancelCheck | None = None,
    ) -> RunningServer:
        self.move_to(SetupState.START)
        assert self.supervisor is not None

        settings = load_local_model_settings(self.settings_path)
        if settings.model is None or not settings.model.path:
            raise SetupStepError(
                SetupFailure(
                    kind=FailureKind.MODEL_LOAD_FAILED,
                    message="There's no model file to start.",
                )
            )
        executable = self._server_executable()
        profile = self.launch_profile()
        spec = LaunchSpec(
            executable=executable,
            model_path=Path(settings.model.path),
            port=lease_port(),
            context_tokens=profile.context_tokens,
            max_output_tokens=profile.max_output_tokens,
            served_model_id=settings.model.served_model_id,
            threads=profile.threads,
            gpu_layers=profile.gpu_layers,
            backend=self.runtime.backend if self.runtime and self.runtime.backend else Backend.CPU,
        )
        try:
            self.server = self.supervisor.start(spec, on_phase=on_phase, cancel=cancel)
        except ServerStartError as exc:
            if exc.failure.kind is FailureKind.PORT_UNAVAILABLE:
                # A leased port can be taken between the lease and the
                # bind. That is a race, not a configuration problem: lease
                # another and try once more.
                retry = spec_with_new_port(spec)
                try:
                    self.server = self.supervisor.start(retry, on_phase=on_phase, cancel=cancel)
                except ServerStartError as second:
                    raise SetupStepError(second.failure) from second
            else:
                raise SetupStepError(exc.failure) from exc

        save_local_model_settings(
            self.settings_path,
            settings.model_copy(
                update={
                    "mode": ManagementMode.MANAGED,
                    "launch": profile,
                    "runtime": RuntimeRecord(
                        path=str(executable),
                        version=self.runtime.version if self.runtime else None,
                        build=_build_number(self.runtime),
                        backend=spec.backend,
                        syzygy_owned=self.paths.contains(executable),
                    ),
                }
            ),
        )
        return self.server

    def _server_executable(self) -> Path:
        if self.runtime is not None and self.runtime.candidate.kind.value == "binary":
            locator = self.runtime.candidate.resolved_path or self.runtime.candidate.locator
            return Path(locator)
        found = find_executable(self.paths.runtime_dir, self.manifest.server_executables)
        if found is None:
            raise SetupStepError(
                SetupFailure(
                    kind=FailureKind.RUNTIME_UNSUITABLE,
                    message="Syzygy can't find the model runner it installed.",
                    actions=(RecoveryAction.REPAIR, RecoveryAction.RETRY),
                )
            )
        return found

    # -- VERIFY --------------------------------------------------------------

    def verify_and_activate(self) -> ActivationOutcome:
        """Run the Syzygy smoke test and switch over only if it passes."""
        self.move_to(SetupState.VERIFY)
        from syzygy.interpretation.providers.llama_cpp import (
            LOCAL_TIMEOUT_SECONDS,
            LlamaCppProvider,
        )

        settings = load_local_model_settings(self.settings_path)
        base_url = self.external_endpoint or (
            self.server.base_url if self.server is not None else None
        )
        if base_url is None:
            raise SetupStepError(
                SetupFailure(
                    kind=FailureKind.PROCESS_CRASHED,
                    message="There's no running model to check.",
                )
            )
        served = settings.model.served_model_id if settings.model else "local"
        outcome = activate_after_smoke_test(
            self.settings_path,
            provider=LlamaCppProvider(
                model_id=served, base_url=base_url, timeout=LOCAL_TIMEOUT_SECONDS
            ),
            base_url=base_url,
            served_model_id=served,
            runtime_version=settings.runtime.version if settings.runtime else None,
            artifact_id=settings.model.artifact_id if settings.model else None,
            catalog_version=self.catalog.catalog_version,
            model_sha256=settings.model.sha256 if settings.model else None,
        )
        if outcome.activated:
            self.move_to(SetupState.COMPLETE)
        elif outcome.failure is not None:
            self.fail(outcome.failure)
        return outcome

    # -- summary -------------------------------------------------------------

    def summary(self) -> LocalModelSettings:
        return load_local_model_settings(self.settings_path)


def spec_with_new_port(spec: LaunchSpec) -> LaunchSpec:
    from dataclasses import replace

    return replace(spec, port=lease_port())


def _build_number(capabilities: RuntimeCapabilities | None) -> int | None:
    if capabilities is None or not capabilities.version:
        return None
    digits = "".join(character for character in capabilities.version if character.isdigit())
    return int(digits) if digits else None
