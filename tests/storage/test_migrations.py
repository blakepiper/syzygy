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


def test_readings_carry_a_retrieved_citations_column(conn):
    """Migration 6 (M18.1a). Nullable and appended, so a reading committed
    before it reopens as a reading with no citations rather than a
    validation error."""
    apply_all(conn)
    columns = {
        row["name"]: row for row in conn.execute("PRAGMA table_info(readings)").fetchall()
    }
    assert "retrieved_citations_json" in columns
    assert columns["retrieved_citations_json"]["notnull"] == 0


def test_oracle_has_its_own_non_unique_indexed_table(conn):
    apply_all(conn)
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(oracle_consultations)")
    }
    assert {
        "question_text",
        "asked_at_utc",
        "card_draw_json",
        "interpretation_context_json",
        "result_json",
    } <= columns
    indexes = conn.execute("PRAGMA index_list(oracle_consultations)").fetchall()
    assert any(row["name"] == "idx_oracle_consultations_profile_asked_at" for row in indexes)


def test_iching_has_its_own_non_unique_indexed_table(conn):
    apply_all(conn)
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(iching_consultations)")
    }
    assert {"question_text", "status", "cast_json", "interpretation_context_json"} <= columns
    indexes = conn.execute("PRAGMA index_list(iching_consultations)").fetchall()
    assert any(row["name"] == "idx_iching_consultations_profile_asked_at" for row in indexes)
    assert not any(row["unique"] for row in indexes if row["origin"] != "pk")


def test_profiles_own_a_persistent_natal_summary(conn):
    apply_all(conn)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(profiles)")}
    assert "natal_summary_json" in columns


def test_migration_8_moves_an_existing_natal_cache_onto_its_profile(tmp_path):
    from syzygy.domain.interpretation import SummaryResult
    from syzygy.storage import migrations

    connection = connect(tmp_path / "pre-summary-profile.db")
    migrations._ensure_migrations_table(connection)
    try:
        for version, description, sql in migrations._MIGRATIONS:
            if version > 7:
                break
            connection.executescript(sql)
            connection.execute(
                "INSERT INTO schema_migrations (version, description) VALUES (?, ?)",
                (version, description),
            )
        connection.execute(
            """
            INSERT INTO profiles (
                id, name, birth_date, birth_time, birth_place_label,
                birth_latitude, birth_longitude, birth_timezone, house_system,
                zodiac_type, astrology_engine, astrology_engine_version,
                chart_schema_version, natal_chart_json, created_at, updated_at
            ) VALUES (
                'p1', 'Blake', '1990-01-01', '12:00:00', 'Here', 0, 0, 'UTC',
                'placidus', 'tropical', 'fixture', '1', 'natal-v1', '{}',
                '2026-08-09T12:00:00+00:00', '2026-08-09T12:00:00+00:00'
            )
            """
        )
        result = SummaryResult(
            headline="Already generated",
            body="This must survive the ownership migration.",
            provider_id="fixture",
            model_id="fixture-v1",
            prompt_version="natal-summary-v1",
        )
        connection.execute(
            """
            INSERT INTO interpretive_summaries (
                profile_id, kind, scope_date, context_json, result_json,
                provider_id, model_id, prompt_version, created_at
            ) VALUES ('p1', 'natal_summary', '', '{}', ?, 'fixture',
                      'fixture-v1', 'natal-summary-v1', '2026-08-09T12:00:00+00:00')
            """,
            (result.model_dump_json(),),
        )

        apply_all(connection)

        row = connection.execute(
            "SELECT natal_summary_json FROM profiles WHERE id = 'p1'"
        ).fetchone()
        assert SummaryResult.model_validate_json(row["natal_summary_json"]) == result
        old_rows = connection.execute(
            "SELECT COUNT(*) FROM interpretive_summaries "
            "WHERE profile_id = 'p1' AND kind = 'natal_summary'"
        ).fetchone()[0]
        assert old_rows == 0
    finally:
        connection.close()


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
