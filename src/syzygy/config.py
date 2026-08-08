"""Local-first application paths.

All Syzygy state lives under one `platformdirs` user-data directory. Nothing
in this module talks to a network or a cloud account (DESIGN.md section
16, section 17).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import platformdirs

APP_NAME = "syzygy"
APP_AUTHOR = "syzygy"


@dataclass(frozen=True)
class AppPaths:
    """Resolved on-disk layout for one Syzygy installation.

    ::

        <data_dir>/
        ├── syzygy.db
        ├── settings.json
        ├── knowledge/
        ├── models/
        └── logs/
    """

    data_dir: Path
    database_path: Path
    settings_path: Path
    knowledge_dir: Path
    models_dir: Path
    logs_dir: Path

    def ensure_exists(self) -> None:
        """Create the directory layout. Safe to call repeatedly.

        `settings_path` is a file, not a directory - it is created on
        first write by whatever saves a setting there
        (`syzygy.interpretation.providers.selection.save_selection`), not
        here.
        """
        for directory in (self.data_dir, self.knowledge_dir, self.models_dir, self.logs_dir):
            directory.mkdir(parents=True, exist_ok=True)


def default_app_paths() -> AppPaths:
    data_dir = Path(platformdirs.user_data_dir(APP_NAME, APP_AUTHOR))
    return AppPaths(
        data_dir=data_dir,
        database_path=data_dir / "syzygy.db",
        settings_path=data_dir / "settings.json",
        knowledge_dir=data_dir / "knowledge",
        models_dir=data_dir / "models",
        logs_dir=data_dir / "logs",
    )
