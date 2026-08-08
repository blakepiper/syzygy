"""SQLite connection management.

One SQLite file per installation (`AppPaths.database_path`, see
`syzygy.config`). No ORM - DESIGN.md section 16.2 and
ARCHITECTURE_HANDOFF.md section 25 both call for explicit SQL over an ORM
for a project this size.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(database_path: Path | str, *, check_same_thread: bool = True) -> sqlite3.Connection:
    """Open a connection with the pragmas Syzygy relies on everywhere:
    foreign keys enforced, and rows addressable by column name.

    Does not run migrations - call `syzygy.storage.migrations.apply_all`
    on the returned connection before using it, or use
    `open_database` which does both.

    `check_same_thread=False` exists for the TUI (`syzygy.tui`), whose
    Textual thread workers necessarily touch the database from a thread
    other than the one that opened it. It is safe there only because those
    workers are declared `exclusive` and never overlap - do not pass it to
    get concurrent writers.
    """
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        path,
        isolation_level=None,  # autocommit; use explicit BEGIN
        check_same_thread=check_same_thread,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def open_database(
    database_path: Path | str, *, check_same_thread: bool = True
) -> sqlite3.Connection:
    """Open a connection and bring the schema up to date. This is the
    normal entry point for application code; `connect` alone is mostly
    useful for migration tests that want to control ordering explicitly.
    """
    from syzygy.storage.migrations import apply_all  # local import: avoid a cycle at module load

    conn = connect(database_path, check_same_thread=check_same_thread)
    apply_all(conn)
    return conn
