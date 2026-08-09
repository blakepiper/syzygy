"""Shared fixtures for the local-model tests.

The machine fixtures themselves live in `machines.py` so they can be
imported explicitly; this file holds only the pytest fixtures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from syzygy.local_models.paths import LocalModelPaths


@pytest.fixture
def local_paths(tmp_path: Path) -> LocalModelPaths:
    paths = LocalModelPaths(
        root=tmp_path / "local_models",
        runtime_dir=tmp_path / "local_models" / "runtime",
        models_dir=tmp_path / "local_models" / "gguf",
        partial_dir=tmp_path / "local_models" / "partial",
        logs_dir=tmp_path / "local_models" / "logs",
        state_path=tmp_path / "local_models" / "state.json",
    )
    paths.ensure_exists()
    return paths


@pytest.fixture
def settings_path(tmp_path: Path) -> Path:
    return tmp_path / "settings.json"
