"""State-machine-respecting reading storage (IMPLEMENTATION_PLAN.md §4.2).

Two layers of enforcement, per AGENTS.md:
1. The `UNIQUE(profile_id, consultation_local_date)` constraint on the
   `readings` table is the actual source of truth for "one reading per
   profile per day" - `create_prepared` catches the resulting
   `sqlite3.IntegrityError` and returns the existing row instead of
   racing a separate check-then-insert.
2. Every write function here re-checks the requested transition against
   `syzygy.domain.reading.ALLOWED_TRANSITIONS` before issuing it. This is
   defense in depth, not the primary guarantee - the primary guarantee is
   structural: there is simply no function below that moves a reading
   back to `PREPARED` or `DRAWN`.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime

from pydantic import TypeAdapter

from syzygy.domain.astrology import RankedTransit, TransitSnapshot
from syzygy.domain.interpretation import InterpretationContext, InterpretationResult
from syzygy.domain.reading import ALLOWED_TRANSITIONS, Reading, ReadingStatus
from syzygy.domain.tarot import TarotDraw

_ranked_transits_adapter = TypeAdapter(list[RankedTransit])


class IllegalReadingTransition(Exception):
    """A caller attempted a transition absent from `ALLOWED_TRANSITIONS`."""

    def __init__(self, current: ReadingStatus, requested: ReadingStatus) -> None:
        super().__init__(f"cannot transition reading from {current!r} to {requested!r}")
        self.current = current
        self.requested = requested


def _check_transition(current: ReadingStatus, requested: ReadingStatus) -> None:
    if requested not in ALLOWED_TRANSITIONS[current]:
        raise IllegalReadingTransition(current, requested)


def _row_to_reading(row: sqlite3.Row) -> Reading:
    card_draw = None
    if row["card_id"] is not None:
        card_draw = TarotDraw(
            card_id=row["card_id"],
            drawn_at_utc=datetime.fromisoformat(row["card_drawn_at_utc"]),
            sortes_version=row["sortes_version"],
            entropy_digest=row["entropy_digest"],
        )

    transit_snapshot = None
    if row["transit_snapshot_json"] is not None:
        transit_snapshot = TransitSnapshot.model_validate_json(row["transit_snapshot_json"])

    interpretation_context = None
    if row["interpretation_context_json"] is not None:
        interpretation_context = InterpretationContext.model_validate_json(
            row["interpretation_context_json"]
        )

    interpretation = None
    if row["interpretation_json"] is not None:
        interpretation = InterpretationResult.model_validate_json(row["interpretation_json"])

    return Reading(
        id=row["id"],
        profile_id=row["profile_id"],
        status=ReadingStatus(row["status"]),
        consultation_local_date=row["consultation_local_date"],
        consultation_local_timestamp=row["consultation_local_timestamp"],
        consultation_utc_timestamp=datetime.fromisoformat(row["consultation_utc_timestamp"]),
        consultation_timezone=row["consultation_timezone"],
        card_draw=card_draw,
        transit_snapshot=transit_snapshot,
        interpretation_context=interpretation_context,
        provider_id=row["provider_id"],
        model_id=row["model_id"],
        interpretation=interpretation,
        created_at_utc=datetime.fromisoformat(row["created_at"]),
        updated_at_utc=datetime.fromisoformat(row["updated_at"]),
    )


def _get_by_id(conn: sqlite3.Connection, reading_id: str) -> Reading | None:
    row = conn.execute("SELECT * FROM readings WHERE id = ?", (reading_id,)).fetchone()
    return _row_to_reading(row) if row is not None else None


def get_today(conn: sqlite3.Connection, profile_id: str, local_date: str) -> Reading | None:
    row = conn.execute(
        "SELECT * FROM readings WHERE profile_id = ? AND consultation_local_date = ?",
        (profile_id, local_date),
    ).fetchone()
    return _row_to_reading(row) if row is not None else None


def get_by_id(conn: sqlite3.Connection, reading_id: str) -> Reading | None:
    """Read one reading back verbatim. Reopening a past reading is a pure
    read - nothing here recalculates astrology or re-runs a provider.
    """
    return _get_by_id(conn, reading_id)


def list_readings(
    conn: sqlite3.Connection, profile_id: str, *, limit: int | None = None
) -> list[Reading]:
    """One profile's readings, most recent local date first.

    The archive's list view (Milestone 5) needs only this much; the
    frequency/statistics queries in DESIGN.md section 15 are Milestone 8.
    """
    sql = (
        "SELECT * FROM readings WHERE profile_id = ? "
        "ORDER BY consultation_local_date DESC, created_at DESC"
    )
    params: list[object] = [profile_id]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return [_row_to_reading(row) for row in conn.execute(sql, params).fetchall()]


def create_prepared(
    conn: sqlite3.Connection,
    *,
    profile_id: str,
    consultation_local_date: str,
    consultation_local_timestamp: str,
    consultation_utc_timestamp: datetime,
    consultation_timezone: str,
) -> Reading:
    """Open today's reading, or return the existing one.

    Callers do not need to check `get_today` first: a concurrent creation
    is resolved by letting the `UNIQUE` constraint fire and reading back
    whichever row won - see the module docstring.
    """
    reading_id = str(uuid.uuid4())
    now = consultation_utc_timestamp.isoformat()
    try:
        conn.execute(
            """
            INSERT INTO readings (
                id, profile_id, consultation_local_date, consultation_local_timestamp,
                consultation_utc_timestamp, consultation_timezone, status,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reading_id,
                profile_id,
                consultation_local_date,
                consultation_local_timestamp,
                now,
                consultation_timezone,
                ReadingStatus.PREPARED.value,
                now,
                now,
            ),
        )
    except sqlite3.IntegrityError:
        existing = get_today(conn, profile_id, consultation_local_date)
        if existing is None:
            raise  # some other integrity failure - not the daily-uniqueness race
        return existing

    created = _get_by_id(conn, reading_id)
    assert created is not None
    return created


def _advance(
    conn: sqlite3.Connection,
    reading_id: str,
    to_status: ReadingStatus,
    now: datetime,
    **columns: str,
) -> Reading:
    current = _get_by_id(conn, reading_id)
    if current is None:
        raise ValueError(f"no reading with id {reading_id!r}")
    _check_transition(current.status, to_status)

    set_clauses = ["status = ?", "updated_at = ?"]
    values: list[str] = [to_status.value, now.isoformat()]
    for column, value in columns.items():
        set_clauses.append(f"{column} = ?")
        values.append(value)
    values.append(reading_id)

    conn.execute(f"UPDATE readings SET {', '.join(set_clauses)} WHERE id = ?", values)

    updated = _get_by_id(conn, reading_id)
    assert updated is not None
    return updated


def commit_draw(conn: sqlite3.Connection, reading_id: str, draw: TarotDraw) -> Reading:
    return _advance(
        conn,
        reading_id,
        ReadingStatus.DRAWN,
        draw.drawn_at_utc,
        card_id=draw.card_id,
        card_drawn_at_utc=draw.drawn_at_utc.isoformat(),
        sortes_version=draw.sortes_version,
        entropy_digest=draw.entropy_digest,
    )


def commit_context(
    conn: sqlite3.Connection,
    reading_id: str,
    *,
    snapshot: TransitSnapshot,
    selected: list[RankedTransit],
    context: InterpretationContext,
    now: datetime,
) -> Reading:
    return _advance(
        conn,
        reading_id,
        ReadingStatus.CONTEXT_READY,
        now,
        astrology_policy_version=snapshot.astrology_policy_version,
        transit_snapshot_json=snapshot.model_dump_json(),
        selected_transits_json=_ranked_transits_adapter.dump_json(selected).decode("utf-8"),
        interpretation_context_json=context.model_dump_json(),
    )


def begin_interpreting(conn: sqlite3.Connection, reading_id: str, *, now: datetime) -> Reading:
    return _advance(conn, reading_id, ReadingStatus.INTERPRETING, now)


def complete_interpretation(
    conn: sqlite3.Connection,
    reading_id: str,
    result: InterpretationResult,
    *,
    now: datetime,
) -> Reading:
    return _advance(
        conn,
        reading_id,
        ReadingStatus.COMPLETE,
        now,
        provider_id=result.provider_id,
        model_id=result.model_id,
        prompt_version=result.prompt_version,
        interpretation_json=result.model_dump_json(),
    )


def fail_interpretation(conn: sqlite3.Connection, reading_id: str, *, now: datetime) -> Reading:
    return _advance(conn, reading_id, ReadingStatus.INTERPRETATION_FAILED, now)
