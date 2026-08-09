"""What the knowledge base actually holds, per source (M18.1d).

One answer, read by three callers that used to each work it out from
`get_source_by_type` plus an ad-hoc `SELECT`: `syzygy doctor`, `syzygy
knowledge status`, and the interface's source-material screen. That
mattered because the states are easy to conflate and one of them is
routinely misread as a fault:

- `ABSENT` - no row at all. Only reachable on a build with no bundled
  artifact.
- `CITATIONS_ONLY` - **the normal state.** Every install ships citations
  for all three sources and none of their prose (ADR 0003), so this is
  what a healthy machine looks like until its owner ingests their own
  PDFs. It is not a shortfall and must never be reported as one.
- `FULL_TEXT` - the passages are here and reach readings.
- `BROKEN` - a row exists but cannot do its job: no chunks, no card
  sections mapped, or ingested by a version of the segmenter this build
  no longer agrees with. This is the only state worth acting on urgently,
  and separating it from `CITATIONS_ONLY` is the whole point of the
  module.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from syzygy.domain.knowledge import tier_for_source_type
from syzygy.knowledge.ingest import EXPECTED_FILENAMES, INGESTION_VERSIONS, SOURCE_TYPES
from syzygy.settings import KNOWLEDGE_SECTION, load_section, save_section

_NOTE_DISMISSED_KEY = "source_note_dismissed"


class SourceState(StrEnum):
    ABSENT = "absent"
    CITATIONS_ONLY = "citations_only"
    FULL_TEXT = "full_text"
    BROKEN = "broken"


@dataclass(frozen=True)
class SourceStatus:
    source_type: str
    tier: int
    title: str
    state: SourceState
    chunk_count: int
    text_chunk_count: int
    card_count: int
    ingestion_version: str | None
    expected_filename: str
    #: Why it is `BROKEN`, in a sentence a person can act on. `None` for
    #: every other state - there is nothing to explain about them.
    detail: str | None = None

    @property
    def has_text(self) -> bool:
        return self.state is SourceState.FULL_TEXT


def source_statuses(conn: sqlite3.Connection) -> list[SourceStatus]:
    """Every known source, canonical first, in one pass."""
    return [_status_for(conn, source_type) for source_type in SOURCE_TYPES]


def any_full_text(statuses: list[SourceStatus]) -> bool:
    """Whether a reading on this install can carry passages at all."""
    return any(status.has_text for status in statuses)


def broken(statuses: list[SourceStatus]) -> list[SourceStatus]:
    return [status for status in statuses if status.state is SourceState.BROKEN]


def source_note_dismissed(settings_path: Path | None) -> bool:
    """Whether the user has told home to stop mentioning this (M18.1d).

    A citation-only install is a supported state, so the note is a
    one-time piece of information rather than a warning to be nagged with.
    No settings file means nobody has expressed a preference, which is
    the same as not dismissed.
    """
    if settings_path is None:
        return False
    return bool(load_section(settings_path, KNOWLEDGE_SECTION).get(_NOTE_DISMISSED_KEY))


def set_source_note_dismissed(settings_path: Path, dismissed: bool) -> None:
    section = dict(load_section(settings_path, KNOWLEDGE_SECTION))
    section[_NOTE_DISMISSED_KEY] = dismissed
    save_section(settings_path, KNOWLEDGE_SECTION, section)


def _status_for(conn: sqlite3.Connection, source_type: str) -> SourceStatus:
    from syzygy.knowledge.store import get_source_by_type

    expected_filename = EXPECTED_FILENAMES.get(source_type, f"{source_type}.pdf")
    tier = tier_for_source_type(source_type)

    source = get_source_by_type(conn, source_type)
    if source is None:
        return SourceStatus(
            source_type=source_type,
            tier=tier,
            title=source_type,
            state=SourceState.ABSENT,
            chunk_count=0,
            text_chunk_count=0,
            card_count=0,
            ingestion_version=None,
            expected_filename=expected_filename,
        )

    row = conn.execute(
        """
        SELECT COUNT(*) AS chunks,
               COUNT(NULLIF(text, '')) AS text_chunks,
               COUNT(DISTINCT card_id) AS cards
        FROM knowledge_chunks WHERE source_id = ?
        """,
        (source.id,),
    ).fetchone()
    chunk_count = int(row["chunks"])
    text_chunk_count = int(row["text_chunks"])
    card_count = int(row["cards"])

    state, detail = _classify(
        source_type=source_type,
        ingestion_version=source.ingestion_version,
        chunk_count=chunk_count,
        text_chunk_count=text_chunk_count,
        card_count=card_count,
    )
    return SourceStatus(
        source_type=source_type,
        tier=tier,
        title=source.title,
        state=state,
        chunk_count=chunk_count,
        text_chunk_count=text_chunk_count,
        card_count=card_count,
        ingestion_version=source.ingestion_version,
        expected_filename=expected_filename,
        detail=detail,
    )


def _classify(
    *,
    source_type: str,
    ingestion_version: str,
    chunk_count: int,
    text_chunk_count: int,
    card_count: int,
) -> tuple[SourceState, str | None]:
    if chunk_count == 0:
        return SourceState.BROKEN, "the source is registered but has no chunks"
    if card_count == 0:
        return (
            SourceState.BROKEN,
            "no chunk was mapped to a card, so retrieval can never find this source",
        )
    current = INGESTION_VERSIONS.get(source_type)
    if current is not None and ingestion_version != current:
        return (
            SourceState.BROKEN,
            f"ingested at {ingestion_version}; this build segments at {current}, "
            f"so re-ingest the PDF",
        )
    if text_chunk_count == 0:
        return SourceState.CITATIONS_ONLY, None
    return SourceState.FULL_TEXT, None
