"""Plain-text renderings of local-model state (M16.10a/b).

Pure functions: state in, lines out. No printing, no `sys.exit`, no
argument parsing - `syzygy.cli` does all of that, and `syzygy doctor` and
`syzygy model local status` share these so they cannot disagree about what
"configured" means.

Everything here is already redacted, because everything here is meant to
be pasteable into a bug report.
"""

from __future__ import annotations

from pathlib import Path

from syzygy.local_models.catalog import load_catalog, load_runtime_manifest
from syzygy.local_models.contracts import MachineInventory
from syzygy.local_models.diagnostics import format_bytes, inventory_facts, redact
from syzygy.local_models.download import verify_digest
from syzygy.local_models.model_install import list_local_models
from syzygy.local_models.paths import LocalModelPaths
from syzygy.local_models.probe import Probe
from syzygy.local_models.runtime_state import load_runtime_state
from syzygy.local_models.settings import load_local_model_settings
from syzygy.local_models.supervisor import verify_recorded_process
from syzygy.local_models.verification import (
    needs_reverification,
    validate_managed_configuration,
)


def machine_lines(inventory: MachineInventory) -> list[str]:
    return [f"{label:24s} {value}" for label, value in inventory_facts(inventory)]


def status_lines(
    settings_path: Path, paths: LocalModelPaths, *, probe: Probe | None = None
) -> list[str]:
    """`syzygy model local status` - read-only, scriptable, never prompts."""
    settings = load_local_model_settings(settings_path)
    catalog = load_catalog()
    manifest = load_runtime_manifest()

    lines = [
        f"catalog        {catalog.catalog_version} ({len(catalog.offerable)} models offered)",
        f"pinned runtime llama.cpp {manifest.release_tag}",
    ]

    if settings.mode is None:
        lines.append("local model    not configured")
        lines.append("")
        lines.append("Set one up with `syzygy model setup-local`, or in the interface")
        lines.append("with [M] → Set up a local model for me. Readings work without one.")
        return lines

    lines.append(f"mode           {settings.mode.value}")

    runtime = settings.runtime
    if runtime is not None and runtime.base_url:
        lines.append(f"server         {redact(runtime.base_url)} (managed by you)")
    elif runtime is not None and runtime.path:
        owned = "Syzygy-installed" if runtime.syzygy_owned else "external"
        version = runtime.version or "unknown version"
        exists = "present" if Path(runtime.path).exists() else "MISSING"
        lines.append(f"runner         {version}, {owned}, {exists}")
        lines.append(f"               {redact(runtime.path)}")
        lines.append(f"backend        {runtime.backend.value}")

    model = settings.model
    if model is not None and model.path:
        exists = "present" if Path(model.path).exists() else "MISSING"
        owned = "Syzygy-downloaded" if model.syzygy_owned else "your own file"
        size = f", {format_bytes(model.size_bytes)}" if model.size_bytes else ""
        lines.append(f"model          {model.artifact_id or 'external file'} ({owned}{size})")
        lines.append(f"               {redact(model.path)} — {exists}")
        lines.append(f"served as      {model.served_model_id}")

    launch = settings.launch
    if launch is not None:
        lines.append(
            f"launch         {launch.context_tokens} context, "
            f"{launch.max_output_tokens} max output, "
            f"{launch.threads or 'auto'} threads, {launch.gpu_layers or 0} GPU layers"
        )

    record = settings.last_verification
    if record is None:
        lines.append("verified       never")
    else:
        stale, why = needs_reverification(
            settings,
            runtime_version=runtime.version if runtime else None,
            catalog_version=catalog.catalog_version,
        )
        state = f"STALE - {why}" if stale else "current"
        lines.append(f"verified       {record.verified_at_utc} ({state})")

    runtime_state = load_runtime_state(paths.state_path)
    if runtime_state.process is None:
        lines.append("server process not running")
    else:
        # The record is not evidence on its own. It outlives an unclean
        # exit, and reporting it as a running server sent the user looking
        # for a process that died days ago (M25.3). Verified here by the
        # same rule that decides whether Syzygy may signal it.
        recorded = runtime_state.process
        verified, reason = verify_recorded_process(recorded, probe or Probe.real())
        where = f"pid {recorded.pid} on 127.0.0.1:{recorded.port}"
        if verified:
            lines.append(f"server process {where}")
        else:
            lines.append(f"server process recorded at {where}, but {reason}")
            lines.append("               `syzygy model local stop` clears the record")
    if runtime_state.downloads:
        for progress in runtime_state.downloads:
            total = format_bytes(progress.total_bytes) if progress.total_bytes else "unknown"
            lines.append(
                f"partial        {progress.key}: "
                f"{format_bytes(progress.downloaded_bytes)} of {total}"
            )
    return lines


def doctor_lines(
    settings_path: Path, paths: LocalModelPaths, *, deep: bool = False
) -> tuple[list[str], bool]:
    """`syzygy model local doctor`, and the local-model part of `syzygy
    doctor`. Returns `(lines, ok)`.

    "Not configured" is not a failure. A missing local model is a
    supported state, so `ok` stays True for it - only a *broken*
    configuration, which the user believes is working, is a problem worth
    a non-zero exit.
    """
    settings = load_local_model_settings(settings_path)
    catalog = load_catalog()
    lines: list[str] = []

    if settings.mode is None:
        return ["local model    not configured (this is fine - readings still work)"], True

    health = validate_managed_configuration(
        settings_path, catalog_version=catalog.catalog_version
    )
    lines.append(
        f"local model    {'OK' if health.healthy else 'NEEDS REPAIR'}: {health.reason}"
    )

    runtime = settings.runtime
    if runtime is not None and runtime.base_url:
        lines.append(f"binding        external server at {redact(runtime.base_url)}")
    elif runtime is not None and runtime.path:
        lines.append("binding        127.0.0.1 only (Syzygy never binds 0.0.0.0)")
        if not Path(runtime.path).exists():
            lines.append(f"runner         MISSING at {redact(runtime.path)}")

    for row in list_local_models(paths, settings_path, deep_verify=deep):
        owner = "managed" if row.syzygy_owned else "external"
        lines.append(
            f"file           {redact(str(row.path))}\n"
            f"               {owner}, {format_bytes(row.size_bytes)}, {row.verification}"
            f"{', in use' if row.in_use else ''}"
        )

    model = settings.model
    if deep and model is not None and model.sha256 and Path(model.path).exists():
        matched = verify_digest(Path(model.path), model.sha256)
        lines.append(f"digest         {'matches the catalogue' if matched else 'DOES NOT MATCH'}")
        if not matched:
            # Digest drift is the one failure the cheap startup check
            # cannot see, and the reason `--deep` exists at all.
            return lines, False

    record = settings.last_verification
    if record is None:
        lines.append("smoke test     never run")
    else:
        lines.append(
            f"smoke test     passed {record.verified_at_utc} "
            f"(runner {record.runtime_version}, prompts {record.prompt_version})"
        )
    return lines, health.healthy


def setup_plan_lines(receipt) -> list[str]:
    """The consent receipt, as text. Identical content to the wizard's -
    both come from `ConsentReceipt`, so the CLI cannot understate what the
    TUI would show."""
    lines = ["Syzygy will:"]
    lines += [f"  {index + 1}. {action}" for index, action in enumerate(receipt.actions)]
    lines.append("")
    lines.append("It will contact:")
    lines += [f"  · {url}  ({why})" for url, why in receipt.network_contacts] or [
        "  · nothing - everything needed is already here"
    ]
    lines.append("")
    lines.append("It will write:")
    lines += [f"  · {redact(path)}  ({format_bytes(size)})" for path, size in receipt.files_written]
    lines.append("")
    lines.append(f"Total download: {format_bytes(receipt.total_download_bytes)}")
    lines.append(f"Disk when finished: {format_bytes(receipt.total_disk_bytes)}")
    lines.append(f"Network exposure: {receipt.local_port_note}")
    if receipt.license_id:
        lines.append(f"Licence: {receipt.license_id} — {receipt.license_url}")
    return lines
