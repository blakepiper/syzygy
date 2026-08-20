"""Regression tests for the optional Nix launcher."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


def test_base_install_includes_keyring_for_startup() -> None:
    """The TUI imports provider selection before it can choose its fallback."""
    project = Path(__file__).resolve().parents[1] / "pyproject.toml"
    project_text = project.read_text(encoding="utf-8")

    dependencies_section = project_text.split("[project.optional-dependencies]", maxsplit=1)[0]
    assert '"keyring>=25.0"' in dependencies_section


def test_nix_start_includes_ca_bundle_for_httpx() -> None:
    """A pure shell needs its own certificate bundle for provider probes."""
    launcher = Path(__file__).resolve().parents[1] / "nix-start"
    assert "python313Packages.pip gcc cacert" in launcher.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("arguments", "expected_command"),
    [
        ([], ""),
        (["doctor"], " doctor"),
    ],
)
def test_nix_start_forwards_only_supplied_arguments(
    tmp_path: Path,
    arguments: list[str],
    expected_command: str,
) -> None:
    """An empty invocation must not turn into one empty CLI argument."""
    launcher = Path(__file__).resolve().parents[1] / "nix-start"
    fake_nix_shell = tmp_path / "nix-shell"
    fake_nix_shell.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"${!#}\"\n",
        encoding="utf-8",
    )
    fake_nix_shell.chmod(0o755)

    result = subprocess.run(
        [str(launcher), *arguments],
        capture_output=True,
        check=True,
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"},
        text=True,
    )

    repo_root = launcher.parent
    assert result.stdout == (
        f"SYZYGY_NIX_SHELL=1 exec bash {repo_root}/nix-start{expected_command}\n"
    )
