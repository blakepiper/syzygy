"""Will this model actually run here? (M16.2d)

Deterministic domain logic: `MachineInventory` in, `FitEstimate` out, no
I/O, no clock, no network. Every number it uses comes from the catalog's
*measured* memory profiles or from a detected machine fact - never from a
parameter count and a rule of thumb, which is how "8B models need 8 GB"
became folklore that is wrong in both directions.

Four things are added up, and all four are shown to the user:

* **weights** - the exact byte size of the GGUF, which we know because the
  catalog pins it;
* **KV cache** at *Syzygy's* context, not the model's advertised maximum.
  A model that can do 128k context is not asked to, and budgeting for a
  context Syzygy will never fill would rule out models that run fine;
* **runtime overhead** - llama.cpp's compute buffers and working set,
  measured per artifact by the M16.3b harness;
* **a reserve** for the OS, Syzygy itself, and whatever else the person
  has open. A laptop that technically fits the model and then swaps is a
  worse outcome than being told to pick the smaller one.

The result is an *upper bound*. `FitEstimate.safe_default` - the gate on
pre-selecting an artifact - additionally requires that no ingredient was
inferred, so a machine we only half-understand never gets a confident
recommendation.
"""

from __future__ import annotations

from syzygy.local_models.contracts import (
    Backend,
    FitEstimate,
    FitVerdict,
    MachineInventory,
    ModelArtifact,
    Provenance,
)

#: The context Syzygy pins for a local server, and the ceiling on one
#: reply. Derived from the real prompt, not from what a model advertises:
#: the daily-reading prompt carries the system prompt, the fixed card, the
#: ranked transits, the natal anchors and the source passages, and the
#: reply is two registers of a few hundred words each. Raising it costs KV
#: cache on every machine, so it is pinned here and passed to
#: `llama-server` explicitly rather than left to the model's default.
#:
#: The prompt is kept under it from the other side, by
#: `reading_service.MAX_SOURCE_PASSAGE_CHARS` - the passage block is the
#: only part of a prompt that varies by thousands of tokens, and the
#: arithmetic tying the two constants together is written out there. The
#: count cap alone was not enough: `llama-server` rejects an over-long
#: request outright, and a reading whose committed context cannot fit
#: fails identically on every retry.
SYZYGY_CONTEXT_TOKENS = 8192
SYZYGY_MAX_OUTPUT_TOKENS = 1536

#: Held back from installed RAM for the OS, the desktop, the browser the
#: user has open, and Syzygy. The larger of the two applies: a 64 GB
#: workstation should not hand 61 GB to llama.cpp, and an 8 GB laptop
#: cannot spare a quarter of itself.
MIN_SYSTEM_RESERVE_BYTES = 3 * 1024**3
SYSTEM_RESERVE_FRACTION = 0.25

#: What fraction of dedicated VRAM llama.cpp can actually use. The rest is
#: the display, the compositor, and the driver's own allocations.
VRAM_USABLE_FRACTION = 0.90

#: A comfortable fit leaves this much of the budget unused. At 1.0 every
#: fit that technically fits would read as comfortable, which is exactly
#: the over-promise M16 forbids.
COMFORTABLE_HEADROOM = 0.80

#: Disk kept free beyond the model itself, so the download does not fill
#: the volume the database and logs live on.
DISK_HEADROOM_BYTES = 2 * 1024**3


def memory_budget(inventory: MachineInventory) -> tuple[int | None, Backend, bool, str]:
    """`(budget_bytes, backend, provisional, explanation)`.

    Three cases, in order:

    1. **Unified memory** (Apple Silicon): the GPU addresses system RAM, so
       there is one budget and Metal gets it.
    2. **A discrete GPU with a VRAM figure we trust**: that card's usable
       memory, on its backend. Never the sum of two cards - llama.cpp does
       not get one pooled allocation across devices without configuration
       Syzygy does not perform.
    3. **Everything else**: system RAM minus the reserve, on the CPU. An
       accelerator whose memory we could not measure is *not* counted; it
       may well help, and the estimate simply does not promise that it
       will.
    """
    total_ram = inventory.total_ram_bytes
    if not total_ram.known:
        return None, Backend.CPU, True, "installed memory could not be determined"

    ram_budget = max(0, total_ram.require() - system_reserve(total_ram.require()))
    ram_provisional = total_ram.provenance is not Provenance.DETECTED

    if inventory.unified_memory.value is True:
        backend = inventory.best_backend
        return (
            ram_budget,
            backend,
            ram_provisional,
            "unified memory: the GPU shares system memory",
        )

    for gpu in inventory.gpus:
        if not gpu.vram_bytes.known or not gpu.backends:
            continue
        vram_budget = int(gpu.vram_bytes.require() * VRAM_USABLE_FRACTION)
        if vram_budget > ram_budget:
            # A card with less usable VRAM than the CPU has spare RAM is
            # not automatically the better placement, so only take the GPU
            # budget when it is genuinely larger.
            return (
                vram_budget,
                gpu.backends[0],
                ram_provisional or gpu.vram_bytes.provenance is not Provenance.DETECTED,
                f"dedicated video memory on GPU {gpu.index}",
            )

    return ram_budget, Backend.CPU, ram_provisional, "system memory, CPU inference"


def system_reserve(total_ram_bytes: int) -> int:
    return max(MIN_SYSTEM_RESERVE_BYTES, int(total_ram_bytes * SYSTEM_RESERVE_FRACTION))


def scaled_kv_cache_bytes(artifact: ModelArtifact, context_tokens: int) -> int:
    """The measured KV cache, scaled to the context Syzygy will actually
    request. Linear in context length, which is exactly how a transformer's
    KV cache grows - this is arithmetic, not an approximation."""
    profile = artifact.memory_profile
    if profile.context_tokens <= 0:
        return profile.kv_cache_bytes
    return int(profile.kv_cache_bytes * (context_tokens / profile.context_tokens))


def estimate_fit(
    artifact: ModelArtifact,
    inventory: MachineInventory,
    *,
    context_tokens: int = SYZYGY_CONTEXT_TOKENS,
) -> FitEstimate:
    budget, backend, provisional, budget_reason = memory_budget(inventory)

    weights = artifact.size_bytes
    kv_cache = scaled_kv_cache_bytes(artifact, context_tokens)
    overhead = artifact.memory_profile.runtime_overhead_bytes
    required_memory = weights + kv_cache + overhead

    total_ram = inventory.total_ram_bytes
    reserved = system_reserve(total_ram.require()) if total_ram.known else 0

    free_disk = inventory.free_disk_bytes.value if inventory.free_disk_bytes.known else None
    required_disk = artifact.size_bytes + DISK_HEADROOM_BYTES

    def build(verdict: FitVerdict, reason: str, *, extra_provisional: bool = False) -> FitEstimate:
        return FitEstimate(
            artifact_id=artifact.id,
            verdict=verdict,
            reason=reason,
            weights_bytes=weights,
            kv_cache_bytes=kv_cache,
            runtime_overhead_bytes=overhead,
            reserved_bytes=reserved,
            memory_budget_bytes=budget or 0,
            required_disk_bytes=required_disk,
            free_disk_bytes=free_disk,
            backend=backend,
            provisional=provisional or extra_provisional,
        )

    # Disk is checked first and is never overridable: a download that
    # cannot finish is not a trade-off the user gets to accept.
    if free_disk is not None and free_disk < required_disk:
        return build(
            FitVerdict.INSUFFICIENT_DISK,
            f"needs {_gib(required_disk)} free, {_gib(free_disk)} available",
        )

    if budget is None:
        return build(
            FitVerdict.UNKNOWN,
            f"cannot judge memory: {budget_reason}",
            extra_provisional=True,
        )

    if required_memory > budget:
        return build(
            FitVerdict.INSUFFICIENT_MEMORY,
            f"needs about {_gib(required_memory)}, {_gib(budget)} available ({budget_reason})",
        )
    if required_memory > budget * COMFORTABLE_HEADROOM:
        return build(
            FitVerdict.TIGHT,
            f"needs about {_gib(required_memory)} of {_gib(budget)} ({budget_reason})",
        )
    return build(
        FitVerdict.COMFORTABLE,
        f"needs about {_gib(required_memory)} of {_gib(budget)} ({budget_reason})",
    )


def _gib(value: int) -> str:
    return f"{value / 1024**3:.1f} GB"
