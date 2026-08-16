"""Distribution capabilities promised by the default installation."""

from __future__ import annotations

import tomllib
import zipfile
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).parents[1]


def project() -> dict:
    return tomllib.loads((REPOSITORY / "pyproject.toml").read_text(encoding="utf-8"))["project"]


def test_audio_and_geocoding_ship_in_the_main_install() -> None:
    metadata = project()
    dependencies = {entry.split(">=", 1)[0] for entry in metadata["dependencies"]}

    assert {"geopy", "timezonefinder", "just_playback"} <= dependencies
    assert metadata["optional-dependencies"]["geocoding"] == []
    assert metadata["optional-dependencies"]["audio"] == []


def test_guided_local_model_setup_ships_in_the_main_install() -> None:
    """M16 makes the local path the beginner path, so its one runtime
    dependency cannot live behind an extra. The `providers` extra keeps
    listing httpx so an existing `pip install .[providers]` still works."""
    metadata = project()
    dependencies = {entry.split(">=", 1)[0] for entry in metadata["dependencies"]}

    assert "httpx" in dependencies


def test_the_catalog_and_runtime_manifest_are_packaged() -> None:
    """They are data the application cannot start setup without, and they
    live under `syzygy.resources` precisely so the wheel carries them."""
    from importlib import resources

    package = resources.files("syzygy.resources.local_models")
    assert package.joinpath("catalog.yaml").is_file()
    assert package.joinpath("runtimes.yaml").is_file()


def test_audio_assets_are_packaged() -> None:
    from importlib import resources

    package = resources.files("syzygy.resources.audio")
    assert package.joinpath("theme.mp3").is_file()
    assert package.joinpath("notification.wav").is_file()


# -- the built distribution ---------------------------------------------------

#: Anything matching these must never appear in a wheel or sdist: they are
#: a *user's* downloaded artifacts and machine state, not the program.
FORBIDDEN_FRAGMENTS = (
    ".gguf",
    "local_models/runtime/",
    "local_models/gguf/",
    "local_models/partial/",
    "local_models/logs/",
    "OWNERSHIP.json",
    "state.json",
    "settings.json",
    "diagnostics.txt",
)


def built_wheel() -> Path | None:
    candidates = sorted((REPOSITORY / "dist").glob("syzygy-*.whl"))
    return candidates[-1] if candidates else None


@pytest.mark.skipif(built_wheel() is None, reason="no built wheel in dist/")
def test_a_built_wheel_carries_the_schemas_but_no_user_artifacts() -> None:
    """Runs only when `python -m build` has been run - the release gate
    (M16.10e), not something every `pytest` should have to do."""
    wheel = built_wheel()
    assert wheel is not None
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()

    assert "syzygy/resources/local_models/catalog.yaml" in names
    assert "syzygy/resources/local_models/runtimes.yaml" in names
    assert any(name.startswith("syzygy/local_models/") for name in names)

    leaked = [
        name
        for name in names
        if any(fragment in name for fragment in FORBIDDEN_FRAGMENTS)
    ]
    assert leaked == []
