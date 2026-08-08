import sqlite3

import pytest

from syzygy.storage.database import connect
from syzygy.storage.migrations import apply_all, current_version


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "test.db")
    yield connection
    connection.close()


def test_apply_all_creates_expected_tables(conn):
    apply_all(conn)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert {"profiles", "readings", "knowledge_sources", "knowledge_chunks"} <= tables


def test_apply_all_is_idempotent(conn):
    apply_all(conn)
    version_after_first = current_version(conn)
    apply_all(conn)  # must not error or re-apply
    assert current_version(conn) == version_after_first


def test_readings_enforce_one_per_profile_per_local_date(conn):
    apply_all(conn)
    conn.execute(
        "INSERT INTO profiles (id, name, birth_date, birth_time, birth_place_label, "
        "birth_latitude, birth_longitude, birth_timezone, house_system, zodiac_type, "
        "astrology_engine, astrology_engine_version, chart_schema_version, "
        "natal_chart_json, created_at, updated_at) VALUES "
        "('p1','Blake','1990-01-01','12:00:00','Nowhere',0,0,'UTC','placidus','tropical',"
        "'kerykeion','5.12.9','chart-v1','{}','2026-08-07','2026-08-07')"
    )

    def insert_reading(reading_id: str) -> None:
        conn.execute(
            "INSERT INTO readings (id, profile_id, consultation_local_date, "
            "consultation_local_timestamp, consultation_utc_timestamp, "
            "consultation_timezone, status, created_at, updated_at) VALUES "
            "(?, 'p1', '2026-08-07', '2026-08-07T08:00:00', "
            "'2026-08-07T12:00:00Z', 'UTC', 'prepared', '2026-08-07', '2026-08-07')",
            (reading_id,),
        )

    insert_reading("r1")
    with pytest.raises(sqlite3.IntegrityError):
        insert_reading("r2")


def test_readings_allow_different_profiles_same_date(conn):
    apply_all(conn)
    for profile_id in ("p1", "p2"):
        conn.execute(
            "INSERT INTO profiles (id, name, birth_date, birth_time, birth_place_label, "
            "birth_latitude, birth_longitude, birth_timezone, house_system, zodiac_type, "
            "astrology_engine, astrology_engine_version, chart_schema_version, "
            "natal_chart_json, created_at, updated_at) VALUES "
            "(?, 'Someone','1990-01-01','12:00:00','Nowhere',0,0,'UTC','placidus','tropical',"
            "'kerykeion','5.12.9','chart-v1','{}','2026-08-07','2026-08-07')",
            (profile_id,),
        )
        conn.execute(
            "INSERT INTO readings (id, profile_id, consultation_local_date, "
            "consultation_local_timestamp, consultation_utc_timestamp, "
            "consultation_timezone, status, created_at, updated_at) VALUES "
            "(?, ?, '2026-08-07', '2026-08-07T08:00:00', "
            "'2026-08-07T12:00:00Z', 'UTC', 'prepared', '2026-08-07', '2026-08-07')",
            (f"r-{profile_id}", profile_id),
        )
    # No exception means both inserts succeeded.
    count = conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
    assert count == 2
