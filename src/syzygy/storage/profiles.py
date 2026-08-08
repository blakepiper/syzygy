"""Profile CRUD against the `profiles` table (IMPLEMENTATION_PLAN.md §4.2).

Straightforward CRUD, no ORM. `NatalChart` round-trips through the
`natal_chart_json` column via its own `model_dump_json`/`model_validate_json`
- the other `profiles` columns (birth data, engine identity) are stored
redundantly in queryable form for `syzygy dev`-style inspection without a
JSON deserialize, but the JSON blob is always the actual source of truth
read back into `Profile.natal_chart`.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from syzygy.domain.astrology import BirthData, NatalChart
from syzygy.domain.profile import Profile


def _row_to_profile(row: sqlite3.Row) -> Profile:
    birth_data = BirthData(
        local_date=row["birth_date"],
        local_time=row["birth_time"],
        place_label=row["birth_place_label"],
        latitude=row["birth_latitude"],
        longitude=row["birth_longitude"],
        timezone=row["birth_timezone"],
        house_system=row["house_system"],
    )
    return Profile(
        id=row["id"],
        display_name=row["name"],
        birth_data=birth_data,
        natal_chart=NatalChart.model_validate_json(row["natal_chart_json"]),
        created_at_utc=datetime.fromisoformat(row["created_at"]),
        updated_at_utc=datetime.fromisoformat(row["updated_at"]),
    )


def insert_profile(conn: sqlite3.Connection, profile: Profile) -> None:
    birth = profile.birth_data
    chart = profile.natal_chart
    conn.execute(
        """
        INSERT INTO profiles (
            id, name, birth_date, birth_time, birth_place_label,
            birth_latitude, birth_longitude, birth_timezone, house_system,
            zodiac_type, astrology_engine, astrology_engine_version,
            chart_schema_version, natal_chart_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            profile.id,
            profile.display_name,
            birth.local_date,
            birth.local_time,
            birth.place_label,
            birth.latitude,
            birth.longitude,
            birth.timezone,
            birth.house_system,
            chart.zodiac_type,
            chart.astrology_engine,
            chart.astrology_engine_version,
            chart.chart_schema_version,
            chart.model_dump_json(),
            profile.created_at_utc.isoformat(),
            profile.updated_at_utc.isoformat(),
        ),
    )


def get_profile(conn: sqlite3.Connection, profile_id: str) -> Profile | None:
    row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    return _row_to_profile(row) if row is not None else None


def list_profiles(conn: sqlite3.Connection) -> list[Profile]:
    rows = conn.execute("SELECT * FROM profiles ORDER BY created_at").fetchall()
    return [_row_to_profile(row) for row in rows]


def count_readings(conn: sqlite3.Connection, profile_id: str) -> int:
    """How many readings would be destroyed along with `profile_id`.

    Deleting a profile is irreversible and takes its readings with it, so
    the caller is expected to show this number before asking the user to
    confirm (M11.2b).
    """
    row = conn.execute(
        "SELECT COUNT(*) AS total FROM readings WHERE profile_id = ?", (profile_id,)
    ).fetchone()
    return int(row["total"])


def delete_profile(conn: sqlite3.Connection, profile_id: str) -> int:
    """Delete `profile_id` and every reading belonging to it, atomically.
    Returns the number of readings deleted. A missing profile is not an
    error - the post-condition ("no such profile") already holds.

    **Readings cascade.** A reading is an interpretation *of a particular
    natal chart*; with the profile gone there is nothing left to interpret
    it against, and its `profile_id` would dangle. The cascade is done
    here in SQL rather than by the schema: `readings.profile_id` is a
    plain `REFERENCES profiles(id)` with no `ON DELETE CASCADE`
    (`storage/migrations.py` migration 1), and SQLite cannot add one to an
    existing table without rebuilding it - which is a much larger, riskier
    change than an explicit two-statement delete, and would bury a
    destructive behavior in schema metadata where no reader of this module
    would see it. `PRAGMA foreign_keys = ON` (see `storage/database.py`)
    means the order below is load-bearing: readings first, then the
    profile.

    As in `knowledge.store.replace_source`, atomicity needs an explicit
    `BEGIN`/`COMMIT` because connections are opened in autocommit mode.
    """
    conn.execute("BEGIN")
    try:
        deleted_readings = conn.execute(
            "DELETE FROM readings WHERE profile_id = ?", (profile_id,)
        ).rowcount
        conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
    return deleted_readings
