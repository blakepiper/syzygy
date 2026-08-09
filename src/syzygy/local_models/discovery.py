"""Finding - and refusing to trust - what is already on this machine (M16.4).

Two kinds of thing can already exist: a *server* answering HTTP, and a
*binary* on disk. Both are treated the same way: they are candidates until
a capability probe proves otherwise, and neither is ever modified. Syzygy
does not upgrade someone else's llama.cpp, does not restart someone else's
server, and does not write to a path it did not create.

Scope limits, from M16's safety contract, enforced here rather than
remembered:

* **Localhost only.** The saved endpoint (which the user typed) plus a
  short list of conventional local ports. No LAN scan, no port range, no
  mDNS. A non-local saved URL is still probed - the user asked for it -
  but the URL is shown before anything is sent.
* **A name proves nothing.** A file called `llama-server` earns a version
  query and nothing else until its output identifies it as llama.cpp.
* **Everything is bounded.** A hung executable is a timeout with a
  classification, not a wedged wizard.
"""

from __future__ import annotations

import asyncio
import os
import re
import stat
from pathlib import Path

from syzygy.local_models.catalog import RuntimeManifest, load_runtime_manifest
from syzygy.local_models.contracts import (
    Backend,
    Compatibility,
    RuntimeCandidate,
    RuntimeCapabilities,
    RuntimeKind,
    RuntimeSource,
    detected,
    unknown,
)
from syzygy.local_models.diagnostics import redact
from syzygy.local_models.paths import LocalModelPaths
from syzygy.local_models.probe import Probe

#: Local ports worth trying, in order. llama.cpp's own default first, then
#: the defaults of the two other OpenAI-compatible local servers people
#: are most likely to already be running. This list is deliberately short
#: and hard-coded: "scan a range" is exactly what M16.4a forbids.
CONVENTIONAL_PORTS: tuple[tuple[int, str], ...] = (
    (8080, "llama.cpp's default"),
    (8081, "llama.cpp's alternate default"),
    (1234, "LM Studio's default"),
    (11434, "Ollama's default"),
)

#: Both localhost families. A server bound to `::1` is invisible to a
#: probe of `127.0.0.1` and vice versa, and "nothing is running" when
#: something is, is the most confusing possible answer.
LOCALHOST_HOSTS: tuple[str, ...] = ("127.0.0.1", "[::1]")

#: `llama-server --version` writes `version: 10331 (7ba604f1c)` to stderr;
#: the newer unified `llama --version` writes `b10331-7ba604f1c` to
#: stdout. Both are matched, from both streams, because which stream a
#: build uses is not something to depend on.
_VERSION_PATTERNS = (
    re.compile(r"\bversion:\s*(?P<build>\d+)\b"),
    re.compile(r"\bb(?P<build>\d{3,})[-\s]"),
    re.compile(r"^b(?P<build>\d{3,})$", re.MULTILINE),
)

_VERSION_TIMEOUT = 10.0


# -- endpoints ---------------------------------------------------------------


def endpoint_candidates(
    saved_base_url: str | None = None,
    *,
    include_conventional: bool = True,
) -> tuple[RuntimeCandidate, ...]:
    """The URLs Syzygy will try, in order, without contacting any of them.

    Returned before probing on purpose: M16.4a requires the URL to be
    visible before a connection is made to anything non-local, and a list
    the caller can render is the only way to honour that.
    """
    candidates: list[RuntimeCandidate] = []
    seen: set[str] = set()

    if saved_base_url:
        normalized = saved_base_url.rstrip("/")
        seen.add(normalized)
        candidates.append(
            RuntimeCandidate(
                kind=RuntimeKind.ENDPOINT,
                source=RuntimeSource.CONFIGURED,
                locator=normalized,
                notes=("the server you configured previously",),
            )
        )

    if not include_conventional:
        return tuple(candidates)

    for port, why in CONVENTIONAL_PORTS:
        for host in LOCALHOST_HOSTS:
            url = f"http://{host}:{port}/v1"
            if url in seen:
                continue
            seen.add(url)
            candidates.append(
                RuntimeCandidate(
                    kind=RuntimeKind.ENDPOINT,
                    source=RuntimeSource.CONVENTIONAL_PORT,
                    locator=url,
                    notes=(why,),
                )
            )
    return tuple(candidates)


def is_local_url(url: str) -> bool:
    """Does this URL stay on this machine? Used to decide whether the
    wizard must show it and ask first."""
    lowered = url.lower()
    return any(
        f"//{host}" in lowered or f"//{host}:" in lowered
        for host in ("127.0.0.1", "localhost", "[::1]", "::1")
    )


async def qualify_endpoint(
    candidate: RuntimeCandidate,
    *,
    minimum_build: int | None = None,
    timeout: float = 10.0,
    transport: object | None = None,
) -> RuntimeCapabilities:
    """Probe one endpoint and classify what answered.

    Imports the provider's probe rather than reimplementing HTTP: M16.8a
    keeps llama.cpp transport in `interpretation.providers`, and this
    module consumes the typed result.
    """
    from syzygy.interpretation.providers.llama_cpp import probe_capabilities

    result = await probe_capabilities(
        candidate.locator,
        timeout=timeout,
        transport=transport,  # type: ignore[arg-type]
    )

    problems = (redact(result.error),) if result.error else ()

    if not result.reachable:
        return RuntimeCapabilities(
            candidate=candidate,
            compatibility=Compatibility.UNKNOWN,
            next_action=f"Nothing answered at {candidate.locator}.",
            problems=problems,
        )

    if result.requires_authentication:
        return RuntimeCapabilities(
            candidate=candidate,
            compatibility=Compatibility.UNSUITABLE,
            next_action=(
                "A server is running there but wants an API key. Use "
                "Advanced / existing server to supply one, or choose a different port."
            ),
            serves_http=True,
            problems=problems,
        )

    if not result.chat_completions:
        return RuntimeCapabilities(
            candidate=candidate,
            compatibility=Compatibility.UNSUITABLE,
            next_action=(
                "Something is listening there, but it isn't an OpenAI-compatible "
                "model server Syzygy can use."
            ),
            serves_http=True,
            lists_models=result.lists_models,
            model_ids=result.model_ids,
            problems=problems,
        )

    if not result.json_schema_response_format:
        return RuntimeCapabilities(
            candidate=candidate,
            compatibility=Compatibility.UNSUITABLE,
            next_action=(
                "That server answers, but it can't return the strict JSON Syzygy "
                "needs. A current llama.cpp build can - update it, or let Syzygy "
                "install its own."
            ),
            serves_http=True,
            lists_models=result.lists_models,
            chat_completions=True,
            model_ids=result.model_ids,
            problems=problems,
        )

    return RuntimeCapabilities(
        candidate=candidate,
        compatibility=Compatibility.COMPATIBLE,
        next_action=f"Ready to use at {candidate.locator}.",
        serves_http=True,
        lists_models=result.lists_models,
        chat_completions=True,
        json_schema_response_format=True,
        model_ids=result.model_ids,
    )


def qualify_endpoint_blocking(
    candidate: RuntimeCandidate, *, timeout: float = 10.0
) -> RuntimeCapabilities:
    """Synchronous wrapper for callers on a worker thread (the TUI's
    `@work(thread=True)` steps, the CLI). Never raises: a base URL
    malformed enough to make httpx throw before any request is still just
    "nothing usable there"."""
    try:
        return asyncio.run(qualify_endpoint(candidate, timeout=timeout))
    except Exception as exc:  # noqa: BLE001 - a malformed URL must not crash setup
        return RuntimeCapabilities(
            candidate=candidate,
            compatibility=Compatibility.UNKNOWN,
            next_action=f"{candidate.locator} could not be contacted.",
            problems=(redact(f"{type(exc).__name__}: {exc}"),),
        )


# -- binaries ----------------------------------------------------------------


def binary_candidates(
    probe: Probe,
    *,
    paths: LocalModelPaths | None = None,
    configured_path: str | None = None,
    manifest: RuntimeManifest | None = None,
) -> tuple[RuntimeCandidate, ...]:
    """Everything on this machine that might be a llama.cpp server.

    Order is preference order, and it is deliberate: a runtime Syzygy
    installed itself is known-good and comes first; the path the user
    configured comes next, because they chose it; `PATH` comes last,
    because that is the one Syzygy knows least about.
    """
    manifest = manifest or load_runtime_manifest()
    names = (*manifest.server_executables, *manifest.unified_executables)

    candidates: list[RuntimeCandidate] = []
    seen: set[str] = set()

    def add(
        raw_path: str, source: RuntimeSource, *, owned: bool, note: str
    ) -> None:
        path = Path(raw_path)
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        key = str(resolved)
        if key in seen or not _is_executable_file(resolved):
            return
        seen.add(key)
        notes = [note]
        if str(resolved) != str(path):
            # A symlink is worth saying out loud: `/usr/local/bin/llama-server`
            # pointing into a Homebrew cellar is normal, and pointing
            # somewhere surprising is exactly what a user should see.
            notes.append(f"resolves to {redact(str(resolved))}")
        candidates.append(
            RuntimeCandidate(
                kind=RuntimeKind.BINARY,
                source=source,
                locator=str(path),
                resolved_path=str(resolved),
                syzygy_owned=owned,
                notes=tuple(notes),
            )
        )

    if paths is not None:
        for name in names:
            for found in sorted(paths.runtime_dir.rglob(name)):
                add(
                    str(found),
                    RuntimeSource.MANAGED,
                    owned=True,
                    note="installed by Syzygy",
                )

    if configured_path:
        add(
            configured_path,
            RuntimeSource.CONFIGURED,
            owned=paths is not None and paths.contains(Path(configured_path)),
            note="the path you configured previously",
        )

    for name in names:
        on_path = probe.which(name)
        if on_path:
            add(on_path, RuntimeSource.PATH, owned=False, note=f"found on PATH as {name}")

    return tuple(candidates)


def _is_executable_file(path: Path) -> bool:
    try:
        mode = path.stat().st_mode
    except OSError:
        return False
    if not stat.S_ISREG(mode):
        return False
    if os.name == "nt":
        return path.suffix.lower() in (".exe", ".bat", ".cmd", "")
    return bool(mode & stat.S_IXUSR)


def qualify_binary(
    candidate: RuntimeCandidate,
    probe: Probe,
    *,
    manifest: RuntimeManifest | None = None,
    minimum_build: int | None = None,
) -> RuntimeCapabilities:
    """Ask a candidate executable what it is, and classify the answer.

    Read-only: the only thing run is `--version`, which loads no model,
    binds no port, and writes nothing. That is enough to separate "this is
    llama.cpp build 10331" from "this is a file someone named
    `llama-server`", and the rest of the capability picture comes from
    actually starting it later (`supervisor` → `qualify_endpoint`).
    """
    manifest = manifest or load_runtime_manifest()
    floor = minimum_build if minimum_build is not None else manifest.build

    executable = candidate.resolved_path or candidate.locator
    result = probe.run((executable, "--version"), _VERSION_TIMEOUT)

    if result.missing:
        return RuntimeCapabilities(
            candidate=candidate,
            compatibility=Compatibility.UNKNOWN,
            next_action="That file is no longer there.",
            problems=(redact(result.failure_note),),
        )
    if result.timed_out:
        return RuntimeCapabilities(
            candidate=candidate,
            compatibility=Compatibility.UNKNOWN,
            next_action=(
                "That program didn't answer a version query. Syzygy won't use it; "
                "it can install its own copy instead."
            ),
            problems=(redact(result.failure_note),),
        )

    # Both streams: `llama-server` prints its version to stderr, the newer
    # unified `llama` prints to stdout, and a wrapper script may do either.
    text = f"{result.stdout}\n{result.stderr}"
    build = _parse_build(text)
    if build is None:
        return RuntimeCapabilities(
            candidate=candidate,
            compatibility=Compatibility.UNSUITABLE,
            next_action=(
                "That program is named like llama.cpp but doesn't identify itself as "
                "llama.cpp. Syzygy will leave it alone."
            ),
            problems=(redact(_first_line(text)) or "no recognizable version output",),
        )

    version = f"b{build}"
    updated = candidate.model_copy(update={"version": detected(version)})

    if build < floor:
        return RuntimeCapabilities(
            candidate=updated,
            compatibility=Compatibility.COMPATIBLE_BUT_OLD,
            next_action=(
                f"This is llama.cpp {version}; Syzygy is tested against b{floor}. "
                "It will probably work - update it yourself if a reading fails, or "
                "let Syzygy install its own copy alongside."
            ),
            version=version,
            backend=_declared_backend(text),
        )

    return RuntimeCapabilities(
        candidate=updated,
        compatibility=Compatibility.COMPATIBLE,
        next_action=f"llama.cpp {version} is installed and Syzygy can use it.",
        version=version,
        backend=_declared_backend(text),
    )


def _parse_build(text: str) -> int | None:
    for pattern in _VERSION_PATTERNS:
        match = pattern.search(text)
        if match:
            return int(match.group("build"))
    return None


def _declared_backend(text: str) -> Backend | None:
    """What the build says it was compiled for, if it says. Advisory only -
    the authoritative answer comes from the server's own startup log, and
    a missing answer here is not a problem."""
    lowered = text.lower()
    for token, backend in (
        ("metal", Backend.METAL),
        ("cuda", Backend.CUDA),
        ("rocm", Backend.ROCM),
        ("hip", Backend.ROCM),
        ("vulkan", Backend.VULKAN),
        ("sycl", Backend.SYCL),
    ):
        if token in lowered:
            return backend
    return None


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:200]
    return ""


def unknown_candidate(locator: str, note: str) -> RuntimeCandidate:
    """A candidate for something that was named but not found - so the UI
    can say "the path you configured is gone" rather than silently
    dropping it."""
    return RuntimeCandidate(
        kind=RuntimeKind.BINARY,
        source=RuntimeSource.CONFIGURED,
        locator=locator,
        version=unknown(note),
        notes=(note,),
    )
