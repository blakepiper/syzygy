"""Reading this computer, read-only and locally (M16.2a/M16.2b).

Nothing here writes, installs, uploads, or asks for elevation. Every value
is a `Fact`, so "8 GB, measured" and "8 GB, guessed from the GPU's name"
cannot be confused downstream, and a tool that is absent or hung produces
`unknown(...)` with the reason attached rather than a plausible zero.

Detection strategy, in order of preference:

1. **The standard library.** `os.sysconf`, `shutil.disk_usage`,
   `platform`, `/proc`, `/sys`. No subprocess, no timeout to worry about,
   nothing to be missing.
2. **A native OS interface behind a command,** where the standard library
   has nothing: `sysctl` on macOS, `Get-CimInstance` on Windows.
3. **A vendor tool,** only for accelerators: `nvidia-smi`, `rocm-smi`.

Numbers are parsed as numbers, never matched against English words, so a
localized `nvidia-smi` or a German Windows still yields a usable answer or
an honest `unknown` - never a wrong one.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from syzygy.local_models.contracts import (
    Backend,
    Fact,
    GpuDevice,
    GpuVendor,
    MachineInventory,
    detected,
    inferred,
    unknown,
)
from syzygy.local_models.probe import Probe

#: PCI vendor ids, as `/sys/class/drm/card*/device/vendor` reports them.
_PCI_VENDORS = {
    "0x10de": GpuVendor.NVIDIA,
    "0x1002": GpuVendor.AMD,
    "0x1022": GpuVendor.AMD,
    "0x8086": GpuVendor.INTEL,
}

_POWERSHELL = ("powershell", "-NoProfile", "-NonInteractive", "-Command")

#: CPU features llama.cpp actually cares about when picking a build.
_INTERESTING_FLAGS = frozenset(
    {"avx", "avx2", "avx512f", "avx512_vnni", "f16c", "fma", "neon", "asimd", "sve"}
)


def collect_inventory(
    probe: Probe | None = None, *, model_dir: Path | None = None
) -> MachineInventory:
    """The whole read-only sweep.

    `model_dir` is where a model would actually be written - free disk is
    measured on *that* volume, since a home directory and an external
    drive can differ by a factor of ten.
    """
    probe = probe or Probe.real()
    warnings: list[str] = list(probe.notes)

    os_name, os_version = _detect_os(probe)
    total_ram = _detect_total_ram(probe, warnings)
    available_ram = _detect_available_ram(probe)
    free_disk, disk_path = _detect_disk(probe, model_dir)
    gpus = _detect_gpus(probe, warnings)

    unified = _detect_unified_memory(probe)

    return MachineInventory(
        collected_at_utc=datetime.now(UTC),
        os_name=os_name,
        os_version=os_version,
        architecture=detected(probe.machine) if probe.machine else unknown("no machine string"),
        cpu_model=_detect_cpu_model(probe),
        physical_cores=_detect_physical_cores(probe),
        logical_cores=_detect_logical_cores(probe),
        instruction_sets=_detect_instruction_sets(probe),
        total_ram_bytes=total_ram,
        available_ram_bytes=available_ram,
        free_disk_bytes=free_disk,
        disk_path=disk_path,
        unified_memory=unified,
        is_wsl=_detect_wsl(probe),
        is_container=_detect_container(probe),
        gpus=tuple(gpus),
        warnings=tuple(warnings),
    )


# -- operating system --------------------------------------------------------


def _detect_os(probe: Probe) -> tuple[Fact[str], Fact[str]]:
    if not probe.system:
        return unknown("platform.system() empty"), unknown("platform.system() empty")
    version = probe.release or probe.version
    return (
        detected(probe.system),
        detected(version) if version else unknown("no release string"),
    )


def _detect_wsl(probe: Probe) -> Fact[bool]:
    """WSL matters because the Windows host's GPU reaches it only through
    a paravirtualized driver, and free memory inside the VM is not the
    machine's free memory. Getting this wrong makes every other number
    misleading, so it is detected two ways."""
    if not probe.is_linux:
        return detected(False)
    if probe.environ.get("WSL_DISTRO_NAME") or probe.environ.get("WSL_INTEROP"):
        return detected(True)
    version = probe.read_text("/proc/version")
    if version is None:
        return unknown("/proc/version unreadable")
    return detected("microsoft" in version.lower())


def _detect_container(probe: Probe) -> Fact[bool]:
    if not probe.is_linux:
        return detected(False)
    for marker in ("/.dockerenv", "/run/.containerenv"):
        if probe.read_text(marker) is not None:
            return detected(True)
    cgroup = probe.read_text("/proc/1/cgroup")
    if cgroup is None:
        return unknown("/proc/1/cgroup unreadable")
    return detected(any(token in cgroup for token in ("docker", "containerd", "lxc", "kubepods")))


# -- memory ------------------------------------------------------------------


def _detect_total_ram(probe: Probe, warnings: list[str]) -> Fact[int]:
    page_size = probe.sysconf("SC_PAGE_SIZE")
    pages = probe.sysconf("SC_PHYS_PAGES")
    if page_size and pages:
        return detected(page_size * pages)

    if probe.is_darwin:
        result = probe.run(("sysctl", "-n", "hw.memsize"), 5.0)
        value = _first_int(result.stdout) if result.ok else None
        if value:
            return detected(value)
        warnings.append(result.failure_note)

    if probe.is_windows:
        result = probe.run(
            (*_POWERSHELL, "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"), 15.0
        )
        value = _first_int(result.stdout) if result.ok else None
        if value:
            return detected(value)
        warnings.append(result.failure_note)

    meminfo = _meminfo(probe)
    if "MemTotal" in meminfo:
        return detected(meminfo["MemTotal"])
    return unknown("installed memory could not be read")


def _detect_available_ram(probe: Probe) -> Fact[int]:
    """Only reported where the OS gives a genuinely meaningful number.

    Linux's `MemAvailable` is exactly that - the kernel's own estimate of
    what a new allocation could get. macOS's `vm_stat` needs a pile of
    assumptions about compressed and purgeable pages to turn into one, so
    this returns `unknown` there rather than a figure that would make a
    16 GB Mac look like a 2 GB one.
    """
    meminfo = _meminfo(probe)
    if "MemAvailable" in meminfo:
        return detected(meminfo["MemAvailable"])
    if probe.is_windows:
        result = probe.run(
            (*_POWERSHELL, "(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory"), 15.0
        )
        kilobytes = _first_int(result.stdout) if result.ok else None
        if kilobytes:
            return detected(kilobytes * 1024)
        return unknown(result.failure_note)
    if probe.is_darwin:
        return unknown("macOS does not report a directly usable available-memory figure")
    return unknown("no available-memory source")


def _meminfo(probe: Probe) -> dict[str, int]:
    """`/proc/meminfo` as bytes. Empty off Linux."""
    raw = probe.read_text("/proc/meminfo")
    if raw is None:
        return {}
    values: dict[str, int] = {}
    for line in raw.splitlines():
        key, _, rest = line.partition(":")
        amount = _first_int(rest)
        if amount is None:
            continue
        # Every numeric line in /proc/meminfo is kB except a couple of
        # counters we do not read.
        values[key.strip()] = amount * 1024 if "kB" in rest else amount
    return values


def _detect_unified_memory(probe: Probe) -> Fact[bool]:
    if probe.is_darwin:
        return detected(probe.machine.lower().startswith("arm"))
    # Integrated graphics on a PC share system memory too, but not in the
    # way that matters here (llama.cpp cannot address it as VRAM), so this
    # is deliberately Apple-only rather than "has an iGPU".
    return detected(False)


# -- cpu ---------------------------------------------------------------------


def _detect_cpu_model(probe: Probe) -> Fact[str]:
    cpuinfo = probe.read_text("/proc/cpuinfo")
    if cpuinfo:
        for line in cpuinfo.splitlines():
            key, sep, value = line.partition(":")
            if sep and key.strip() in ("model name", "Model", "Hardware"):
                text = value.strip()
                if text:
                    return detected(text)
    if probe.is_darwin:
        result = probe.run(("sysctl", "-n", "machdep.cpu.brand_string"), 5.0)
        if result.ok and result.stdout.strip():
            return detected(result.stdout.strip())
    if probe.is_windows:
        identifier = probe.environ.get("PROCESSOR_IDENTIFIER", "").strip()
        if identifier:
            return detected(identifier)
    if probe.processor:
        return inferred(probe.processor, "from platform.processor()")
    return unknown("no CPU model source")


def _detect_logical_cores(probe: Probe) -> Fact[int]:
    count = probe.cpu_count()
    return detected(count) if count else unknown("os.cpu_count() returned nothing")


def _detect_physical_cores(probe: Probe) -> Fact[int]:
    """Physical cores, because llama.cpp's thread default wants them - on
    a machine with SMT, running one thread per *logical* core measurably
    hurts token throughput."""
    if probe.is_darwin:
        result = probe.run(("sysctl", "-n", "hw.physicalcpu"), 5.0)
        value = _first_int(result.stdout) if result.ok else None
        if value:
            return detected(value)
    cpuinfo = probe.read_text("/proc/cpuinfo")
    if cpuinfo:
        cores = _physical_cores_from_cpuinfo(cpuinfo)
        if cores:
            return detected(cores)
    if probe.is_windows:
        result = probe.run(
            (
                *_POWERSHELL,
                "(Get-CimInstance Win32_Processor | "
                "Measure-Object -Property NumberOfCores -Sum).Sum",
            ),
            15.0,
        )
        value = _first_int(result.stdout) if result.ok else None
        if value:
            return detected(value)
    logical = probe.cpu_count()
    if logical:
        # Deliberately conservative: assuming SMT when we cannot tell
        # under-estimates threads, which is slow. Over-estimating is worse
        # - it oversubscribes and can make generation crawl.
        return inferred(max(1, logical // 2), "assumed SMT: half of the logical core count")
    return unknown("no core-count source")


def _physical_cores_from_cpuinfo(cpuinfo: str) -> int | None:
    """Count distinct `(physical id, core id)` pairs. Absent on ARM and in
    many VMs, hence the `None`."""
    pairs: set[tuple[str, str]] = set()
    physical_id = core_id = None
    for line in cpuinfo.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            if physical_id is not None and core_id is not None:
                pairs.add((physical_id, core_id))
            physical_id = core_id = None
            continue
        name = key.strip()
        if name == "physical id":
            physical_id = value.strip()
        elif name == "core id":
            core_id = value.strip()
    if physical_id is not None and core_id is not None:
        pairs.add((physical_id, core_id))
    return len(pairs) or None


def _detect_instruction_sets(probe: Probe) -> Fact[tuple[str, ...]]:
    cpuinfo = probe.read_text("/proc/cpuinfo")
    if cpuinfo:
        found: set[str] = set()
        for line in cpuinfo.splitlines():
            key, sep, value = line.partition(":")
            if sep and key.strip() in ("flags", "Features"):
                found |= {flag for flag in value.split() if flag in _INTERESTING_FLAGS}
        # An empty set here is a *detected* absence: the file was readable.
        return detected(tuple(sorted(found)))
    if probe.is_darwin and probe.machine.lower().startswith("arm"):
        return inferred(("neon",), "every Apple Silicon core implements NEON")
    if probe.is_darwin:
        result = probe.run(("sysctl", "-n", "machdep.cpu.features"), 5.0)
        if result.ok:
            found = {
                flag.lower() for flag in result.stdout.split() if flag.lower() in _INTERESTING_FLAGS
            }
            return detected(tuple(sorted(found)))
    return unknown("CPU feature flags are not exposed on this platform")


# -- disk --------------------------------------------------------------------


def _detect_disk(probe: Probe, model_dir: Path | None) -> tuple[Fact[int], str]:
    target = model_dir or Path.home()
    usage = probe.disk_usage(target)
    if usage is None:
        return unknown(f"free space on {target} could not be read"), str(target)
    return detected(usage[2]), str(target)


# -- accelerators ------------------------------------------------------------


def _detect_gpus(probe: Probe, warnings: list[str]) -> list[GpuDevice]:
    devices: list[GpuDevice] = []

    if probe.is_darwin:
        devices.extend(_detect_apple_gpus(probe))
        return _reindex(devices)

    nvidia = _detect_nvidia_gpus(probe, warnings)
    devices.extend(nvidia)

    if probe.is_windows:
        devices.extend(_detect_windows_gpus(probe, warnings, skip_nvidia=bool(nvidia)))
    else:
        devices.extend(_detect_drm_gpus(probe, skip_nvidia=bool(nvidia)))

    return _reindex(devices)


def _reindex(devices: list[GpuDevice]) -> list[GpuDevice]:
    return [
        device.model_copy(update={"index": position})
        for position, device in enumerate(devices)
    ]


def _detect_apple_gpus(probe: Probe) -> list[GpuDevice]:
    if not probe.machine.lower().startswith("arm"):
        # Intel Macs have Metal, but llama.cpp's Metal backend targets
        # Apple Silicon; an Intel Mac's honest answer is "CPU".
        return [
            GpuDevice(
                index=0,
                vendor=GpuVendor.OTHER,
                name=unknown("not queried on Intel Macs"),
                backends=(),
            )
        ]
    model = probe.run(("sysctl", "-n", "hw.model"), 5.0)
    name = (
        detected(f"Apple Silicon GPU ({model.stdout.strip()})")
        if model.ok and model.stdout.strip()
        else inferred("Apple Silicon GPU", "from the arm64 architecture")
    )
    return [
        GpuDevice(
            index=0,
            vendor=GpuVendor.APPLE,
            name=name,
            # Unified memory: the GPU addresses system RAM, so a dedicated
            # VRAM figure would be fiction. `MachineInventory.unified_memory`
            # carries this instead, and the fit calculator reads it there.
            vram_bytes=unknown("unified memory - see total RAM"),
            backends=(Backend.METAL,),
        )
    ]


def _detect_nvidia_gpus(probe: Probe, warnings: list[str]) -> list[GpuDevice]:
    if probe.which("nvidia-smi") is None:
        return []
    result = probe.run(
        (
            "nvidia-smi",
            "--query-gpu=name,memory.total,driver_version",
            "--format=csv,noheader,nounits",
        ),
        10.0,
    )
    if not result.ok:
        warnings.append(result.failure_note)
        return []
    devices: list[GpuDevice] = []
    for line in result.stdout.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) < 2 or not fields[0]:
            continue
        megabytes = _first_int(fields[1])
        devices.append(
            GpuDevice(
                index=len(devices),
                vendor=GpuVendor.NVIDIA,
                name=detected(fields[0]),
                vram_bytes=(
                    detected(megabytes * 1024 * 1024)
                    if megabytes
                    else unknown("nvidia-smi reported no memory figure")
                ),
                driver_version=(
                    detected(fields[2])
                    if len(fields) > 2 and fields[2]
                    else unknown("not reported")
                ),
                backends=_nvidia_backends(probe),
            )
        )
    return devices


def _nvidia_backends(probe: Probe) -> tuple[Backend, ...]:
    backends = [Backend.CUDA]
    if probe.which("vulkaninfo") is not None:
        backends.append(Backend.VULKAN)
    return tuple(backends)


def _detect_drm_gpus(probe: Probe, *, skip_nvidia: bool) -> list[GpuDevice]:
    """AMD and Intel on Linux, straight out of `/sys` - no vendor tool, no
    subprocess, no timeout. `mem_info_vram_total` is the amdgpu driver's
    own figure and is exact when present."""
    devices: list[GpuDevice] = []
    for vendor_path in probe.glob("/sys/class/drm/card*/device/vendor"):
        vendor_id = (probe.read_text(vendor_path) or "").strip().lower()
        vendor = _PCI_VENDORS.get(vendor_id)
        if vendor is None or (vendor is GpuVendor.NVIDIA and skip_nvidia):
            continue
        device_dir = vendor_path.rsplit("/vendor", 1)[0]
        vram = _first_int(probe.read_text(f"{device_dir}/mem_info_vram_total") or "")
        name = (probe.read_text(f"{device_dir}/product_name") or "").strip()
        devices.append(
            GpuDevice(
                index=len(devices),
                vendor=vendor,
                name=(
                    detected(name)
                    if name
                    else inferred(vendor.value.upper() + " GPU", "PCI vendor id only")
                ),
                vram_bytes=detected(vram) if vram else unknown("driver reports no VRAM total"),
                backends=_linux_backends(probe, vendor),
            )
        )
    return devices


def _linux_backends(probe: Probe, vendor: GpuVendor) -> tuple[Backend, ...]:
    backends: list[Backend] = []
    if vendor is GpuVendor.NVIDIA:
        backends.append(Backend.CUDA)
    if vendor is GpuVendor.AMD and (
        probe.which("rocminfo") is not None or probe.which("rocm-smi") is not None
    ):
        backends.append(Backend.ROCM)
    if vendor is GpuVendor.INTEL and probe.which("sycl-ls") is not None:
        backends.append(Backend.SYCL)
    if probe.which("vulkaninfo") is not None:
        backends.append(Backend.VULKAN)
    return tuple(backends)


def _detect_windows_gpus(
    probe: Probe, warnings: list[str], *, skip_nvidia: bool
) -> list[GpuDevice]:
    result = probe.run(
        (
            *_POWERSHELL,
            "Get-CimInstance Win32_VideoController | "
            "ForEach-Object { $_.Name + '|' + $_.AdapterRAM + '|' + $_.DriverVersion }",
        ),
        20.0,
    )
    if not result.ok:
        warnings.append(result.failure_note)
        return []
    devices: list[GpuDevice] = []
    for line in result.stdout.splitlines():
        fields = [field.strip() for field in line.split("|")]
        if not fields or not fields[0]:
            continue
        vendor = _vendor_from_name(fields[0])
        if vendor is GpuVendor.NVIDIA and skip_nvidia:
            continue
        raw_bytes = _first_int(fields[1]) if len(fields) > 1 else None
        devices.append(
            GpuDevice(
                index=len(devices),
                vendor=vendor,
                name=detected(fields[0]),
                # `AdapterRAM` is a 32-bit field: anything at or above 4 GiB
                # reports as exactly 4294967295, so a big card looks like a
                # small one. Never `detected`.
                vram_bytes=(
                    inferred(raw_bytes, "Win32_VideoController.AdapterRAM, capped at 4 GiB")
                    if raw_bytes and raw_bytes < 4 * 1024**3 - 1
                    else unknown("Windows reports adapter memory as a 32-bit value")
                ),
                driver_version=(
                    detected(fields[2])
                    if len(fields) > 2 and fields[2]
                    else unknown("not reported")
                ),
                backends=_windows_backends(probe, vendor),
            )
        )
    return devices


def _windows_backends(probe: Probe, vendor: GpuVendor) -> tuple[Backend, ...]:
    backends: list[Backend] = []
    if vendor is GpuVendor.NVIDIA:
        backends.append(Backend.CUDA)
    if probe.which("vulkaninfo") is not None:
        backends.append(Backend.VULKAN)
    return tuple(backends)


def _vendor_from_name(name: str) -> GpuVendor:
    lowered = name.lower()
    if "nvidia" in lowered or "geforce" in lowered or "quadro" in lowered or "rtx" in lowered:
        return GpuVendor.NVIDIA
    if "amd" in lowered or "radeon" in lowered:
        return GpuVendor.AMD
    if "intel" in lowered:
        return GpuVendor.INTEL
    return GpuVendor.OTHER


# -- parsing -----------------------------------------------------------------

_INT_PATTERN = re.compile(r"-?\d+")


def _first_int(text: str) -> int | None:
    """The first integer in `text`, or `None`.

    Locale-proof by construction: it never matches a word, a decimal
    separator, or a unit, so `"16384 MiB"`, `"16384"`, and a German
    `"16384 MiB"` all give the same answer, and a localized error message
    with no digits in it gives `None` rather than a wrong number.
    """
    match = _INT_PATTERN.search(text or "")
    if match is None:
        return None
    value = int(match.group())
    return value if value >= 0 else None
