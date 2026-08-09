"""State-machine-respecting persistence for I Ching consultations."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime

from syzygy.domain.astrology import TransitSnapshot
from syzygy.domain.iching import IChingCast
from syzygy.domain.iching_consultation import (
    ALLOWED_TRANSITIONS,
    IChingConsultation,
    IChingStatus,
)
from syzygy.domain.interpretation import InterpretationContext, OracleResult
from syzygy.domain.oracle import OracleQuestion


class IllegalIChingTransition(Exception):
    def __init__(self, current: IChingStatus, requested: IChingStatus) -> None:
        super().__init__(f"cannot transition I Ching from {current!r} to {requested!r}")
        self.current = current
        self.requested = requested


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


def create_asked(
    conn: sqlite3.Connection,
    *,
    profile_id: str,
    question: OracleQuestion,
    consultation_local_timestamp: str,
    consultation_timezone: str,
) -> IChingConsultation:
    consultation_id = str(uuid.uuid4())
    now = question.asked_at_utc.isoformat()
    conn.execute(
        """
        INSERT INTO iching_consultations (
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
            IChingStatus.ASKED.value,
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
    to_status: IChingStatus,
    now: datetime,
    **columns: str,
) -> IChingConsultation:
    current = get_by_id(conn, consultation_id)
    if current is None:
        raise ValueError(f"no I Ching consultation with id {consultation_id!r}")
    if to_status not in ALLOWED_TRANSITIONS[current.status]:
        raise IllegalIChingTransition(current.status, to_status)
    clauses = ["status = ?", "updated_at = ?"]
    values: list[str] = [to_status.value, now.isoformat()]
    for column, value in columns.items():
        clauses.append(f"{column} = ?")
        values.append(value)
    values.append(consultation_id)
    conn.execute(
        f"UPDATE iching_consultations SET {', '.join(clauses)} WHERE id = ?", values
    )
    updated = get_by_id(conn, consultation_id)
    assert updated is not None
    return updated


def commit_cast(
    conn: sqlite3.Connection, consultation_id: str, cast: IChingCast
) -> IChingConsultation:
    return _advance(
        conn,
        consultation_id,
        IChingStatus.CAST,
        cast.cast_at_utc,
        cast_json=cast.model_dump_json(),
    )


def commit_context(
    conn: sqlite3.Connection,
    consultation_id: str,
    *,
    snapshot: TransitSnapshot,
    context: InterpretationContext,
    now: datetime,
) -> IChingConsultation:
    return _advance(
        conn,
        consultation_id,
        IChingStatus.CONTEXT_READY,
        now,
        transit_snapshot_json=snapshot.model_dump_json(),
        interpretation_context_json=context.model_dump_json(),
    )


def begin_interpreting(
    conn: sqlite3.Connection, consultation_id: str, *, now: datetime
) -> IChingConsultation:
    return _advance(conn, consultation_id, IChingStatus.INTERPRETING, now)


def complete_interpretation(
    conn: sqlite3.Connection,
    consultation_id: str,
    result: OracleResult,
    *,
    now: datetime,
) -> IChingConsultation:
    return _advance(
        conn,
        consultation_id,
        IChingStatus.COMPLETE,
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
) -> IChingConsultation:
    return _advance(
        conn,
        consultation_id,
        IChingStatus.INTERPRETATION_FAILED,
        now,
        provider_id=provider_id,
        model_id=model_id,
        prompt_version=prompt_version,
    )
