"""Machine inventory against captured fixtures only (M16.2e).

Every case here is a *parser* test. None of them touches real hardware,
and the fixtures deliberately include the awkward states - a missing
vendor tool, a hung one, a localized error, a container, WSL, two GPUs -
because those are the ones a naive implementation gets wrong by returning
a confident zero.
"""

from __future__ import annotations

from pathlib import Path

from syzygy.local_models.contracts import Backend, GpuVendor, Provenance
from syzygy.local_models.inventory import collect_inventory
from syzygy.local_models.probe import CommandResult

from .machines import (
    GIB,
    linux_cpu_probe,
    linux_nvidia_probe,
    macos_arm_probe,
    macos_intel_probe,
    make_probe,
    meminfo,
    ok,
    windows_probe,
)


def test_linux_cpu_machine_is_fully_detected() -> None:
    inventory = collect_inventory(linux_cpu_probe(), model_dir=Path("/tmp"))

    assert inventory.os_name.value == "Linux"
    assert inventory.total_ram_bytes.value == 16 * GIB
    assert inventory.total_ram_bytes.provenance is Provenance.DETECTED
    assert inventory.available_ram_bytes.value == 9 * 1024 * 1024 * 1024
    assert inventory.physical_cores.value == 2  # two distinct (physical id, core id) pairs
    assert inventory.logical_cores.value == 8
    assert set(inventory.instruction_sets.value or ()) == {"avx", "avx2", "f16c", "fma"}
    assert inventory.gpus == ()
    assert inventory.best_backend is Backend.CPU
    assert inventory.is_wsl.value is False
    assert inventory.is_container.value is False


def test_nvidia_vram_comes_from_nvidia_smi_in_bytes() -> None:
    inventory = collect_inventory(linux_nvidia_probe())

    assert len(inventory.gpus) == 1
    gpu = inventory.gpus[0]
    assert gpu.vendor is GpuVendor.NVIDIA
    # 24564 MiB, reported by `--format=csv,nounits`.
    assert gpu.vram_bytes.value == 24564 * 1024 * 1024
    assert gpu.vram_bytes.provenance is Provenance.DETECTED
    assert gpu.driver_version.value == "550.54.14"
    assert Backend.CUDA in gpu.backends
    assert inventory.best_backend is Backend.CUDA


def test_missing_nvidia_smi_is_not_an_error_and_not_a_gpu() -> None:
    inventory = collect_inventory(linux_cpu_probe(which={}))

    assert inventory.gpus == ()
    assert inventory.warnings == ()


def test_hung_vendor_tool_becomes_a_warning_not_a_hang() -> None:
    probe = linux_nvidia_probe(
        commands={("nvidia-smi",): CommandResult(argv=("nvidia-smi",), timed_out=True)}
    )
    inventory = collect_inventory(probe)

    assert inventory.gpus == ()
    assert any("timed out" in warning for warning in inventory.warnings)


def test_localized_tool_output_yields_unknown_rather_than_a_wrong_number() -> None:
    # A German `sysctl` failing prints no digits at all; the parser must
    # not invent a size from a message it cannot read.
    probe = macos_arm_probe(
        commands={
            ("sysctl", "-n", "hw.memsize"): CommandResult(
                argv=("sysctl",), returncode=1, stderr="sysctl: unbekannter oid 'hw.memsize'"
            )
        },
        sysconf={},
    )
    inventory = collect_inventory(probe)

    assert inventory.total_ram_bytes.value is None
    assert inventory.total_ram_bytes.provenance is Provenance.UNKNOWN


def test_apple_silicon_reports_unified_memory_and_no_vram_figure() -> None:
    inventory = collect_inventory(macos_arm_probe())

    assert inventory.unified_memory.value is True
    assert inventory.total_ram_bytes.value == 32 * GIB
    gpu = inventory.gpus[0]
    assert gpu.vendor is GpuVendor.APPLE
    assert gpu.backends == (Backend.METAL,)
    # Reporting system RAM as VRAM would make every fit estimate wrong.
    assert gpu.vram_bytes.value is None
    assert inventory.best_backend is Backend.METAL


def test_intel_mac_is_cpu_only_and_says_so() -> None:
    inventory = collect_inventory(macos_intel_probe())

    assert inventory.unified_memory.value is False
    assert inventory.best_backend is Backend.CPU
    assert inventory.instruction_sets.value == ("avx2", "f16c", "fma")


def test_windows_adapter_ram_is_never_reported_as_measured() -> None:
    inventory = collect_inventory(windows_probe())

    gpu = inventory.gpus[0]
    # 2 GiB is under the 32-bit cap, so it is usable - but only as an
    # inference, because the field cannot express anything larger.
    assert gpu.vram_bytes.provenance is Provenance.INFERRED
    assert gpu.vram_bytes.value == 2 * GIB


def test_windows_adapter_ram_at_the_32_bit_cap_is_unknown() -> None:
    powershell = ("powershell", "-NoProfile", "-NonInteractive", "-Command")
    probe = windows_probe(
        commands={
            (*powershell, "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"): ok(
                "17179869184\r\n"
            ),
            (
                *powershell,
                "Get-CimInstance Win32_VideoController | "
                "ForEach-Object { $_.Name + '|' + $_.AdapterRAM + '|' + $_.DriverVersion }",
            ): ok("Redacted RTX|4294967295|31.0.0.1\r\n"),
        }
    )
    inventory = collect_inventory(probe)

    assert inventory.gpus[0].vram_bytes.value is None
    assert inventory.gpus[0].vram_bytes.provenance is Provenance.UNKNOWN


def test_wsl_is_detected_from_proc_version() -> None:
    probe = linux_cpu_probe(
        files={
            "/proc/meminfo": meminfo(8 * 1024 * 1024, 4 * 1024 * 1024),
            "/proc/version": "Linux version 5.15.0-microsoft-standard-WSL2",
            "/proc/1/cgroup": "0::/init.scope",
        }
    )
    assert collect_inventory(probe).is_wsl.value is True


def test_wsl_is_detected_from_the_environment_too() -> None:
    probe = linux_cpu_probe(environ={"WSL_DISTRO_NAME": "Ubuntu"})
    assert collect_inventory(probe).is_wsl.value is True


def test_container_is_detected_from_cgroup() -> None:
    probe = linux_cpu_probe(
        files={
            "/proc/meminfo": meminfo(8 * 1024 * 1024, 4 * 1024 * 1024),
            "/proc/version": "Linux version 6.1.0",
            "/proc/1/cgroup": "0::/docker/abcdef",
        }
    )
    assert collect_inventory(probe).is_container.value is True


def test_two_gpus_are_two_records_with_distinct_indexes() -> None:
    probe = linux_nvidia_probe(
        commands={
            ("nvidia-smi",): ok(
                "Redacted GPU A, 8192, 550.54.14\nRedacted GPU B, 16384, 550.54.14\n"
            )
        }
    )
    inventory = collect_inventory(probe)

    assert [gpu.index for gpu in inventory.gpus] == [0, 1]
    assert [gpu.vram_bytes.value for gpu in inventory.gpus] == [
        8192 * 1024 * 1024,
        16384 * 1024 * 1024,
    ]


def test_amd_gpu_comes_from_sysfs_without_any_subprocess() -> None:
    probe = linux_cpu_probe(
        globs={"/sys/class/drm/card*/device/vendor": ["/sys/class/drm/card0/device/vendor"]},
        files={
            "/proc/meminfo": meminfo(32 * 1024 * 1024, 16 * 1024 * 1024),
            "/proc/version": "Linux version 6.1.0",
            "/proc/1/cgroup": "0::/init.scope",
            "/sys/class/drm/card0/device/vendor": "0x1002\n",
            "/sys/class/drm/card0/device/mem_info_vram_total": str(16 * GIB),
            "/sys/class/drm/card0/device/product_name": "Redacted Radeon\n",
        },
        which={"rocminfo": "/opt/rocm/bin/rocminfo"},
    )
    inventory = collect_inventory(probe)

    assert inventory.gpus[0].vendor is GpuVendor.AMD
    assert inventory.gpus[0].vram_bytes.value == 16 * GIB
    assert Backend.ROCM in inventory.gpus[0].backends


def test_unreadable_disk_is_unknown_not_zero() -> None:
    inventory = collect_inventory(linux_cpu_probe(free_disk=None))

    assert inventory.free_disk_bytes.value is None
    assert inventory.free_disk_bytes.provenance is Provenance.UNKNOWN


def test_permission_failure_reading_cpuinfo_falls_back_to_an_inference() -> None:
    probe = make_probe(
        system="Linux",
        files={"/proc/meminfo": meminfo(8 * 1024 * 1024, 4 * 1024 * 1024)},
        cpu_count=16,
    )
    inventory = collect_inventory(probe)

    assert inventory.physical_cores.provenance is Provenance.INFERRED
    assert inventory.physical_cores.value == 8
    assert inventory.instruction_sets.value is None
