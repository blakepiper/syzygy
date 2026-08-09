"""Distribution capabilities promised by the default installation."""

from __future__ import annotations

import tomllib
from pathlib import Path


def test_audio_and_geocoding_ship_in_the_main_install() -> None:
    project = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]
    dependencies = {entry.split(">=", 1)[0] for entry in project["dependencies"]}

    assert {"geopy", "timezonefinder", "just_playback"} <= dependencies
    assert project["optional-dependencies"]["geocoding"] == []
    assert project["optional-dependencies"]["audio"] == []
