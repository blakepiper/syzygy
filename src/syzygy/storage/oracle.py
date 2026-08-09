"""State-machine-respecting persistence for Oracle consultations."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime

from pydantic import TypeAdapter

from syzygy.domain.astrology import TransitSnapshot
from syzygy.domain.interpretation import InterpretationContext, OracleResult
from syzygy.domain.knowledge import RetrievedCitation
from syzygy.domain.oracle import (
    ALLOWED_TRANSITIONS,
    OracleConsultation,
    OracleQuestion,
    OracleStatus,
)
from syzygy.domain.tarot import TarotDraw

_citations_adapter = TypeAdapter(list[RetrievedCitation])


class IllegalOracleTransition(Exception):
    def __init__(self, current: OracleStatus, requested: OracleStatus) -> None:
        super().__init__(f"cannot transition oracle from {current!r} to {requested!r}")
        self.current = current
        self.requested = requested


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


def create_asked(
    conn: sqlite3.Connection,
    *,
    profile_id: str,
    question: OracleQuestion,
    consultation_local_timestamp: str,
    consultation_timezone: str,
) -> OracleConsultation:
    consultation_id = str(uuid.uuid4())
    now = question.asked_at_utc.isoformat()
    conn.execute(
        """
        INSERT INTO oracle_consultations (
            id, profile_id, question_text, question_normalized, asked_at_utc,
            consultation_local_date, consultation_local_timestamp,
            consultation_timezone, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            consultation_id,
            profile_id,
            question.text,
            question.normalized_text,
            now,
            question.consultation_local_date,
            consultation_local_timestamp,
            consultation_timezone,
            OracleStatus.ASKED.value,
            now,
            now,
        ),
    )
    created = get_by_id(conn, consultation_id)
    assert created is not None
    return created


def _advance(
    conn: sqlite3.Connection,
    consultation_id: str,
    to_status: OracleStatus,
    now: datetime,
    **columns: str,
) -> OracleConsultation:
    current = get_by_id(conn, consultation_id)
    if current is None:
        raise ValueError(f"no oracle consultation with id {consultation_id!r}")
    if to_status not in ALLOWED_TRANSITIONS[current.status]:
        raise IllegalOracleTransition(current.status, to_status)
    clauses = ["status = ?", "updated_at = ?"]
    values: list[str] = [to_status.value, now.isoformat()]
    for column, value in columns.items():
        clauses.append(f"{column} = ?")
        values.append(value)
    values.append(consultation_id)
    conn.execute(
        f"UPDATE oracle_consultations SET {', '.join(clauses)} WHERE id = ?", values
    )
    updated = get_by_id(conn, consultation_id)
    assert updated is not None
    return updated


def commit_draw(
    conn: sqlite3.Connection, consultation_id: str, draw: TarotDraw
) -> OracleConsultation:
    return _advance(
        conn,
        consultation_id,
        OracleStatus.DRAWN,
        draw.drawn_at_utc,
        card_draw_json=draw.model_dump_json(),
    )


def commit_context(
    conn: sqlite3.Connection,
    consultation_id: str,
    *,
    snapshot: TransitSnapshot,
    context: InterpretationContext,
    citations: list[RetrievedCitation],
    now: datetime,
) -> OracleConsultation:
    return _advance(
        conn,
        consultation_id,
        OracleStatus.CONTEXT_READY,
        now,
        transit_snapshot_json=snapshot.model_dump_json(),
        interpretation_context_json=context.model_dump_json(),
        retrieved_citations_json=_citations_adapter.dump_json(citations).decode(),
    )


def begin_interpreting(
    conn: sqlite3.Connection, consultation_id: str, *, now: datetime
) -> OracleConsultation:
    return _advance(conn, consultation_id, OracleStatus.INTERPRETING, now)


def complete_interpretation(
    conn: sqlite3.Connection,
    consultation_id: str,
    result: OracleResult,
    *,
    now: datetime,
) -> OracleConsultation:
    return _advance(
        conn,
        consultation_id,
        OracleStatus.COMPLETE,
        now,
        result_json=result.model_dump_json(),
        provider_id=result.provider_id,
        model_id=result.model_id,
        prompt_version=result.prompt_version,
    )


def fail_interpretation(
    conn: sqlite3.Connection,
    consultation_id: str,
    *,
    provider_id: str,
    model_id: str,
    prompt_version: str,
    now: datetime,
) -> OracleConsultation:
    return _advance(
        conn,
        consultation_id,
        OracleStatus.INTERPRETATION_FAILED,
        now,
        provider_id=provider_id,
        model_id=model_id,
        prompt_version=prompt_version,
    )
