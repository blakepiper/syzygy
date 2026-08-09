"""Discovering and qualifying what already exists (M16.4e).

Two seams, both faked: `Probe` for the filesystem and `--version`, and
`httpx.MockTransport` for the endpoint. Nothing here contacts a real
server or executes a real binary.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from syzygy.local_models.catalog import load_runtime_manifest
from syzygy.local_models.contracts import Backend, Compatibility, RuntimeSource
from syzygy.local_models.discovery import (
    CONVENTIONAL_PORTS,
    binary_candidates,
    endpoint_candidates,
    is_local_url,
    qualify_binary,
    qualify_endpoint,
)
from syzygy.local_models.probe import CommandResult

from .machines import linux_cpu_probe, make_probe, ok


def executable(path: Path, content: str = "#!/bin/sh\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(0o755)
    return path


# -- endpoint candidates -----------------------------------------------------


def test_the_saved_endpoint_is_tried_first() -> None:
    candidates = endpoint_candidates("http://127.0.0.1:9999/v1")

    assert candidates[0].locator == "http://127.0.0.1:9999/v1"
    assert candidates[0].source is RuntimeSource.CONFIGURED


def test_both_localhost_families_are_tried_and_nothing_else() -> None:
    locators = [candidate.locator for candidate in endpoint_candidates()]

    assert any("127.0.0.1:8080" in url for url in locators)
    assert any("[::1]:8080" in url for url in locators)
    # Localhost only: no LAN address, no wildcard, no port sweep.
    assert all(is_local_url(url) for url in locators)
    assert len(locators) == len(CONVENTIONAL_PORTS) * 2


def test_a_duplicate_saved_url_is_not_probed_twice() -> None:
    candidates = endpoint_candidates("http://127.0.0.1:8080/v1")
    locators = [candidate.locator for candidate in candidates]

    assert locators.count("http://127.0.0.1:8080/v1") == 1


def test_a_remote_url_is_recognised_as_non_local() -> None:
    assert is_local_url("http://192.168.1.10:8080/v1") is False
    assert is_local_url("http://localhost:8080/v1") is True


# -- endpoint qualification --------------------------------------------------


def transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


async def qualify(handler, url: str = "http://127.0.0.1:8080/v1"):
    candidate = endpoint_candidates(url, include_conventional=False)[0]
    return await qualify_endpoint(candidate, transport=transport(handler))


async def test_a_fully_capable_server_is_compatible() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "local-model"}]})
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"ok": true}'}}]}
        )

    result = await qualify(handler)

    assert result.compatibility is Compatibility.COMPATIBLE
    assert result.json_schema_response_format is True
    assert result.model_ids == ("local-model",)


async def test_a_server_that_ignores_the_schema_is_unsuitable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "m"}]})
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "Sure! Here you go."}}]}
        )

    result = await qualify(handler)

    assert result.compatibility is Compatibility.UNSUITABLE
    assert result.chat_completions is True
    assert result.json_schema_response_format is False
    assert "strict JSON" in result.next_action


@pytest.mark.parametrize("status", [401, 403])
async def test_an_authenticating_server_gets_its_own_explanation(status: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "unauthorized"})

    result = await qualify(handler)

    assert result.compatibility is Compatibility.UNSUITABLE
    assert "API key" in result.next_action


async def test_nothing_listening_is_unknown_not_unsuitable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    result = await qualify(handler)

    assert result.compatibility is Compatibility.UNKNOWN
    assert result.serves_http is False


async def test_something_that_is_not_a_model_server_is_unsuitable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, text="<html>a web server</html>")
        return httpx.Response(404)

    result = await qualify(handler)

    assert result.compatibility is Compatibility.UNSUITABLE
    assert result.serves_http is True


async def test_an_endpoint_that_disappears_mid_probe_is_handled() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json={"data": [{"id": "m"}]})
        raise httpx.ConnectError("gone", request=request)

    result = await qualify(handler)

    assert result.compatibility is Compatibility.UNSUITABLE
    assert result.lists_models is True
    assert result.chat_completions is False


# -- binary discovery --------------------------------------------------------


def test_path_precedence_puts_a_managed_runtime_first(tmp_path, local_paths) -> None:
    managed = executable(local_paths.runtime_dir / "b10331" / "llama-server")
    system = executable(tmp_path / "usr" / "bin" / "llama-server")
    probe = linux_cpu_probe(which={"llama-server": str(system)})

    candidates = binary_candidates(probe, paths=local_paths)

    assert candidates[0].resolved_path == str(managed.resolve())
    assert candidates[0].syzygy_owned is True
    assert candidates[0].source is RuntimeSource.MANAGED
    assert candidates[1].source is RuntimeSource.PATH


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks")
def test_a_symlink_is_resolved_and_reported(tmp_path) -> None:
    real = executable(tmp_path / "cellar" / "llama-server")
    link = tmp_path / "bin" / "llama-server"
    link.parent.mkdir(parents=True)
    link.symlink_to(real)
    probe = linux_cpu_probe(which={"llama-server": str(link)})

    candidate = binary_candidates(probe)[0]

    assert candidate.locator == str(link)
    assert candidate.resolved_path == str(real.resolve())
    assert any("resolves to" in note for note in candidate.notes)


def test_a_path_with_spaces_and_non_ascii_is_handled(tmp_path) -> None:
    target = executable(tmp_path / "Élan Vitàl" / "my tools" / "llama-server")
    probe = linux_cpu_probe(which={"llama-server": str(target)})

    candidates = binary_candidates(probe)

    assert candidates[0].resolved_path == str(target.resolve())


def test_the_same_binary_found_twice_appears_once(tmp_path) -> None:
    target = executable(tmp_path / "bin" / "llama-server")
    probe = linux_cpu_probe(which={"llama-server": str(target), "llama": str(target)})

    assert len(binary_candidates(probe, configured_path=str(target))) == 1


def test_a_configured_path_that_no_longer_exists_is_dropped(tmp_path) -> None:
    probe = linux_cpu_probe()
    assert binary_candidates(probe, configured_path=str(tmp_path / "gone")) == ()


def test_a_non_executable_file_is_not_a_candidate(tmp_path) -> None:
    target = tmp_path / "llama-server"
    target.write_text("text")
    target.chmod(0o644)
    probe = linux_cpu_probe(which={"llama-server": str(target)})

    assert binary_candidates(probe) == ()


# -- binary qualification ----------------------------------------------------


def candidate_for(tmp_path, version_result: CommandResult):
    target = executable(tmp_path / "llama-server")
    probe = make_probe(
        which={"llama-server": str(target)},
        commands={(str(target.resolve()), "--version"): version_result},
    )
    return binary_candidates(probe)[0], probe


def test_llama_server_version_on_stderr_is_parsed(tmp_path) -> None:
    candidate, probe = candidate_for(
        tmp_path, ok(stderr="version: 10331 (7ba604f1c)\nbuilt with GNU 11.4.0\n")
    )
    result = qualify_binary(candidate, probe)

    assert result.compatibility is Compatibility.COMPATIBLE
    assert result.version == "b10331"


def test_the_unified_llama_version_on_stdout_is_parsed(tmp_path) -> None:
    candidate, probe = candidate_for(tmp_path, ok(stdout="b10331-7ba604f1c\n"))
    result = qualify_binary(candidate, probe)

    assert result.version == "b10331"
    assert result.compatibility is Compatibility.COMPATIBLE


def test_an_older_build_is_compatible_but_old(tmp_path) -> None:
    candidate, probe = candidate_for(tmp_path, ok(stderr="version: 6000 (abc1234)\n"))
    result = qualify_binary(candidate, probe)

    assert result.compatibility is Compatibility.COMPATIBLE_BUT_OLD
    assert result.usable is True
    assert "b" + str(load_runtime_manifest().build) in result.next_action


def test_a_same_named_program_that_is_not_llama_cpp_is_unsuitable(tmp_path) -> None:
    candidate, probe = candidate_for(tmp_path, ok(stdout="GNU coreutils 9.4\n"))
    result = qualify_binary(candidate, probe)

    assert result.compatibility is Compatibility.UNSUITABLE
    assert "doesn't identify itself" in result.next_action


def test_a_hung_executable_is_unknown_and_never_used(tmp_path) -> None:
    candidate, probe = candidate_for(
        tmp_path, CommandResult(argv=("llama-server", "--version"), timed_out=True)
    )
    result = qualify_binary(candidate, probe)

    assert result.compatibility is Compatibility.UNKNOWN
    assert result.usable is False


def test_a_declared_backend_is_picked_up_when_present(tmp_path) -> None:
    candidate, probe = candidate_for(
        tmp_path, ok(stderr="version: 10331 (abc)\nbuilt with Metal support\n")
    )
    result = qualify_binary(candidate, probe)

    assert result.backend is Backend.METAL
