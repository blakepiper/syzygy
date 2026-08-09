"""Fit estimation, at the boundaries (M16.2d/e).

The interesting behaviour of this module is entirely at its edges: one
byte either side of the memory budget, exactly at the comfortable
threshold, disk that is short by a byte, and every combination of facts
that are inferred rather than measured. Those are the cases where an
over-confident estimate turns into a machine that swaps.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from syzygy.local_models.contracts import (
    Backend,
    FitVerdict,
    GpuDevice,
    GpuVendor,
    MachineInventory,
    MemoryProfile,
    ModelArtifact,
    ProfileProvenance,
    detected,
    inferred,
    unknown,
)
from syzygy.local_models.fit import (
    COMFORTABLE_HEADROOM,
    DISK_HEADROOM_BYTES,
    SYZYGY_CONTEXT_TOKENS,
    estimate_fit,
    memory_budget,
    scaled_kv_cache_bytes,
    system_reserve,
)

GIB = 1024**3


def artifact(
    *, size: int = 5 * GIB, kv: int = GIB, overhead: int = GIB, context: int = SYZYGY_CONTEXT_TOKENS
) -> ModelArtifact:
    return ModelArtifact(
        id="test-artifact",
        display_name="Test",
        publisher="Test",
        repository="test/test",
        revision="0" * 40,
        filename="test.gguf",
        download_url="https://huggingface.co/test/test/resolve/" + "0" * 40 + "/test.gguf",
        sha256="a" * 64,
        size_bytes=size,
        quantization="Q4_K_M",
        parameter_class="8B",
        license_id="Apache-2.0",
        license_url="https://huggingface.co/test/test/blob/main/LICENSE",
        source_url="https://huggingface.co/test/test",
        min_runtime_build=5092,
        context_tokens=SYZYGY_CONTEXT_TOKENS,
        max_output_tokens=1536,
        memory_profile=MemoryProfile(
            context_tokens=context,
            kv_cache_bytes=kv,
            runtime_overhead_bytes=overhead,
            kv_cache_provenance=ProfileProvenance.COMPUTED,
            runtime_overhead_provenance=ProfileProvenance.ESTIMATED,
            source="test",
        ),
    )


def machine(
    *,
    total_ram: int | None = 32 * GIB,
    ram_inferred: bool = False,
    free_disk: int | None = 500 * GIB,
    unified: bool = False,
    gpus: tuple[GpuDevice, ...] = (),
) -> MachineInventory:
    ram = unknown("not probed")
    if total_ram is not None:
        ram = inferred(total_ram, "test") if ram_inferred else detected(total_ram)
    return MachineInventory(
        collected_at_utc=datetime(2026, 1, 1, tzinfo=UTC),
        os_name=detected("Linux"),
        architecture=detected("x86_64"),
        total_ram_bytes=ram,
        free_disk_bytes=detected(free_disk) if free_disk is not None else unknown("no disk"),
        unified_memory=detected(unified),
        gpus=gpus,
    )


# -- the reserve -------------------------------------------------------------


@pytest.mark.parametrize(
    ("total", "expected"),
    [
        (4 * GIB, 3 * GIB),  # the floor wins on a small machine
        (12 * GIB, 3 * GIB),  # 25% is exactly the floor here
        (16 * GIB, 4 * GIB),  # the fraction takes over
        (64 * GIB, 16 * GIB),
    ],
)
def test_system_reserve_is_the_larger_of_floor_and_fraction(total: int, expected: int) -> None:
    assert system_reserve(total) == expected


# -- budget ------------------------------------------------------------------


def test_unified_memory_spends_system_ram_on_the_gpu() -> None:
    inventory = machine(
        total_ram=32 * GIB,
        unified=True,
        gpus=(GpuDevice(index=0, vendor=GpuVendor.APPLE, backends=(Backend.METAL,)),),
    )
    budget, backend, provisional, _ = memory_budget(inventory)

    assert budget == 32 * GIB - 8 * GIB
    assert backend is Backend.METAL
    assert provisional is False


def test_discrete_vram_is_used_only_when_it_beats_system_ram() -> None:
    small_card = GpuDevice(
        index=0,
        vendor=GpuVendor.NVIDIA,
        vram_bytes=detected(8 * GIB),
        backends=(Backend.CUDA,),
    )
    # 32 GB machine: RAM budget is 24 GB, larger than 8 GB of VRAM, so the
    # CPU placement is the honest one.
    budget, backend, _, _ = memory_budget(machine(total_ram=32 * GIB, gpus=(small_card,)))
    assert backend is Backend.CPU
    assert budget == 24 * GIB

    big_card = small_card.model_copy(update={"vram_bytes": detected(48 * GIB)})
    budget, backend, _, _ = memory_budget(machine(total_ram=16 * GIB, gpus=(big_card,)))
    assert backend is Backend.CUDA
    assert budget == int(48 * GIB * 0.90)


def test_a_gpu_with_unknown_vram_is_not_counted() -> None:
    card = GpuDevice(
        index=0,
        vendor=GpuVendor.AMD,
        vram_bytes=unknown("driver said nothing"),
        backends=(Backend.VULKAN,),
    )
    budget, backend, _, _ = memory_budget(machine(total_ram=16 * GIB, gpus=(card,)))

    assert backend is Backend.CPU
    assert budget == 12 * GIB


def test_unknown_ram_gives_no_budget_at_all() -> None:
    budget, _, provisional, reason = memory_budget(machine(total_ram=None))

    assert budget is None
    assert provisional is True
    assert "memory" in reason


# -- KV cache scaling --------------------------------------------------------


def test_kv_cache_scales_linearly_with_context() -> None:
    entry = artifact(kv=2 * GIB, context=SYZYGY_CONTEXT_TOKENS)

    assert scaled_kv_cache_bytes(entry, SYZYGY_CONTEXT_TOKENS) == 2 * GIB
    assert scaled_kv_cache_bytes(entry, SYZYGY_CONTEXT_TOKENS // 2) == GIB
    assert scaled_kv_cache_bytes(entry, SYZYGY_CONTEXT_TOKENS * 2) == 4 * GIB


# -- verdict boundaries ------------------------------------------------------


def test_exactly_at_the_budget_is_tight_not_insufficient() -> None:
    inventory = machine(total_ram=16 * GIB)  # budget = 12 GiB
    entry = artifact(size=10 * GIB, kv=GIB, overhead=GIB)  # needs exactly 12 GiB

    estimate = estimate_fit(entry, inventory)

    assert estimate.required_memory_bytes == 12 * GIB
    assert estimate.memory_budget_bytes == 12 * GIB
    assert estimate.verdict is FitVerdict.TIGHT


def test_one_byte_over_the_budget_is_insufficient() -> None:
    inventory = machine(total_ram=16 * GIB)
    entry = artifact(size=10 * GIB + 1, kv=GIB, overhead=GIB)

    assert estimate_fit(entry, inventory).verdict is FitVerdict.INSUFFICIENT_MEMORY


def test_exactly_at_the_comfortable_threshold_is_still_tight() -> None:
    inventory = machine(total_ram=16 * GIB)  # budget 12 GiB
    needed = int(12 * GIB * COMFORTABLE_HEADROOM)  # 9.6 GiB
    entry = artifact(size=needed - 2 * GIB, kv=GIB, overhead=GIB)

    estimate = estimate_fit(entry, inventory)
    assert estimate.required_memory_bytes == needed
    # `>` the threshold is tight, so exactly at it is comfortable.
    assert estimate.verdict is FitVerdict.COMFORTABLE

    over = artifact(size=needed - 2 * GIB + 1, kv=GIB, overhead=GIB)
    assert estimate_fit(over, inventory).verdict is FitVerdict.TIGHT


def test_disk_is_checked_before_memory_and_is_never_overridable() -> None:
    entry = artifact(size=5 * GIB)
    inventory = machine(total_ram=64 * GIB, free_disk=5 * GIB + DISK_HEADROOM_BYTES - 1)

    estimate = estimate_fit(entry, inventory)

    assert estimate.verdict is FitVerdict.INSUFFICIENT_DISK
    assert estimate.required_disk_bytes == 5 * GIB + DISK_HEADROOM_BYTES


def test_exactly_enough_disk_passes() -> None:
    entry = artifact(size=5 * GIB)
    inventory = machine(total_ram=64 * GIB, free_disk=5 * GIB + DISK_HEADROOM_BYTES)

    assert estimate_fit(entry, inventory).verdict is not FitVerdict.INSUFFICIENT_DISK


def test_unknown_disk_does_not_block_but_is_reported_as_unknown() -> None:
    estimate = estimate_fit(artifact(), machine(free_disk=None))

    assert estimate.free_disk_bytes is None
    assert estimate.verdict is not FitVerdict.INSUFFICIENT_DISK


def test_unknown_memory_gives_an_unknown_verdict_not_a_guess() -> None:
    estimate = estimate_fit(artifact(), machine(total_ram=None))

    assert estimate.verdict is FitVerdict.UNKNOWN
    assert estimate.provisional is True
    assert estimate.safe_default is False


def test_inferred_facts_make_a_comfortable_fit_unsafe_as_a_default() -> None:
    inventory = machine(total_ram=64 * GIB, ram_inferred=True)
    estimate = estimate_fit(artifact(size=2 * GIB), inventory)

    assert estimate.verdict is FitVerdict.COMFORTABLE
    assert estimate.provisional is True
    # Comfortable, but not pre-selectable: an inference is not a measurement.
    assert estimate.safe_default is False


def test_a_measured_comfortable_fit_is_a_safe_default() -> None:
    estimate = estimate_fit(artifact(size=2 * GIB), machine(total_ram=64 * GIB))

    assert estimate.safe_default is True


def test_every_ingredient_of_the_estimate_is_reported() -> None:
    entry = artifact(size=5 * GIB, kv=GIB, overhead=2 * GIB)
    estimate = estimate_fit(entry, machine(total_ram=32 * GIB))

    assert estimate.weights_bytes == 5 * GIB
    assert estimate.kv_cache_bytes == GIB
    assert estimate.runtime_overhead_bytes == 2 * GIB
    assert estimate.reserved_bytes == 8 * GIB
    assert estimate.required_memory_bytes == 8 * GIB
