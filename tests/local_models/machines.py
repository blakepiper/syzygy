"""Captured, redacted machine fixtures (M16.2e).

No test in this package learns anything about the computer running it.
Every OS touchpoint goes through `syzygy.local_models.probe.Probe`, and
these builders construct one from a dictionary - so a macOS fixture yields
identical results on a Linux CI runner, and a maintainer's NVIDIA
workstation cannot make an "is CUDA detected" test pass by accident.

The values are shapes taken from real tool output with the identifying
parts removed: `nvidia-smi`'s CSV, `/proc/meminfo`'s `kB` lines,
`/sys/class/drm`'s vendor ids, PowerShell's `Get-CimInstance` output.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from syzygy.local_models.probe import CommandResult, Probe

GIB = 1024**3


def make_probe(
    *,
    system: str = "Linux",
    release: str = "6.1.0",
    machine: str = "x86_64",
    processor: str = "",
    environ: Mapping[str, str] | None = None,
    files: Mapping[str, str] | None = None,
    globs: Mapping[str, list[str]] | None = None,
    commands: Mapping[tuple[str, ...], CommandResult] | None = None,
    which: Mapping[str, str] | None = None,
    free_disk: int | None = 200 * GIB,
    sysconf: Mapping[str, int] | None = None,
    cpu_count: int | None = 8,
) -> Probe:
    """Build a `Probe` that answers only what the fixture says it does.

    Anything not in `commands` is reported *missing*, not silently empty:
    "the tool isn't there" is the most common real condition and the one
    most likely to be handled wrongly, so it is the default.
    """
    file_map = dict(files or {})
    glob_map = dict(globs or {})
    command_map = dict(commands or {})
    which_map = dict(which or {})
    sysconf_map = dict(sysconf or {})

    def run(argv: Sequence[str], timeout: float) -> CommandResult:
        key = tuple(argv)
        if key in command_map:
            return command_map[key]
        # Match on the executable alone, so a fixture can stub
        # `nvidia-smi` without repeating its argument list.
        for candidate, result in command_map.items():
            if candidate and candidate[0] == key[0] and len(candidate) == 1:
                return result
        return CommandResult(argv=key, missing=True)

    return Probe(
        system=system,
        release=release,
        version=release,
        machine=machine,
        processor=processor,
        environ=dict(environ or {}),
        run=run,
        read_text=lambda path: file_map.get(path),
        glob=lambda pattern: list(glob_map.get(pattern, [])),
        which=lambda name: which_map.get(name),
        disk_usage=(
            (lambda _path: (500 * GIB, 500 * GIB - free_disk, free_disk))
            if free_disk is not None
            else (lambda _path: None)
        ),
        sysconf=lambda name: sysconf_map.get(name),
        cpu_count=lambda: cpu_count,
    )


def ok(stdout: str = "", stderr: str = "", argv: tuple[str, ...] = ("tool",)) -> CommandResult:
    return CommandResult(argv=argv, returncode=0, stdout=stdout, stderr=stderr)


def meminfo(total_kb: int, available_kb: int) -> str:
    return (
        f"MemTotal:       {total_kb} kB\n"
        f"MemFree:        {available_kb // 2} kB\n"
        f"MemAvailable:   {available_kb} kB\n"
        "Buffers:          123456 kB\n"
    )


CPUINFO_TWO_SOCKETS = """processor\t: 0
model name\t: Redacted CPU @ 3.00GHz
physical id\t: 0
core id\t\t: 0
flags\t\t: fpu avx avx2 f16c fma

processor\t: 1
model name\t: Redacted CPU @ 3.00GHz
physical id\t: 0
core id\t\t: 1
flags\t\t: fpu avx avx2 f16c fma

processor\t: 2
model name\t: Redacted CPU @ 3.00GHz
physical id\t: 0
core id\t\t: 0
flags\t\t: fpu avx avx2 f16c fma
"""


# -- ready-made machines -----------------------------------------------------


def linux_cpu_probe(**overrides) -> Probe:
    defaults = dict(
        system="Linux",
        machine="x86_64",
        files={
            "/proc/meminfo": meminfo(16 * 1024 * 1024, 9 * 1024 * 1024),
            "/proc/cpuinfo": CPUINFO_TWO_SOCKETS,
            "/proc/version": "Linux version 6.1.0 (gcc)",
            "/proc/1/cgroup": "0::/init.scope",
        },
        sysconf={"SC_PAGE_SIZE": 4096, "SC_PHYS_PAGES": 4 * 1024 * 1024},
    )
    defaults.update(overrides)
    return make_probe(**defaults)


def linux_nvidia_probe(**overrides) -> Probe:
    defaults = dict(
        which={"nvidia-smi": "/usr/bin/nvidia-smi"},
        commands={
            ("nvidia-smi",): ok("Redacted GPU, 24564, 550.54.14\n"),
        },
    )
    base = dict(
        system="Linux",
        machine="x86_64",
        files={
            "/proc/meminfo": meminfo(32 * 1024 * 1024, 20 * 1024 * 1024),
            "/proc/cpuinfo": CPUINFO_TWO_SOCKETS,
            "/proc/version": "Linux version 6.1.0 (gcc)",
            "/proc/1/cgroup": "0::/init.scope",
        },
        sysconf={"SC_PAGE_SIZE": 4096, "SC_PHYS_PAGES": 8 * 1024 * 1024},
    )
    base.update(defaults)
    base.update(overrides)
    return make_probe(**base)


def macos_arm_probe(**overrides) -> Probe:
    defaults = dict(
        system="Darwin",
        release="24.0.0",
        machine="arm64",
        commands={
            ("sysctl", "-n", "hw.memsize"): ok("34359738368\n"),
            ("sysctl", "-n", "hw.physicalcpu"): ok("10\n"),
            ("sysctl", "-n", "machdep.cpu.brand_string"): ok("Apple M-series\n"),
            ("sysctl", "-n", "hw.model"): ok("MacRedacted\n"),
        },
        cpu_count=10,
    )
    defaults.update(overrides)
    return make_probe(**defaults)


def macos_intel_probe(**overrides) -> Probe:
    defaults = dict(
        system="Darwin",
        release="23.0.0",
        machine="x86_64",
        commands={
            ("sysctl", "-n", "hw.memsize"): ok("17179869184\n"),
            ("sysctl", "-n", "hw.physicalcpu"): ok("4\n"),
            ("sysctl", "-n", "machdep.cpu.brand_string"): ok("Redacted Intel CPU\n"),
            ("sysctl", "-n", "machdep.cpu.features"): ok("FPU AVX2 FMA F16C\n"),
        },
        cpu_count=8,
    )
    defaults.update(overrides)
    return make_probe(**defaults)


def windows_probe(**overrides) -> Probe:
    powershell = ("powershell", "-NoProfile", "-NonInteractive", "-Command")
    defaults = dict(
        system="Windows",
        release="10",
        machine="AMD64",
        environ={"PROCESSOR_IDENTIFIER": "Redacted Family 6 Model 1"},
        commands={
            (*powershell, "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"): ok(
                "17179869184\r\n"
            ),
            (*powershell, "(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory"): ok(
                "8388608\r\n"
            ),
            (
                *powershell,
                "(Get-CimInstance Win32_Processor | "
                "Measure-Object -Property NumberOfCores -Sum).Sum",
            ): ok("6\r\n"),
            (
                *powershell,
                "Get-CimInstance Win32_VideoController | "
                "ForEach-Object { $_.Name + '|' + $_.AdapterRAM + '|' + $_.DriverVersion }",
            ): ok("Redacted Graphics|2147483648|31.0.0.1\r\n"),
        },
        cpu_count=12,
    )
    defaults.update(overrides)
    return make_probe(**defaults)
