"""Read-only history: the `iching-v1` cast-only consultations (M20).

The alternative-Oracle mode these rows came from no longer exists: M22
casts both objects in one rite (`syzygy.storage.consultations`, ADR 0008).
They stay readable in the archive forever and can never be advanced, so
this module has readers and a delete and no writers at all.
`iching_consultations` is neither altered nor dropped.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from syzygy.domain.astrology import TransitSnapshot
from syzygy.domain.iching import IChingCast
from syzygy.domain.iching_consultation import IChingConsultation, IChingStatus
from syzygy.domain.interpretation import InterpretationContext, OracleResult
from syzygy.domain.oracle import OracleQuestion


def _row_to_consultation(row: sqlite3.Row) -> IChingConsultation:
    return IChingConsultation(
        id=row["id"],
        profile_id=row["profile_id"],
        question=OracleQuestion(
            text=row["question_text"],
            normalized_text=row["question_normalized"],
            asked_at_utc=datetime.fromisoformat(row["asked_at_utc"]),
            consultation_local_date=row["consultation_local_date"],
        ),
        status=IChingStatus(row["status"]),
        consultation_local_timestamp=row["consultation_local_timestamp"],
        consultation_timezone=row["consultation_timezone"],
        cast=(
            IChingCast.model_validate_json(row["cast_json"])
            if row["cast_json"] is not None
            else None
        ),
        transit_snapshot=(
            TransitSnapshot.model_validate_json(row["transit_snapshot_json"])
            if row["transit_snapshot_json"] is not None
            else None
        ),
        interpretation_context=(
            InterpretationContext.model_validate_json(row["interpretation_context_json"])
            if row["interpretation_context_json"] is not None
            else None
        ),
        result=(
            OracleResult.model_validate_json(row["result_json"])
            if row["result_json"] is not None
            else None
        ),
        provider_id=row["provider_id"],
        model_id=row["model_id"],
        prompt_version=row["prompt_version"],
        created_at_utc=datetime.fromisoformat(row["created_at"]),
        updated_at_utc=datetime.fromisoformat(row["updated_at"]),
    )


def get_by_id(conn: sqlite3.Connection, consultation_id: str) -> IChingConsultation | None:
    row = conn.execute(
        "SELECT * FROM iching_consultations WHERE id = ?", (consultation_id,)
    ).fetchone()
    return _row_to_consultation(row) if row is not None else None


def list_consultations(
    conn: sqlite3.Connection, profile_id: str, *, limit: int | None = None
) -> list[IChingConsultation]:
    sql = (
        "SELECT * FROM iching_consultations WHERE profile_id = ? "
        "ORDER BY asked_at_utc DESC, created_at DESC"
    )
    params: list[object] = [profile_id]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return [_row_to_consultation(row) for row in conn.execute(sql, params).fetchall()]


def delete_consultation(
    conn: sqlite3.Connection, consultation_id: str, *, profile_id: str
) -> bool:
    """Delete exactly one I Ching consultation owned by a profile."""
    deleted = conn.execute(
        "DELETE FROM iching_consultations WHERE id = ? AND profile_id = ?",
        (consultation_id, profile_id),
    ).rowcount
    return deleted == 1
