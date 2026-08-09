"""Pure value contracts for guided local-model setup (M16.1a).

Pydantic only. No Textual, no provider SDK, no `subprocess`, no `httpx` -
every module that *does* those things produces or consumes the shapes
defined here, so the interesting logic (fit estimation, recommendation,
classification) can be tested without a machine, a network, or a process.

**Provenance is part of every detected fact.** A `Fact[int]` for installed
RAM is not an integer: it is a value plus whether Syzygy *measured* it,
*inferred* it from something else, or could not determine it at all. M16's
product contract requires the UI to show which is which ("Model fit is a
conservative estimate, not a promise"), and the only way to keep that
honest is to make it impossible to write a detector that quietly returns a
made-up number as though it were measured.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Provenance(StrEnum):
    """Where a value in `MachineInventory` came from."""

    #: Read from the OS or a vendor tool. Trustworthy.
    DETECTED = "detected"
    #: Derived from something else that was detected (a GPU's VRAM guessed
    #: from its model name, say). Directionally useful, not a measurement.
    INFERRED = "inferred"
    #: Not determinable here. Never a zero, never a default - `None`.
    UNKNOWN = "unknown"


class Fact(BaseModel, Generic[T]):
    """One detected value plus how it was obtained.

    `value is None` iff `provenance is UNKNOWN`; `note` explains an
    inference or a failure ("nvidia-smi not on PATH") and is what the
    fact table in the UI shows next to the value.
    """

    model_config = ConfigDict(frozen=True)

    value: T | None = None
    provenance: Provenance = Provenance.UNKNOWN
    note: str | None = None

    @property
    def known(self) -> bool:
        return self.value is not None and self.provenance is not Provenance.UNKNOWN

    def require(self) -> T:
        """The value, or raise. For call sites that have already checked
        `known` and want the narrowed type without a second `if`."""
        if self.value is None:
            raise ValueError(f"fact is unknown: {self.note or 'no detail'}")
        return self.value


def detected(value: T, note: str | None = None) -> Fact[T]:
    return Fact[T](value=value, provenance=Provenance.DETECTED, note=note)


def inferred(value: T, note: str) -> Fact[T]:
    """An inference always carries its reasoning - there is no honest way
    to show "inferred" in a fact table without saying from what."""
    return Fact[T](value=value, provenance=Provenance.INFERRED, note=note)


def unknown(note: str) -> Fact[T]:
    return Fact[T](value=None, provenance=Provenance.UNKNOWN, note=note)


# -- machine inventory -------------------------------------------------------


class GpuVendor(StrEnum):
    APPLE = "apple"
    NVIDIA = "nvidia"
    AMD = "amd"
    INTEL = "intel"
    OTHER = "other"


class Backend(StrEnum):
    """A llama.cpp compute backend. `CPU` is always available and is the
    floor, never an error state."""

    CPU = "cpu"
    METAL = "metal"
    CUDA = "cuda"
    ROCM = "rocm"
    VULKAN = "vulkan"
    SYCL = "sycl"


class GpuDevice(BaseModel):
    """One accelerator. Multiple GPUs are multiple records - Syzygy never
    sums VRAM across devices, because llama.cpp does not get one pooled
    allocation out of two cards without configuration Syzygy does not do.
    """

    model_config = ConfigDict(frozen=True)

    index: int
    vendor: GpuVendor
    name: Fact[str] = Field(default_factory=lambda: unknown("no device name reported"))
    #: Dedicated video memory. On unified-memory Macs this stays UNKNOWN
    #: and `MachineInventory.unified_memory` carries the story instead -
    #: reporting system RAM as VRAM would make every fit estimate a lie.
    vram_bytes: Fact[int] = Field(default_factory=lambda: unknown("no VRAM reported"))
    driver_version: Fact[str] = Field(default_factory=lambda: unknown("no driver version"))
    #: Backends this device could plausibly serve, best first.
    backends: tuple[Backend, ...] = ()


class MachineInventory(BaseModel):
    """Everything the fit calculator and the runtime selector are allowed
    to know about this computer. Read-only, local, never transmitted."""

    model_config = ConfigDict(frozen=True)

    collected_at_utc: datetime

    os_name: Fact[str] = Field(default_factory=lambda: unknown("not probed"))
    os_version: Fact[str] = Field(default_factory=lambda: unknown("not probed"))
    architecture: Fact[str] = Field(default_factory=lambda: unknown("not probed"))

    cpu_model: Fact[str] = Field(default_factory=lambda: unknown("not probed"))
    physical_cores: Fact[int] = Field(default_factory=lambda: unknown("not probed"))
    logical_cores: Fact[int] = Field(default_factory=lambda: unknown("not probed"))
    #: Lowercase feature names ("avx2", "avx512f", "neon"). Empty list is a
    #: *detected* absence; UNKNOWN means the CPU flags could not be read.
    instruction_sets: Fact[tuple[str, ...]] = Field(
        default_factory=lambda: unknown("not probed")
    )

    total_ram_bytes: Fact[int] = Field(default_factory=lambda: unknown("not probed"))
    #: Free *right now*. Deliberately separate from `total_ram_bytes`: the
    #: fit calculator budgets against installed RAM minus a reserve, and
    #: uses this only to warn, because a machine with a browser open is
    #: not permanently smaller.
    available_ram_bytes: Fact[int] = Field(default_factory=lambda: unknown("not probed"))

    #: Free space on the volume that would actually hold the model.
    free_disk_bytes: Fact[int] = Field(default_factory=lambda: unknown("not probed"))
    disk_path: str = ""

    #: True on Apple Silicon (and anywhere else CPU and GPU share one
    #: pool): the GPU can address most of `total_ram_bytes`.
    unified_memory: Fact[bool] = Field(default_factory=lambda: unknown("not probed"))

    is_wsl: Fact[bool] = Field(default_factory=lambda: unknown("not probed"))
    is_container: Fact[bool] = Field(default_factory=lambda: unknown("not probed"))

    gpus: tuple[GpuDevice, ...] = ()

    #: Non-fatal collection problems, already redacted, shown under
    #: "technical details" so a partially-known machine explains itself.
    warnings: tuple[str, ...] = ()

    @property
    def best_backend(self) -> Backend:
        """The backend Syzygy would prefer on this machine. `CPU` when
        nothing better is both present and supported."""
        return self.candidate_backends[0]

    @property
    def candidate_backends(self) -> tuple[Backend, ...]:
        """Every backend this machine could use, best first, ending in
        `CPU`.

        More than one matters: a Linux machine with an NVIDIA card prefers
        CUDA, but Syzygy ships no reviewed Linux CUDA archive, and that
        machine's Vulkan driver works perfectly well. Offering only the
        first choice would drop it to the processor for no reason, so
        runtime selection walks this whole list.
        """
        ordered: list[Backend] = []
        for gpu in self.gpus:
            for backend in gpu.backends:
                if backend not in ordered:
                    ordered.append(backend)
        ordered.append(Backend.CPU)
        return tuple(ordered)


class Assessment(StrEnum):
    """The one-line verdict the wizard leads with (M16.2c)."""

    COMFORTABLE = "comfortable"
    POSSIBLE_WITH_TRADE_OFFS = "possible with trade-offs"
    CPU_SLOW = "CPU only, slow"
    MANUAL_SETUP_RECOMMENDED = "manual setup recommended"


class MachineAssessment(BaseModel):
    """Plain-language summary plus the facts behind it."""

    model_config = ConfigDict(frozen=True)

    assessment: Assessment
    headline: str
    detail: str
    #: `(label, value)` rows for the expandable fact table. Already
    #: redacted - this is what "copy diagnostics" writes out.
    facts: tuple[tuple[str, str], ...] = ()


# -- runtime discovery -------------------------------------------------------


class RuntimeKind(StrEnum):
    #: An executable on disk (`llama-server`, or the newer unified `llama`).
    BINARY = "binary"
    #: An already-running OpenAI-compatible HTTP endpoint.
    ENDPOINT = "endpoint"


class RuntimeSource(StrEnum):
    #: Found on `PATH`.
    PATH = "path"
    #: Previously configured by the user (absolute path or saved base URL).
    CONFIGURED = "configured"
    #: Installed by Syzygy into `LocalModelPaths.runtime_dir`.
    MANAGED = "managed"
    #: A conventional localhost port Syzygy tried. Never a LAN scan.
    CONVENTIONAL_PORT = "conventional_port"


class RuntimeCandidate(BaseModel):
    """Something that *might* be a usable local model runner. A candidate
    is never used until `RuntimeCapabilities` says so - a file called
    `llama-server` on `PATH` proves nothing at all."""

    model_config = ConfigDict(frozen=True)

    kind: RuntimeKind
    source: RuntimeSource
    #: For `BINARY`: the path as found. For `ENDPOINT`: the base URL.
    locator: str
    #: Symlinks resolved. Equal to `locator` when there was nothing to
    #: resolve; unset for endpoints.
    resolved_path: str | None = None
    version: Fact[str] = Field(default_factory=lambda: unknown("not probed"))
    #: True when the file lives under `LocalModelPaths.runtime_dir` - the
    #: only case in which Syzygy may ever replace or remove it.
    syzygy_owned: bool = False
    notes: tuple[str, ...] = ()


class Compatibility(StrEnum):
    COMPATIBLE = "compatible"
    #: Works, but older than the catalog entry's declared minimum.
    COMPATIBLE_BUT_OLD = "compatible but old"
    #: Present and identifiable, but cannot serve what Syzygy needs.
    UNSUITABLE = "present but unsuitable"
    #: Could not be classified (hung, unreadable, unrecognized output).
    UNKNOWN = "unknown"


class RuntimeCapabilities(BaseModel):
    """What a candidate actually proved it can do."""

    model_config = ConfigDict(frozen=True)

    candidate: RuntimeCandidate
    compatibility: Compatibility
    #: Imperative, user-facing, and specific: "Update llama.cpp to b4400 or
    #: newer", not "incompatible".
    next_action: str

    serves_http: bool = False
    lists_models: bool = False
    chat_completions: bool = False
    json_schema_response_format: bool = False

    version: str | None = None
    backend: Backend | None = None
    model_ids: tuple[str, ...] = ()
    #: Everything that went wrong, already redacted.
    problems: tuple[str, ...] = ()

    @property
    def usable(self) -> bool:
        return self.compatibility in (
            Compatibility.COMPATIBLE,
            Compatibility.COMPATIBLE_BUT_OLD,
        )


# -- catalog and fit ---------------------------------------------------------


class SupportStatus(StrEnum):
    #: Passed every M16.3c release gate, including the Syzygy-specific
    #: evaluation on representative hardware.
    SUPPORTED = "supported"
    #: Offered, and honestly labelled: the artifact is pinned and its
    #: licence reviewed, and its memory arithmetic is exact, but the
    #: Syzygy-specific quality/latency evaluation (M16.3b) has not been run
    #: against it yet. The wizard says so rather than implying evidence
    #: that does not exist.
    PROVISIONAL = "provisional"
    #: Still selectable, but no longer the recommendation for new setups.
    DEPRECATED = "deprecated"
    #: Withdrawn. Never offered; an installed copy still runs, and the
    #: repair route explains why it is no longer listed.
    RETIRED = "retired"


class ProfileProvenance(StrEnum):
    """How a `MemoryProfile`'s numbers were arrived at.

    The distinction is load-bearing. A KV cache size is *arithmetic* over
    the GGUF header - layers × kv-heads × head dim × context × 2 bytes -
    and is exact. Runtime overhead is not derivable from anything in the
    file; it has to be watched. Recording which is which stops a measured
    figure and an estimated one from being averaged into a single
    confident-looking number.
    """

    #: Observed by running the model (M16.3b's harness).
    MEASURED = "measured"
    #: Computed exactly from the artifact's own GGUF header.
    COMPUTED = "computed"
    #: A documented, conservative rule. Never presented as measurement.
    ESTIMATED = "estimated"


class ModelTier(StrEnum):
    """The three user-facing choices (M16.3d). A tier may be absent when no
    candidate passed the release gates - it is never filled by demoting a
    model that failed."""

    FASTER = "faster"
    RECOMMENDED = "recommended"
    HIGHER_QUALITY = "higher_quality"


class MemoryProfile(BaseModel):
    """Runtime cost for one artifact at Syzygy's pinned context."""

    model_config = ConfigDict(frozen=True)

    context_tokens: int
    #: KV cache at `context_tokens`, in bytes.
    kv_cache_bytes: int
    #: Everything llama.cpp allocates that is neither weights nor KV cache
    #: (compute buffers, graph, its own working set).
    runtime_overhead_bytes: int
    kv_cache_provenance: ProfileProvenance
    runtime_overhead_provenance: ProfileProvenance
    #: Where the numbers came from, in words: "computed from the GGUF
    #: header" or "measured on b10331, macOS arm64".
    source: str


class ModelArtifact(BaseModel):
    """One curated, pinned GGUF file (M16.3a).

    Every field that could change upstream is pinned: `revision` is an
    immutable commit sha, `sha256` is the file digest, `size_bytes` is
    exact. Nothing here tracks "latest" - a new upstream build is a
    reviewed catalog change, never a silent one.
    """

    model_config = ConfigDict(frozen=True)

    #: Stable, catalog-local identity. Persisted in settings, so it must
    #: not encode anything that can move (no "latest", no tier name).
    id: str
    display_name: str
    publisher: str
    repository: str
    #: Immutable upstream revision - a 40-char git sha for Hugging Face.
    revision: str
    filename: str
    download_url: str
    sha256: str
    size_bytes: int

    quantization: str
    parameter_class: str
    license_id: str
    license_url: str
    #: The model card / release page a person can actually read.
    source_url: str

    #: llama.cpp build number below which this artifact is not supported.
    min_runtime_build: int
    #: Chat template requirement, if the artifact needs an explicit one.
    chat_template: str | None = None

    context_tokens: int
    max_output_tokens: int
    memory_profile: MemoryProfile

    tier: ModelTier | None = None
    support_status: SupportStatus = SupportStatus.SUPPORTED
    #: One sentence, plain language, for the recommendation card.
    why: str = ""
    #: Pointer into the committed evaluation results, so a recommendation
    #: is traceable to a measurement rather than to a vibe.
    evidence_id: str | None = None


class FitVerdict(StrEnum):
    #: Fits with room to spare, on the accelerated backend if there is one.
    COMFORTABLE = "comfortable"
    #: Fits, but slowly or with little headroom.
    TIGHT = "tight"
    #: Would not fit in memory. Offered only behind an explicit override.
    INSUFFICIENT_MEMORY = "insufficient memory"
    #: Not enough disk to download and keep it. Never overridable.
    INSUFFICIENT_DISK = "insufficient disk"
    #: Machine facts too incomplete to judge.
    UNKNOWN = "unknown"


class FitEstimate(BaseModel):
    """A conservative upper-bound memory estimate, plus its ingredients.

    Every number is shown to the user; a verdict with no visible arithmetic
    behind it is exactly the "trust me" this milestone is meant to avoid.
    """

    model_config = ConfigDict(frozen=True)

    artifact_id: str
    verdict: FitVerdict
    reason: str

    weights_bytes: int
    kv_cache_bytes: int
    runtime_overhead_bytes: int
    #: Held back for the OS, Syzygy itself, and whatever else is running.
    reserved_bytes: int

    #: Memory Syzygy is willing to spend on this machine.
    memory_budget_bytes: int
    #: Disk needed to download *and* keep the artifact.
    required_disk_bytes: int
    free_disk_bytes: int | None

    backend: Backend
    #: True when the estimate rests on an inferred or missing fact.
    provisional: bool = False

    @property
    def required_memory_bytes(self) -> int:
        return self.weights_bytes + self.kv_cache_bytes + self.runtime_overhead_bytes

    @property
    def safe_default(self) -> bool:
        """May this artifact be offered as a pre-selected default? Only a
        comfortable fit on facts we actually measured."""
        return self.verdict is FitVerdict.COMFORTABLE and not self.provisional


class Recommendation(BaseModel):
    """What the wizard shows on the RECOMMEND step (M16.3e)."""

    model_config = ConfigDict(frozen=True)

    artifact: ModelArtifact | None
    fit: FitEstimate | None
    #: Every other catalog entry, each with its own estimate, including the
    #: ones that are not selectable - they stay visible with a reason.
    alternatives: tuple[tuple[ModelArtifact, FitEstimate], ...] = ()
    #: "high" when nothing was inferred and the machine is well understood.
    confidence: str = "low"
    #: Why this one, in the user's terms.
    rationale: str = ""


# -- failures ----------------------------------------------------------------


class FailureKind(StrEnum):
    """Every distinct failure the wizard knows how to recover from. A
    generic "something went wrong" is not on the list on purpose: M16.6d
    and M16.7c require each of these to have its own remedy."""

    OFFLINE = "offline"
    AUTHENTICATION_REQUIRED = "authentication_required"
    TERMS_NOT_ACCEPTED = "terms_not_accepted"
    INSUFFICIENT_DISK = "insufficient_disk"
    UPSTREAM_CHANGED = "upstream_changed"
    CORRUPT_PARTIAL = "corrupt_partial"
    DIGEST_MISMATCH = "digest_mismatch"
    CATALOG_RETIRED = "catalog_retired"
    UNSUPPORTED_PLATFORM = "unsupported_platform"
    ELEVATION_REFUSED = "elevation_refused"
    PACKAGE_MANAGER_MISSING = "package_manager_missing"
    ARCHIVE_UNSAFE = "archive_unsafe"
    RUNTIME_UNSUITABLE = "runtime_unsuitable"
    MODEL_LOAD_FAILED = "model_load_failed"
    OUT_OF_MEMORY = "out_of_memory"
    BACKEND_FAILED = "backend_failed"
    CHAT_TEMPLATE_FAILED = "chat_template_failed"
    PORT_UNAVAILABLE = "port_unavailable"
    STARTUP_TIMEOUT = "startup_timeout"
    PROCESS_CRASHED = "process_crashed"
    SCHEMA_UNSUPPORTED = "schema_unsupported"
    SMOKE_TEST_FAILED = "smoke_test_failed"
    MODEL_IDENTITY_MISMATCH = "model_identity_mismatch"
    CANCELLED = "cancelled"


class RecoveryAction(StrEnum):
    """Buttons the failure card may offer (M16.9d)."""

    RETRY = "try_again"
    CHOOSE_SMALLER = "choose_smaller"
    USE_EXISTING_SERVER = "use_existing_server"
    COPY_DIAGNOSTICS = "copy_diagnostics"
    SKIP_FOR_NOW = "skip_for_now"
    OPEN_LICENSE = "open_license"
    FREE_DISK_SPACE = "free_disk_space"
    REPAIR = "repair"


class SetupFailure(BaseModel):
    """A typed, recoverable failure. `detail` is already redacted."""

    model_config = ConfigDict(frozen=True)

    kind: FailureKind
    #: One sentence, no jargon, tells the user what happened.
    message: str
    #: Optional expandable technical text (redacted logs, exit codes).
    detail: str | None = None
    actions: tuple[RecoveryAction, ...] = (RecoveryAction.RETRY, RecoveryAction.SKIP_FOR_NOW)
    #: False for a failure that will not become success by pressing the
    #: same button again (an unsupported platform, a retired catalog entry).
    retryable: bool = True
