"""The bundled knowledge index: citations and vectors, never source text.

Every install ships this (`src/syzygy/resources/knowledge/`), so a fresh
clone knows where each of the 78 cards is discussed in all three sources
without anyone having to obtain a PDF first. What it deliberately does
*not* ship is the passages themselves - see
`docs/adr/0003-ship-derived-knowledge-index-without-source-text.md`.

Two files, on purpose:

- `index.json` - sorted, human-readable, diffable. A reviewer can open it
  and confirm at a glance that there is no prose in it. Given the
  redistribution question this artifact exists to answer, being auditable
  matters more than being compact.
- `vectors.npy` - a `float32` matrix, one unit-length row per chunk in
  `index.json` order.

## What this does and does not enable

Loaded into a fresh database, this makes structural lookup
(`retrieve_for_card`) and vector search work: a reading can say *where*
its card is discussed. It does **not** put source passages in front of the
model - there is no text to put there, and a citation with no text under a
"SOURCE PASSAGES" heading is an invitation to fabricate the contents
(`docs/old/DESIGN.md` section 23: never imply Crowley grounding that was not
retrieved). `reading_service` therefore filters textless chunks out of the
interpretation context, and a user who wants grounded readings still runs
`syzygy knowledge ingest` against their own copy of the books.

## Reproducibility

`build_artifact` is deterministic given the same PDFs and the same
`INGESTION_VERSIONS`/`VECTOR_VERSION`: ids are derived from content rather
than `uuid4`, chunks are emitted in a fixed order, and the JSON is written
with sorted keys. `tests/knowledge/test_artifact.py` asserts a rebuild is
byte-identical, so the committed file can be audited against its inputs.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from io import BytesIO
from pathlib import Path
from typing import Any, Final

import numpy as np

from syzygy.domain.knowledge import KnowledgeChunk, KnowledgeSource
from syzygy.knowledge.embedding import DIMENSIONS, VECTOR_VERSION, lexical_vector

ARTIFACT_VERSION: Final = "knowledge-artifact-v1"

#: Where the artifact lives inside the package, and inside the repo.
RESOURCE_PACKAGE: Final = "syzygy.resources"
INDEX_RESOURCE: Final = "knowledge/index.json"
VECTORS_RESOURCE: Final = "knowledge/vectors.npy"


class ArtifactError(RuntimeError):
    """The bundled artifact is missing, unreadable, or inconsistent."""


@dataclass(frozen=True)
class ArtifactChunk:
    """One chunk's citation - everything about a passage except the
    passage."""

    id: str
    source_type: str
    section_id: str
    section_type: str
    card_id: str | None
    title: str
    page_start: int
    page_end: int
    chunk_index: int
    text_hash: str
    word_count: int

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_type": self.source_type,
            "section_id": self.section_id,
            "section_type": self.section_type,
            "card_id": self.card_id,
            "title": self.title,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "chunk_index": self.chunk_index,
            "text_hash": self.text_hash,
            "word_count": self.word_count,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> ArtifactChunk:
        return cls(
            id=raw["id"],
            source_type=raw["source_type"],
            section_id=raw["section_id"],
            section_type=raw["section_type"],
            card_id=raw["card_id"],
            title=raw["title"],
            page_start=raw["page_start"],
            page_end=raw["page_end"],
            chunk_index=raw["chunk_index"],
            text_hash=raw["text_hash"],
            word_count=raw["word_count"],
        )


@dataclass(frozen=True)
class ArtifactSource:
    id: str
    source_type: str
    title: str
    file_hash: str
    ingestion_version: str

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_type": self.source_type,
            "title": self.title,
            "file_hash": self.file_hash,
            "ingestion_version": self.ingestion_version,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> ArtifactSource:
        return cls(
            id=raw["id"],
            source_type=raw["source_type"],
            title=raw["title"],
            file_hash=raw["file_hash"],
            ingestion_version=raw["ingestion_version"],
        )


@dataclass(frozen=True)
class Artifact:
    sources: tuple[ArtifactSource, ...]
    chunks: tuple[ArtifactChunk, ...]
    vectors: np.ndarray

    def __post_init__(self) -> None:
        if self.vectors.shape != (len(self.chunks), DIMENSIONS):
            raise ArtifactError(
                f"vector matrix {self.vectors.shape} does not match "
                f"{len(self.chunks)} chunks x {DIMENSIONS} dimensions"
            )

    def index_json(self) -> str:
        """The `index.json` payload. Sorted and newline-terminated so a
        rebuild is byte-identical and a diff is readable."""
        payload = {
            "artifact_version": ARTIFACT_VERSION,
            "vector_version": VECTOR_VERSION,
            "dimensions": DIMENSIONS,
            "sources": [source.to_json() for source in self.sources],
            "chunks": [chunk.to_json() for chunk in self.chunks],
        }
        return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    def vectors_bytes(self) -> bytes:
        buffer = BytesIO()
        np.save(buffer, self.vectors, allow_pickle=False)
        return buffer.getvalue()


#: Headings longer than this are almost certainly not headings. The
#: segmenters occasionally take a run-on line as a section title, and a
#: sentence of Crowley's prose in a redistributed file is exactly what
#: this artifact exists to avoid.
_MAX_TITLE_LENGTH: Final = 80


def normalize_title(title: str) -> str:
    """A heading, guaranteed to be heading-shaped.

    Collapses whitespace, then - if the result is too long to be a
    heading - keeps the trailing `/`-separated part, which is where the
    segmenter puts the real heading when it has swept up preceding prose
    with it. Failing that, truncates.
    """
    collapsed = " ".join(title.split())
    if len(collapsed) <= _MAX_TITLE_LENGTH:
        return collapsed
    tail = collapsed.rsplit("/", 1)[-1].strip()
    if tail and len(tail) <= _MAX_TITLE_LENGTH:
        return tail
    return collapsed[: _MAX_TITLE_LENGTH - 1].rstrip() + "…"


def _deterministic_id(*parts: str) -> str:
    """A stable id derived from content.

    `ingest` uses `uuid4`, which is fine for a local database but would
    make the committed artifact differ on every rebuild.
    """
    digest = hashlib.blake2b("\x1f".join(parts).encode("utf-8"), digest_size=16)
    return digest.hexdigest()


# -- building -------------------------------------------------------------


def build_artifact(conn: sqlite3.Connection) -> Artifact:
    """Derive the artifact from an already-ingested database.

    The caller is expected to have run `syzygy.knowledge.ingest` against
    the real PDFs first; this reads the chunk text only to hash it and to
    compute its vector, and never copies it into the result.
    """
    source_rows = conn.execute(
        "SELECT * FROM knowledge_sources ORDER BY source_type"
    ).fetchall()
    if not source_rows:
        raise ArtifactError("no ingested sources: run `syzygy knowledge ingest` first")

    sources: list[ArtifactSource] = []
    chunks: list[ArtifactChunk] = []
    vectors: list[np.ndarray] = []

    for source_row in source_rows:
        source_type = source_row["source_type"]
        sources.append(
            ArtifactSource(
                id=_deterministic_id("source", source_type, source_row["file_hash"]),
                source_type=source_type,
                title=source_row["title"],
                file_hash=source_row["file_hash"],
                ingestion_version=source_row["ingestion_version"],
            )
        )
        chunk_rows = conn.execute(
            """
            SELECT * FROM knowledge_chunks
            WHERE source_id = ?
            ORDER BY section_id, chunk_index
            """,
            (source_row["id"],),
        ).fetchall()
        for chunk_row in chunk_rows:
            text = chunk_row["text"]
            chunks.append(
                ArtifactChunk(
                    id=_deterministic_id(
                        "chunk", source_type, chunk_row["section_id"],
                        str(chunk_row["chunk_index"]),
                    ),
                    source_type=source_type,
                    section_id=chunk_row["section_id"],
                    section_type=chunk_row["section_type"],
                    card_id=chunk_row["card_id"],
                    title=normalize_title(chunk_row["title"]),
                    page_start=chunk_row["page_start"],
                    page_end=chunk_row["page_end"],
                    chunk_index=chunk_row["chunk_index"],
                    text_hash=chunk_row["text_hash"],
                    word_count=len(text.split()),
                )
            )
            vectors.append(lexical_vector(text))

    matrix = (
        np.vstack(vectors).astype(np.float32)
        if vectors
        else np.zeros((0, DIMENSIONS), dtype=np.float32)
    )
    return Artifact(sources=tuple(sources), chunks=tuple(chunks), vectors=matrix)


def write_artifact(artifact: Artifact, directory: Path) -> tuple[Path, Path]:
    """Write `index.json` and `vectors.npy` into `directory`."""
    directory.mkdir(parents=True, exist_ok=True)
    index_path = directory / "index.json"
    vectors_path = directory / "vectors.npy"
    index_path.write_text(artifact.index_json(), encoding="utf-8")
    vectors_path.write_bytes(artifact.vectors_bytes())
    return index_path, vectors_path


# -- loading --------------------------------------------------------------


def parse_artifact(index_json: str, vectors_bytes: bytes) -> Artifact:
    raw = json.loads(index_json)
    if raw.get("artifact_version") != ARTIFACT_VERSION:
        raise ArtifactError(
            f"artifact version {raw.get('artifact_version')!r} is not {ARTIFACT_VERSION!r}"
        )
    if raw.get("vector_version") != VECTOR_VERSION:
        # A vector built by a different scheme cannot be compared against
        # a query vector built by this one - silently mixing them would
        # produce plausible-looking nonsense rankings.
        raise ArtifactError(
            f"artifact vectors are {raw.get('vector_version')!r}, "
            f"this build computes {VECTOR_VERSION!r}"
        )
    vectors = np.load(BytesIO(vectors_bytes), allow_pickle=False)
    return Artifact(
        sources=tuple(ArtifactSource.from_json(item) for item in raw["sources"]),
        chunks=tuple(ArtifactChunk.from_json(item) for item in raw["chunks"]),
        vectors=vectors.astype(np.float32),
    )


def load_bundled_artifact() -> Artifact | None:
    """The artifact shipped inside the package, or `None` if this build
    does not carry one.

    Read through `importlib.resources`, so it works from a zipped wheel.
    A missing artifact is not an error: the knowledge base is optional
    and the ritual runs without it.
    """
    try:
        package_files = resources.files(RESOURCE_PACKAGE)
        index_json = package_files.joinpath(INDEX_RESOURCE).read_text(encoding="utf-8")
        vectors_bytes = package_files.joinpath(VECTORS_RESOURCE).read_bytes()
    except (FileNotFoundError, OSError):
        return None
    return parse_artifact(index_json, vectors_bytes)


# -- installing into a database -------------------------------------------


@dataclass(frozen=True)
class InstallResult:
    #: Source types whose citations were written into the database.
    installed: tuple[str, ...] = ()
    #: Source types already present, and therefore left untouched.
    skipped: tuple[str, ...] = ()
    chunk_count: int = 0


def install_artifact(
    conn: sqlite3.Connection, artifact: Artifact, *, now: datetime
) -> InstallResult:
    """Populate `knowledge_sources`/`knowledge_chunks` from `artifact`.

    Chunks are inserted with **empty text**: the artifact carries none.
    A `source_type` that already exists in this database is left alone,
    so locally ingested full text is never replaced by citations - the
    real thing always wins over the shipped index.
    """
    from syzygy.knowledge.store import get_source_by_type

    installed: list[str] = []
    skipped: list[str] = []
    inserted = 0

    conn.execute("BEGIN")
    try:
        for source in artifact.sources:
            if get_source_by_type(conn, source.source_type) is not None:
                skipped.append(source.source_type)
                continue
            conn.execute(
                """
                INSERT INTO knowledge_sources
                    (id, source_type, title, file_hash, ingestion_version, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    source.id,
                    source.source_type,
                    source.title,
                    source.file_hash,
                    source.ingestion_version,
                    now.isoformat(),
                ),
            )
            rows = [
                (
                    chunk.id,
                    source.id,
                    chunk.section_id,
                    chunk.section_type,
                    chunk.card_id,
                    chunk.title,
                    chunk.page_start,
                    chunk.page_end,
                    chunk.chunk_index,
                    "",  # no text: that is the whole point of this artifact
                    chunk.text_hash,
                    artifact.vectors[position].tobytes(),
                    VECTOR_VERSION,
                    chunk.word_count,
                )
                for position, chunk in enumerate(artifact.chunks)
                if chunk.source_type == source.source_type
            ]
            conn.executemany(
                """
                INSERT INTO knowledge_chunks
                    (id, source_id, section_id, section_type, card_id, title,
                     page_start, page_end, chunk_index, text, text_hash,
                     vector, vector_version, word_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            inserted += len(rows)
            installed.append(source.source_type)
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")

    return InstallResult(
        installed=tuple(installed), skipped=tuple(skipped), chunk_count=inserted
    )


def ensure_knowledge_base(conn: sqlite3.Connection, *, now: datetime) -> InstallResult:
    """Install the bundled artifact for any source this database has never
    seen. Safe and cheap to call on every launch: an install that has
    everything already does one query per source and no writes."""
    artifact = load_bundled_artifact()
    if artifact is None:
        return InstallResult(installed=(), skipped=())
    return install_artifact(conn, artifact, now=now)


# -- reading back ---------------------------------------------------------


def chunk_vectors(conn: sqlite3.Connection) -> tuple[list[str], np.ndarray]:
    """Every chunk id that has a current-version vector, and the matching
    matrix. Chunks vectorised under an older `VECTOR_VERSION` are skipped
    rather than compared against incompatible query vectors."""
    rows = conn.execute(
        """
        SELECT id, vector FROM knowledge_chunks
        WHERE vector IS NOT NULL AND vector_version = ?
        ORDER BY id
        """,
        (VECTOR_VERSION,),
    ).fetchall()
    if not rows:
        return [], np.zeros((0, DIMENSIONS), dtype=np.float32)
    ids = [row["id"] for row in rows]
    matrix = np.vstack(
        [np.frombuffer(row["vector"], dtype=np.float32) for row in rows]
    ).astype(np.float32)
    return ids, matrix


def source_chunks(artifact: Artifact, source_type: str) -> list[ArtifactChunk]:
    return [chunk for chunk in artifact.chunks if chunk.source_type == source_type]


def as_domain_source(source: ArtifactSource, *, now: datetime) -> KnowledgeSource:
    return KnowledgeSource(
        id=source.id,
        source_type=source.source_type,
        title=source.title,
        file_hash=source.file_hash,
        ingestion_version=source.ingestion_version,
        created_at_utc=now,
    )


def as_domain_chunk(chunk: ArtifactChunk, source_id: str) -> KnowledgeChunk:
    """The citation as a `KnowledgeChunk` with empty text - what a
    citation-only row looks like once it is in the database."""
    return KnowledgeChunk(
        id=chunk.id,
        source_id=source_id,
        section_id=chunk.section_id,
        section_type=chunk.section_type,
        card_id=chunk.card_id,
        title=chunk.title,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        chunk_index=chunk.chunk_index,
        text="",
        text_hash=chunk.text_hash,
    )
