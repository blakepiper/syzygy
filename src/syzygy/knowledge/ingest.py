"""Ingestion pipeline orchestration: PDF -> segmented sections -> chunks ->
`knowledge_sources`/`knowledge_chunks` rows.

Idempotent: re-running `ingest()` against the same file (same SHA-256) at
the same `INGESTION_VERSIONS[source_type]` is a no-op. Bump the relevant
entry in `INGESTION_VERSIONS` whenever `normalize.py`/`segment.py` change
that source's segmentation/chunking logic, so the next `ingest()` call is
recognized as needing a re-ingest rather than being skipped.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pymupdf

from syzygy.domain.knowledge import KnowledgeChunk, KnowledgeSource
from syzygy.knowledge.segment import (
    Section,
    segment_book_of_thoth,
    segment_duquette,
    segment_ziegler,
)
from syzygy.knowledge.store import get_source_by_type, has_full_text, replace_source

if TYPE_CHECKING:
    import sqlite3

# docs/old/DESIGN.md section 11.3 step 5: "roughly 600-1,200 tokens". Token counts
# are approximated as word counts (close enough for a chunk-size target;
# no tokenizer dependency is worth adding for this).
_TARGET_WORDS_MAX = 900

SOURCE_TYPES = ("book_of_thoth", "duquette_companion", "ziegler_mirror_of_soul")

INGESTION_VERSIONS: dict[str, str] = {
    "book_of_thoth": "v1",
    "duquette_companion": "v1",
    "ziegler_mirror_of_soul": "v1",
}

_TITLES: dict[str, str] = {
    "book_of_thoth": "The Book of Thoth",
    "duquette_companion": "Understanding Aleister Crowley's Thoth Tarot",
    "ziegler_mirror_of_soul": "Tarot: Mirror of the Soul",
}

# docs/KNOWLEDGE_SOURCES.md section 2 (source registry) file names.
_FILENAME_HINTS: dict[str, str] = {
    "book_of_thoth": "book_of_thoth",
    "duquette_companion": "understanding_crowley_thoth_tarot",
    "ziegler_mirror_of_soul": "mirror_of_the_soul",
}

#: What each source's file is called in `docs/KNOWLEDGE_SOURCES.md`, for
#: an interface that has to tell someone what to go and find. A file named
#: anything else still ingests - `--source-type` exists for exactly that -
#: but these are the names auto-detection recognises.
EXPECTED_FILENAMES: dict[str, str] = {
    source_type: f"{hint}.pdf" for source_type, hint in _FILENAME_HINTS.items()
}


def default_source_paths(docs_dir: Path = Path("docs")) -> list[tuple[str, Path]]:
    """The complete, canonical no-argument ingest set.

    Keeping this mapping beside source detection prevents the CLI's convenient
    path from acquiring a second, drifting list of filenames or source types.
    """
    return [
        (source_type, docs_dir / EXPECTED_FILENAMES[source_type])
        for source_type in SOURCE_TYPES
    ]

_SEGMENTERS: dict[str, Callable[[pymupdf.Document], list[Section]]] = {
    "book_of_thoth": segment_book_of_thoth,
    "duquette_companion": segment_duquette,
    "ziegler_mirror_of_soul": segment_ziegler,
}


class UnknownSourceTypeError(ValueError):
    """Raised when a `source_type` can't be auto-detected or isn't recognized."""


class SourceFileMismatchError(ValueError):
    """The file offered is not the edition this build's citations describe."""


def known_file_hashes() -> dict[str, str]:
    """`source_type -> sha256` for the editions this build knows.

    Read from the shipped artifact rather than restated here, so there is
    exactly one record of which file each citation's page numbers refer to
    (`docs/KNOWLEDGE_SOURCES.md` section 2 documents the same hashes; the
    artifact is what was actually built from them). A build with no
    artifact knows no hashes, and `verify_known_source_file` says so
    rather than waving an unverifiable file through.
    """
    from syzygy.knowledge.artifact import load_bundled_artifact

    try:
        artifact = load_bundled_artifact()
    except Exception:  # noqa: BLE001 - an unparseable artifact knows nothing
        return {}
    if artifact is None:
        return {}
    return {source.source_type: source.file_hash for source in artifact.sources}


def verify_known_source_file(path: Path, *, source_type: str | None = None) -> tuple[str, str]:
    """`(source_type, sha256)` for a file that is the edition we expect.

    Raises `SourceFileMismatchError` otherwise. The interface uses this
    (M18.1c) because the page ranges in every shipped citation are that
    edition's pagination: ingesting a different scan under the same
    `source_type` would quietly make every "pages 106-110" in the app
    point somewhere else. `syzygy knowledge ingest` deliberately does not
    call it - the CLI stays the route for anyone who knows their copy
    differs and accepts what that means.
    """
    resolved = source_type or detect_source_type(path)
    if resolved not in _SEGMENTERS:
        raise UnknownSourceTypeError(
            f"unknown source_type {resolved!r} (expected one of {SOURCE_TYPES})"
        )
    expected = known_file_hashes().get(resolved)
    if expected is None:
        raise SourceFileMismatchError(
            f"this build ships no citations for {resolved!r}, so a file cannot be "
            f"checked against a known edition"
        )
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise SourceFileMismatchError(
            f"{path.name} is not the edition of {resolved!r} these citations describe "
            f"(sha256 {actual[:12]}…, expected {expected[:12]}…). Its page numbers "
            f"would not match. Use `syzygy knowledge ingest` if you accept that."
        )
    return resolved, actual


def detect_source_type(path: Path) -> str:
    stem = path.stem.lower()
    for source_type, hint in _FILENAME_HINTS.items():
        if hint in stem:
            return source_type
    raise UnknownSourceTypeError(
        f"cannot auto-detect source_type from filename {path.name!r}; "
        f"pass --source-type explicitly (one of {SOURCE_TYPES})"
    )


def _chunk_text(text: str) -> list[str]:
    """Greedy paragraph-boundary chunker. Never splits a paragraph, so a
    single very long paragraph can still exceed `_TARGET_WORDS_MAX` - that
    is an intentional trade-off against chunking mid-sentence."""
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return [text] if text.strip() else []

    chunks: list[str] = []
    current: list[str] = []
    current_words = 0
    for paragraph in paragraphs:
        words = len(paragraph.split())
        if current and current_words + words > _TARGET_WORDS_MAX:
            chunks.append("\n\n".join(current))
            current = []
            current_words = 0
        current.append(paragraph)
        current_words += words
    if current:
        chunks.append("\n\n".join(current))
    return chunks


@dataclass(frozen=True)
class IngestResult:
    source_type: str
    skipped: bool
    chunk_count: int
    card_count: int


def ingest(
    conn: sqlite3.Connection,
    pdf_path: Path,
    *,
    now: datetime,
    source_type: str | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> IngestResult:
    """Ingest one PDF. `on_progress` is called with a short phase label
    between the stages that take real time (hashing, opening, segmenting,
    storing) so a caller with a screen can say what is happening; a
    caller without one passes nothing and this behaves exactly as before.
    """
    report = on_progress or (lambda _phase: None)

    resolved_type = source_type or detect_source_type(pdf_path)
    if resolved_type not in _SEGMENTERS:
        raise UnknownSourceTypeError(
            f"unknown source_type {resolved_type!r} (expected one of {SOURCE_TYPES})"
        )

    report("hashing the file")
    file_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    version = INGESTION_VERSIONS[resolved_type]

    existing = get_source_by_type(conn, resolved_type)
    if (
        existing is not None
        and existing.file_hash == file_hash
        and existing.ingestion_version == version
        # ...and it actually has the passages. A source installed from the
        # bundled artifact (M13.3) records the same file hash and version
        # as a real ingest but carries citations only, so without this the
        # first thing a user does with their own PDF - ingest it - would
        # report "already ingested" and change nothing (M13.3c).
        and has_full_text(conn, existing.id)
    ):
        return IngestResult(source_type=resolved_type, skipped=True, chunk_count=0, card_count=0)

    report("reading the PDF")
    doc = pymupdf.open(pdf_path)
    try:
        report("segmenting into card sections")
        sections = _SEGMENTERS[resolved_type](doc)
    finally:
        doc.close()

    report("chunking")
    source_id = str(uuid.uuid4())
    chunks: list[KnowledgeChunk] = []
    card_ids: set[str] = set()
    for section in sections:
        if section.card_id is not None:
            card_ids.add(section.card_id)
        for chunk_index, chunk_text in enumerate(_chunk_text(section.text)):
            chunks.append(
                KnowledgeChunk(
                    id=str(uuid.uuid4()),
                    source_id=source_id,
                    section_id=section.section_id,
                    section_type=section.section_type,
                    card_id=section.card_id,
                    title=section.title,
                    page_start=section.page_start,
                    page_end=section.page_end,
                    chunk_index=chunk_index,
                    text=chunk_text,
                    text_hash=hashlib.sha256(chunk_text.encode("utf-8")).hexdigest(),
                )
            )

    source = KnowledgeSource(
        id=source_id,
        source_type=resolved_type,
        title=_TITLES[resolved_type],
        file_hash=file_hash,
        ingestion_version=version,
        created_at_utc=now,
    )
    report(f"storing {len(chunks)} chunks")
    replace_source(conn, source, chunks)
    return IngestResult(
        source_type=resolved_type,
        skipped=False,
        chunk_count=len(chunks),
        card_count=len(card_ids),
    )
