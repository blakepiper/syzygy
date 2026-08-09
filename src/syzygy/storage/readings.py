"""State-machine-respecting reading storage (docs/old/IMPLEMENTATION_PLAN.md §4.2).

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
from syzygy.domain.knowledge import RetrievedCitation
from syzygy.domain.reading import ALLOWED_TRANSITIONS, Reading, ReadingStatus
from syzygy.domain.tarot import TarotDraw

_ranked_transits_adapter = TypeAdapter(list[RankedTransit])
_citations_adapter = TypeAdapter(list[RetrievedCitation])


class IllegalReadingTransition(Exception):
    """A caller attempted a transition absent from `ALLOWED_TRANSITIONS`."""

    def __init__(self, current: ReadingStatus, requested: ReadingStatus) -> None:
        super().__init__(f"cannot transition reading from {current!r} to {requested!r}")
        self.current = current
        self.requested = requested


class ReadingDateArchivedError(Exception):
    """A deleted daily reading may not be replaced with a new draw."""


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

    # A reading committed before migration 6 has no citations column value
    # at all. That is an older reading, not a broken one - it reopens with
    # an empty list, exactly as a reading whose retrieval found nothing.
    retrieved_citations: list[RetrievedCitation] = []
    if row["retrieved_citations_json"] is not None:
        retrieved_citations = _citations_adapter.validate_json(row["retrieved_citations_json"])

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
        retrieved_citations=retrieved_citations,
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


def date_was_deleted(conn: sqlite3.Connection, profile_id: str, local_date: str) -> bool:
    """Whether this profile/date once had a reading removed from the archive."""
    return (
        conn.execute(
            "SELECT 1 FROM deleted_reading_dates "
            "WHERE profile_id = ? AND consultation_local_date = ?",
            (profile_id, local_date),
        ).fetchone()
        is not None
    )


def delete_from_archive(
    conn: sqlite3.Connection, reading_id: str, *, profile_id: str, deleted_at: datetime
) -> bool:
    """Delete one daily reading while permanently preserving its occupied date.

    The tombstone and deletion are one transaction. The migration-10 trigger
    then makes a later replacement impossible at the database boundary, so
    removing archive history can never become a production reroll path.
    """
    row = conn.execute(
        "SELECT consultation_local_date FROM readings WHERE id = ? AND profile_id = ?",
        (reading_id, profile_id),
    ).fetchone()
    if row is None:
        return False
    conn.execute("BEGIN")
    try:
        conn.execute(
            "INSERT OR IGNORE INTO deleted_reading_dates "
            "(profile_id, consultation_local_date, deleted_at) VALUES (?, ?, ?)",
            (profile_id, row["consultation_local_date"], deleted_at.isoformat()),
        )
        deleted = conn.execute(
            "DELETE FROM readings WHERE id = ? AND profile_id = ?",
            (reading_id, profile_id),
        ).rowcount
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
    return deleted == 1


def list_readings(
    conn: sqlite3.Connection, profile_id: str, *, limit: int | None = None
) -> list[Reading]:
    """One profile's readings, most recent local date first.

    The archive's list view (Milestone 5) needs only this much; the
    frequency/statistics queries in docs/old/DESIGN.md section 15 are Milestone 8.
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


def card_frequency(conn: sqlite3.Connection, profile_id: str) -> dict[str, int]:
    """`card_id` -> number of this profile's readings that drew it.

    Descriptive counts only (docs/old/DESIGN.md section 15) - no statistical framing
    is added here or implied by the ordering. Any reading past `DRAWN` has
    a committed `card_id`, regardless of whether interpretation ever
    succeeded, so a card that was drawn still counts even if the model
    call failed. Ordered most-frequent-first, `card_id` ascending to break
    ties, so callers get a stable, deterministic ordering.
    """
    rows = conn.execute(
        "SELECT card_id, COUNT(*) AS n FROM readings "
        "WHERE profile_id = ? AND card_id IS NOT NULL "
        "GROUP BY card_id ORDER BY n DESC, card_id ASC",
        (profile_id,),
    ).fetchall()
    return {row["card_id"]: row["n"] for row in rows}


def suit_frequency(conn: sqlite3.Connection, profile_id: str) -> dict[str, int]:
    """Suit label (`"major"` or a `Suit` value) -> reading count.

    The `readings` table has no `suit` column - only `card_id` - so this
    re-buckets `card_frequency`'s per-card counts using the deck's static
    suit metadata (`syzygy.sortes.deck.get_card`) rather than adding a
    denormalized column. Ordered most-frequent-first, label ascending to
    break ties.
    """
    from syzygy.sortes.deck import get_card

    totals: dict[str, int] = {}
    for card_id, count in card_frequency(conn, profile_id).items():
        card = get_card(card_id)
        label = card.suit.value if card.suit is not None else "major"
        totals[label] = totals.get(label, 0) + count
    return dict(sorted(totals.items(), key=lambda item: (-item[1], item[0])))


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
    if date_was_deleted(conn, profile_id, consultation_local_date):
        raise ReadingDateArchivedError(
            "this date's reading was deleted from the archive; its card remains final"
        )

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
    citations: list[RetrievedCitation] | None = None,
    now: datetime,
) -> Reading:
    """Commit the reading's inputs.

    `context` is what the provider will be given; `citations` is what
    retrieval found, which is a superset and is stored separately on
    purpose (M18.1a) - a citation whose passage is not installed belongs
    in front of the user and must never reach a prompt.
    """
    return _advance(
        conn,
        reading_id,
        ReadingStatus.CONTEXT_READY,
        now,
        astrology_policy_version=snapshot.astrology_policy_version,
        transit_snapshot_json=snapshot.model_dump_json(),
        selected_transits_json=_ranked_transits_adapter.dump_json(selected).decode("utf-8"),
        interpretation_context_json=context.model_dump_json(),
        retrieved_citations_json=_citations_adapter.dump_json(citations or []).decode("utf-8"),
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
