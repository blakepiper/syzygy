"""Regression tests for the optional Nix launcher."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


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
