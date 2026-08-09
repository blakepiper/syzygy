"""Explicit, ordered SQLite schema migrations.

No migration framework library - docs/old/DESIGN.md section 16.2: "For a small
local application, avoid introducing an ORM solely for migrations unless
implementation complexity later justifies it." Each migration is a plain
SQL string, applied in order, tracked in `schema_migrations`. Migrations
are append-only: once merged, a migration's SQL must never be edited -
add a new migration instead, even to fix a mistake in an old one. This is
what makes `docs/THOTH_INGESTION_MAP.md`-style historical reproducibility
possible for the database itself.

Large nested structures (a full natal chart, a full transit snapshot, an
interpretation context) are stored as JSON columns rather than normalized
across many tables, per docs/old/ARCHITECTURE_HANDOFF.md section 25: "Do not
prematurely normalize every astrological coordinate into relational
tables." Every such JSON blob carries its own schema version inside the
serialized payload (via the corresponding Pydantic model's version
fields) - the database does not separately version JSON column shapes.
"""

from __future__ import annotations

import sqlite3

# Each entry is (version, description, sql). `version` must be a
# monotonically increasing integer starting at 1; storage/database.py
# applies any migration whose version is not yet recorded in
# `schema_migrations`, in list order.
_MIGRATIONS: list[tuple[int, str, str]] = [
    (
        1,
        "initial schema: profiles, readings, knowledge_sources, knowledge_chunks",
        """
        CREATE TABLE profiles (
            id                          TEXT PRIMARY KEY,
            name                        TEXT NOT NULL,
            birth_date                  TEXT NOT NULL,
            birth_time                  TEXT NOT NULL,
            birth_place_label           TEXT NOT NULL,
            birth_latitude              REAL NOT NULL,
            birth_longitude             REAL NOT NULL,
            birth_timezone              TEXT NOT NULL,
            house_system                TEXT NOT NULL,
            zodiac_type                 TEXT NOT NULL,
            astrology_engine            TEXT NOT NULL,
            astrology_engine_version    TEXT NOT NULL,
            chart_schema_version        TEXT NOT NULL,
            natal_chart_json            TEXT NOT NULL,
            created_at                  TEXT NOT NULL,
            updated_at                  TEXT NOT NULL
        );

        CREATE TABLE readings (
            id                              TEXT PRIMARY KEY,
            profile_id                      TEXT NOT NULL REFERENCES profiles(id),
            consultation_local_date         TEXT NOT NULL,
            consultation_local_timestamp    TEXT NOT NULL,
            consultation_utc_timestamp      TEXT NOT NULL,
            consultation_timezone           TEXT NOT NULL,

            status                          TEXT NOT NULL,

            card_id                         TEXT,
            sortes_version                  TEXT,
            entropy_digest                  TEXT,

            astrology_policy_version        TEXT,
            transit_snapshot_json           TEXT,
            selected_transits_json          TEXT,
            interpretation_context_json     TEXT,

            provider_id                     TEXT,
            model_id                        TEXT,
            prompt_version                  TEXT,
            interpretation_json             TEXT,

            created_at                      TEXT NOT NULL,
            updated_at                      TEXT NOT NULL,

            UNIQUE (profile_id, consultation_local_date)
        );

        CREATE TABLE knowledge_sources (
            id                  TEXT PRIMARY KEY,
            source_type         TEXT NOT NULL,
            title               TEXT NOT NULL,
            file_hash           TEXT NOT NULL,
            ingestion_version   TEXT NOT NULL,
            created_at          TEXT NOT NULL
        );

        CREATE TABLE knowledge_chunks (
            id              TEXT PRIMARY KEY,
            source_id       TEXT NOT NULL REFERENCES knowledge_sources(id),
            section_id      TEXT NOT NULL,
            section_type    TEXT NOT NULL,
            card_id         TEXT,
            title           TEXT NOT NULL,
            page_start      INTEGER NOT NULL,
            page_end        INTEGER NOT NULL,
            chunk_index     INTEGER NOT NULL,
            text            TEXT NOT NULL,
            text_hash       TEXT NOT NULL
        );

        CREATE INDEX idx_readings_profile_date
            ON readings (profile_id, consultation_local_date);

        CREATE INDEX idx_knowledge_chunks_card_id
            ON knowledge_chunks (card_id);
        """,
    ),
    (
        2,
        "readings: add card_drawn_at_utc (TarotDraw.drawn_at_utc has no home in migration 1)",
        """
        ALTER TABLE readings ADD COLUMN card_drawn_at_utc TEXT;
        """,
    ),
    (
        3,
        "knowledge_chunks_fts: FTS5 lexical index over knowledge_chunks.text (M6.4)",
        """
        CREATE VIRTUAL TABLE knowledge_chunks_fts USING fts5(
            text,
            content='knowledge_chunks',
            content_rowid='rowid',
            tokenize='porter unicode61'
        );

        CREATE TRIGGER knowledge_chunks_ai AFTER INSERT ON knowledge_chunks BEGIN
            INSERT INTO knowledge_chunks_fts(rowid, text) VALUES (new.rowid, new.text);
        END;

        CREATE TRIGGER knowledge_chunks_ad AFTER DELETE ON knowledge_chunks BEGIN
            INSERT INTO knowledge_chunks_fts(knowledge_chunks_fts, rowid, text)
            VALUES ('delete', old.rowid, old.text);
        END;

        CREATE TRIGGER knowledge_chunks_au AFTER UPDATE ON knowledge_chunks BEGIN
            INSERT INTO knowledge_chunks_fts(knowledge_chunks_fts, rowid, text)
            VALUES ('delete', old.rowid, old.text);
            INSERT INTO knowledge_chunks_fts(rowid, text) VALUES (new.rowid, new.text);
        END;
        """,
    ),
    (
        4,
        "knowledge_chunks: add vector BLOB for hashed lexical signatures (M13.3)",
        """
        ALTER TABLE knowledge_chunks ADD COLUMN vector BLOB;
        ALTER TABLE knowledge_chunks ADD COLUMN vector_version TEXT;
        ALTER TABLE knowledge_chunks ADD COLUMN word_count INTEGER;
        """,
    ),
    (
        5,
        "interpretive summaries: stable natal cache and per-local-day cosmos cache (M13.2)",
        """
        CREATE TABLE interpretive_summaries (
            profile_id       TEXT NOT NULL REFERENCES profiles(id),
            kind             TEXT NOT NULL CHECK (kind IN ('natal_summary', 'cosmos_summary')),
            scope_date       TEXT NOT NULL,
            context_json     TEXT NOT NULL,
            result_json      TEXT NOT NULL,
            provider_id      TEXT NOT NULL,
            model_id         TEXT NOT NULL,
            prompt_version   TEXT NOT NULL,
            created_at       TEXT NOT NULL,
            PRIMARY KEY (profile_id, kind, scope_date)
        );
        """,
    ),
    (
        6,
        "readings: add retrieved_citations_json - what retrieval found, not what was sent (M18.1a)",
        """
        ALTER TABLE readings ADD COLUMN retrieved_citations_json TEXT;
        """,
    ),
    (
        7,
        "oracle consultations: separate question-led rite (M19)",
        """
        CREATE TABLE oracle_consultations (
            id                          TEXT PRIMARY KEY,
            profile_id                  TEXT NOT NULL REFERENCES profiles(id),
            question_text               TEXT NOT NULL,
            question_normalized         TEXT NOT NULL,
            asked_at_utc                TEXT NOT NULL,
            consultation_local_date     TEXT NOT NULL,
            consultation_local_timestamp TEXT NOT NULL,
            consultation_timezone       TEXT NOT NULL,
            status                      TEXT NOT NULL,
            card_draw_json              TEXT,
            transit_snapshot_json       TEXT,
            interpretation_context_json TEXT,
            retrieved_citations_json    TEXT,
            result_json                 TEXT,
            provider_id                 TEXT,
            model_id                    TEXT,
            prompt_version              TEXT,
            created_at                  TEXT NOT NULL,
            updated_at                  TEXT NOT NULL
        );

        CREATE INDEX idx_oracle_consultations_profile_asked_at
            ON oracle_consultations (profile_id, asked_at_utc DESC);
        """,
    ),
    (
        8,
        "profiles: own the persistent natal-chart summary",
        """
        ALTER TABLE profiles ADD COLUMN natal_summary_json TEXT;

        UPDATE profiles
        SET natal_summary_json = (
            SELECT result_json
            FROM interpretive_summaries
            WHERE interpretive_summaries.profile_id = profiles.id
              AND kind = 'natal_summary'
              AND scope_date = ''
            LIMIT 1
        )
        WHERE EXISTS (
            SELECT 1
            FROM interpretive_summaries
            WHERE interpretive_summaries.profile_id = profiles.id
              AND kind = 'natal_summary'
              AND scope_date = ''
        );

        DELETE FROM interpretive_summaries
        WHERE kind = 'natal_summary' AND scope_date = '';
        """,
    ),
    (
        9,
        "I Ching consultations: immutable alternative Oracle rite (M20)",
        """
        CREATE TABLE iching_consultations (
            id                           TEXT PRIMARY KEY,
            profile_id                   TEXT NOT NULL REFERENCES profiles(id),
            question_text                TEXT NOT NULL,
            question_normalized          TEXT NOT NULL,
            asked_at_utc                 TEXT NOT NULL,
            consultation_local_date      TEXT NOT NULL,
            consultation_local_timestamp TEXT NOT NULL,
            consultation_timezone        TEXT NOT NULL,
            status                       TEXT NOT NULL,
            cast_json                    TEXT,
            transit_snapshot_json        TEXT,
            interpretation_context_json  TEXT,
            result_json                  TEXT,
            provider_id                  TEXT,
            model_id                     TEXT,
            prompt_version               TEXT,
            created_at                   TEXT NOT NULL,
            updated_at                   TEXT NOT NULL
        );

        CREATE INDEX idx_iching_consultations_profile_asked_at
            ON iching_consultations (profile_id, asked_at_utc DESC);
        """,
    ),
]


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )


def current_version(conn: sqlite3.Connection) -> int:
    _ensure_migrations_table(conn)
    row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
    return int(row[0])


def apply_all(conn: sqlite3.Connection) -> None:
    """Apply every migration in `_MIGRATIONS` not yet recorded as applied.
    Idempotent: safe to call on every application startup.

    Each migration's DDL and its `schema_migrations` bookkeeping row are
    applied as one atomic script. `sqlite3.Connection.executescript`
    ignores any transaction started via a separate `conn.execute("BEGIN")`
    call (it always starts from a clean autocommit state), so the
    `BEGIN`/`COMMIT` here are embedded directly in the script text rather
    than issued as separate statements - that is the only way to get
    atomicity across a whole migration through the stdlib `sqlite3` API.
    `description` is always a trusted literal from `_MIGRATIONS`, never
    user input, so inlining it (with a defensive quote-escape) is safe.
    """
    _ensure_migrations_table(conn)
    applied = current_version(conn)
    for version, description, sql in _MIGRATIONS:
        if version <= applied:
            continue
        safe_description = description.replace("'", "''")
        script = (
            f"{sql}\n"
            f"INSERT INTO schema_migrations (version, description) "
            f"VALUES ({version}, '{safe_description}');\n"
        )
        try:
            conn.executescript(f"BEGIN;\n{script}COMMIT;")
        except Exception:
            conn.execute("ROLLBACK")
            raise
