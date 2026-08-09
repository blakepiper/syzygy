"""Cached natal and daily-cosmos model summaries (M13.2).

These are deliberately not readings: this module never imports the sortes
package, never writes `readings`, and has no card-shaped input. A natal row
uses the empty string as its stable scope date; a cosmos row uses the
consultation's local ISO date. The non-null key avoids SQLite's multiple-NULL
UNIQUE behavior and makes the database, not application timing, enforce one
canonical cache entry per scope.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from syzygy.domain.interpretation import InterpretationContext, InterpretationKind, SummaryResult

NATAL_SCOPE_DATE = ""


def get_summary(
    conn: sqlite3.Connection,
    profile_id: str,
    kind: InterpretationKind,
    scope_date: str,
) -> SummaryResult | None:
    row = conn.execute(
        """
        SELECT result_json FROM interpretive_summaries
        WHERE profile_id = ? AND kind = ? AND scope_date = ?
        """,
        (profile_id, kind.value, scope_date),
    ).fetchone()
    return SummaryResult.model_validate_json(row["result_json"]) if row is not None else None


def save_summary(
    conn: sqlite3.Connection,
    profile_id: str,
    context: InterpretationContext,
    result: SummaryResult,
    created_at: datetime,
) -> None:
    if context.kind is InterpretationKind.DAILY_READING:
        raise ValueError("daily readings cannot be stored in the summary cache")
    scope_date = (
        NATAL_SCOPE_DATE
        if context.kind is InterpretationKind.NATAL_SUMMARY
        else context.consultation_local_date
    )
    conn.execute(
        """
        INSERT INTO interpretive_summaries (
            profile_id, kind, scope_date, context_json, result_json,
            provider_id, model_id, prompt_version, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(profile_id, kind, scope_date) DO NOTHING
        """,
        (
            profile_id,
            context.kind.value,
            scope_date,
            context.model_dump_json(),
            result.model_dump_json(),
            result.provider_id,
            result.model_id,
            result.prompt_version,
            created_at.isoformat(),
        ),
    )
