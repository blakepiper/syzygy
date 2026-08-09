"""Redaction, and the "copy diagnostics" report (M16.2c).

Everything a user might paste into an issue passes through `redact` first:
the fact table, server logs, subprocess errors, download failures. The
list of things removed is short and specific - home directory, username,
hostname, and anything shaped like a credential - because a report that
redacts so much it is useless gets replaced by a screenshot of the real
one, which helps nobody.

Redaction is applied at the *boundary*, when text is produced, not when it
is displayed: a log line that reaches `LocalModelPaths.logs_dir` is
already redacted, so a user who opens the file by hand gets the same
treatment as one who presses the button.
"""

from __future__ import annotations

import getpass
import os
import re
import socket
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Final

from syzygy.local_models.contracts import (
    Fact,
    MachineInventory,
    Provenance,
)

_REDACTED: Final = "<redacted>"

#: Credential shapes worth catching by pattern rather than by value: a
#: Hugging Face token, an OpenAI-style key, an HTTP bearer header, and a
#: `?token=`/`&api_key=` query parameter.
_CREDENTIAL_PATTERNS: Final = (
    re.compile(r"\bhf_[A-Za-z0-9]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)([?&](?:token|api[_-]?key|access[_-]?token)=)[^&\s]+"),
    re.compile(r"(?i)\b(authorization|x-api-key)\s*[:=]\s*\S+"),
)


def _identity(
    environ: Mapping[str, str] | None = None,
) -> tuple[str | None, str | None, str | None]:
    """`(home, username, hostname)`, any of which may be `None`. Nothing
    here may raise: redaction runs on the failure path, where a broken
    environment is exactly the situation."""
    env = environ if environ is not None else os.environ
    home: str | None
    username: str | None
    hostname: str | None
    try:
        home = str(Path.home())
    except (OSError, RuntimeError):
        home = env.get("HOME") or env.get("USERPROFILE") or None
    try:
        username = getpass.getuser()
    except (OSError, KeyError, ImportError):
        username = env.get("USER") or env.get("USERNAME") or None
    try:
        hostname = socket.gethostname()
    except OSError:
        hostname = None
    return home, username, hostname


def redact(text: str, *, environ: Mapping[str, str] | None = None) -> str:
    """Strip identifying and credential-shaped substrings from `text`.

    Order matters: credentials go first, so a token that happens to
    contain the username is not partially rewritten into something that
    still looks like a token.
    """
    if not text:
        return text
    for pattern in _CREDENTIAL_PATTERNS:
        text = pattern.sub(
            lambda match: (match.group(1) + _REDACTED) if match.groups() else _REDACTED, text
        )

    home, username, hostname = _identity(environ)
    if home and len(home) > 3:
        text = text.replace(home, "~")
        # Windows paths reach us both ways depending on who wrote them.
        text = text.replace(home.replace("\\", "/"), "~")
    if username and len(username) > 2:
        text = re.sub(rf"\b{re.escape(username)}\b", "<user>", text)
    if hostname and len(hostname) > 2:
        text = re.sub(rf"\b{re.escape(hostname)}\b", "<host>", text)
    return text


def redact_argv(argv: Iterable[str]) -> str:
    """A command line, safe to show. Used for the consent receipt's
    "exact command" and for process-start log lines."""
    return redact(" ".join(argv))


# -- the fact table ----------------------------------------------------------


def format_bytes(value: int) -> str:
    """Binary units, one decimal - the same units every model publisher
    quotes file sizes in. Public because the wizard shows the same figures
    the fact table does, and two formatters would disagree."""
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(size) < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TiB"


def _render_fact(fact: Fact[Any], *, as_bytes: bool = False) -> str:
    if fact.provenance is Provenance.UNKNOWN or fact.value is None:
        return f"unknown ({fact.note})" if fact.note else "unknown"
    value = fact.value
    if as_bytes and isinstance(value, int):
        rendered = format_bytes(value)
    elif isinstance(value, tuple):
        rendered = ", ".join(str(item) for item in value) or "none"
    else:
        rendered = str(value)
    if fact.provenance is Provenance.INFERRED:
        return f"{rendered} (inferred: {fact.note})"
    return rendered


def inventory_facts(inventory: MachineInventory) -> tuple[tuple[str, str], ...]:
    """`(label, value)` rows for the expandable fact table. Already
    redacted, and every row says whether the value was measured."""
    rows: list[tuple[str, str]] = [
        ("Operating system", _render_fact(inventory.os_name)),
        ("OS version", _render_fact(inventory.os_version)),
        ("Architecture", _render_fact(inventory.architecture)),
        ("Processor", _render_fact(inventory.cpu_model)),
        ("Physical cores", _render_fact(inventory.physical_cores)),
        ("Logical cores", _render_fact(inventory.logical_cores)),
        ("CPU features", _render_fact(inventory.instruction_sets)),
        ("Installed memory", _render_fact(inventory.total_ram_bytes, as_bytes=True)),
        ("Available memory", _render_fact(inventory.available_ram_bytes, as_bytes=True)),
        ("Unified memory", _render_fact(inventory.unified_memory)),
        ("Free disk", _render_fact(inventory.free_disk_bytes, as_bytes=True)),
        ("Disk measured at", redact(inventory.disk_path or "unknown")),
        ("Running under WSL", _render_fact(inventory.is_wsl)),
        ("Running in a container", _render_fact(inventory.is_container)),
    ]
    if not inventory.gpus:
        rows.append(("Graphics", "none detected"))
    for gpu in inventory.gpus:
        label = f"GPU {gpu.index}"
        rows.append((label, f"{gpu.vendor.value}: {_render_fact(gpu.name)}"))
        rows.append((f"{label} memory", _render_fact(gpu.vram_bytes, as_bytes=True)))
        rows.append((f"{label} driver", _render_fact(gpu.driver_version)))
        rows.append(
            (
                f"{label} acceleration",
                ", ".join(backend.value for backend in gpu.backends) or "none usable",
            )
        )
    for warning in inventory.warnings:
        rows.append(("Note", redact(warning)))
    return tuple((label, redact(value)) for label, value in rows)


def diagnostics_report(
    inventory: MachineInventory,
    *,
    extra_sections: Iterable[tuple[str, Iterable[tuple[str, str]]]] = (),
) -> str:
    """The full text "copy diagnostics" puts on the clipboard.

    Deliberately *not* a machine-readable dump: no environment variables,
    no process list, no file listing, no serial numbers. Everything in it
    is something a maintainer would have to ask for anyway.
    """
    lines = ["SYZYGY LOCAL MODEL DIAGNOSTICS", ""]
    lines.append(f"collected: {inventory.collected_at_utc.isoformat(timespec='seconds')}")
    lines.append("")
    lines.append("[machine]")
    for label, value in inventory_facts(inventory):
        lines.append(f"  {label}: {value}")
    for title, rows in extra_sections:
        lines.append("")
        lines.append(f"[{title}]")
        for label, value in rows:
            lines.append(f"  {label}: {redact(value)}")
    return "\n".join(lines) + "\n"
