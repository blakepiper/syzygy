"""Read-only history: the `oracle-v1` single-card consultations (M19).

M22 replaced that rite with one that casts a card *and* a hexagram
(`syzygy.storage.consultations`, ADR 0008). These rows remain in the
archive forever and are readable forever; they cannot be retried,
resumed, or regenerated, so this module has readers and a delete and no
writers at all. `oracle_consultations` is neither altered nor dropped.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from pydantic import TypeAdapter

from syzygy.domain.astrology import TransitSnapshot
from syzygy.domain.interpretation import InterpretationContext, OracleResult
from syzygy.domain.knowledge import RetrievedCitation
from syzygy.domain.oracle import OracleConsultation, OracleQuestion, OracleStatus
from syzygy.domain.tarot import TarotDraw

_citations_adapter = TypeAdapter(list[RetrievedCitation])


def _row_to_consultation(row: sqlite3.Row) -> OracleConsultation:
    citations: list[RetrievedCitation] = []
    if row["retrieved_citations_json"] is not None:
        citations = _citations_adapter.validate_json(row["retrieved_citations_json"])
    return OracleConsultation(
        id=row["id"],
        profile_id=row["profile_id"],
        question=OracleQuestion(
            text=row["question_text"],
            normalized_text=row["question_normalized"],
            asked_at_utc=datetime.fromisoformat(row["asked_at_utc"]),
            consultation_local_date=row["consultation_local_date"],
        ),
        status=OracleStatus(row["status"]),
        consultation_local_timestamp=row["consultation_local_timestamp"],
        consultation_timezone=row["consultation_timezone"],
        card_draw=(
            TarotDraw.model_validate_json(row["card_draw_json"])
            if row["card_draw_json"] is not None
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
        retrieved_citations=citations,
        provider_id=row["provider_id"],
        model_id=row["model_id"],
        prompt_version=row["prompt_version"],
        result=(
            OracleResult.model_validate_json(row["result_json"])
            if row["result_json"] is not None
            else None
        ),
        created_at_utc=datetime.fromisoformat(row["created_at"]),
        updated_at_utc=datetime.fromisoformat(row["updated_at"]),
    )


def get_by_id(conn: sqlite3.Connection, consultation_id: str) -> OracleConsultation | None:
    row = conn.execute(
        "SELECT * FROM oracle_consultations WHERE id = ?", (consultation_id,)
    ).fetchone()
    return _row_to_consultation(row) if row is not None else None


def list_consultations(
    conn: sqlite3.Connection, profile_id: str, *, limit: int | None = None
) -> list[OracleConsultation]:
    sql = (
        "SELECT * FROM oracle_consultations WHERE profile_id = ? "
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
    """Delete exactly one question-led Thoth consultation owned by a profile."""
    deleted = conn.execute(
        "DELETE FROM oracle_consultations WHERE id = ? AND profile_id = ?",
        (consultation_id, profile_id),
    ).rowcount
    return deleted == 1
