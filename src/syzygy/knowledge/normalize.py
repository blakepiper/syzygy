"""Page-aware PDF text extraction and boilerplate stripping.

One extraction strategy per source, per AGENTS.md's "per-source strategies,
not one universal parser" rule - the three sources have unrelated header/
footer/page-marker conventions:

- Book of Thoth (Tier 0): exact-string header/footer stripping and in-line
  `p.NNN` printed-page markers. docs/THOTH_INGESTION_MAP.md sections 4-5.
- DuQuette (Tier 1): position-based header stripping only (its OCR noise
  means the same running header extracts as a different string on
  different pages - exact-string matching does not work).
  docs/KNOWLEDGE_SOURCES.md section 3.1. No footer boilerplate was
  observed for this source.
- Ziegler (Tier 1): no repeated header/footer boilerplate was observed
  (docs/KNOWLEDGE_SOURCES.md section 4.1/4.4) - `extract_page_text` is a
  thin pass-through, since `segment.segment_ziegler` locates card sections
  by page range (from the book's own table of contents) rather than by
  in-page heading detection.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pymupdf

# A page whose stripped body text is shorter than this is assumed to be a
# non-prose page (card-artwork gallery, blank leaf) and is skipped rather
# than segmented - THOTH_INGESTION_MAP.md section 9.
MIN_PAGE_CHARS = 50


@dataclass(frozen=True)
class PageBlock:
    """One `get_text("blocks")` paragraph block, after boilerplate stripping."""

    text: str
    pdf_page: int  # 1-indexed
    printed_page: int | None  # None when not tracked for this source


# ---------------------------------------------------------------------------
# Book of Thoth (Tier 0)
# ---------------------------------------------------------------------------

_BOT_FOOTER_RE = re.compile(r"^file:///")
_BOT_PAGE_MARKER_RE = re.compile(r"^[Pp]\.\s?(\d{1,3})\.?$")
_BOT_NAV_BOILERPLATE = {"CONTENTS", "TOP OF THIS SECTION"}
_BOT_NAV_PREFIXES = ("PREVIOUS SECTION", "NEXT SECTION")


def extract_book_of_thoth_blocks(doc: pymupdf.Document) -> list[PageBlock]:
    """THOTH_INGESTION_MAP.md sections 4-5, 9, 12 (steps 3-4).

    Drops the first block of every page (repeated section header) and the
    last block matching `^file:///` (repeated footer, verified 100% of
    pages in that document). Skips pages whose remaining text is under
    `MIN_PAGE_CHARS` (card-artwork gallery pages). Attaches the nearest
    preceding in-line `p.NNN` printed-page marker to every following block
    as real book-page provenance.
    """
    blocks: list[PageBlock] = []
    printed_page: int | None = None
    for page_index in range(doc.page_count):
        raw_blocks = doc[page_index].get_text("blocks")
        if not raw_blocks:
            continue
        body = list(raw_blocks[1:])  # drop header: always the first block
        if body and _BOT_FOOTER_RE.match(body[-1][4].strip()):
            body = body[:-1]
        if sum(len(b[4]) for b in body) < MIN_PAGE_CHARS:
            continue  # image-gallery / boilerplate-only page
        for b in body:
            text = b[4].strip()
            if not text:
                continue
            marker = _BOT_PAGE_MARKER_RE.match(text)
            if marker:
                printed_page = int(marker.group(1))
                continue
            if text in _BOT_NAV_BOILERPLATE or text.startswith(_BOT_NAV_PREFIXES):
                continue
            blocks.append(PageBlock(text=text, pdf_page=page_index + 1, printed_page=printed_page))
    return blocks


# ---------------------------------------------------------------------------
# DuQuette companion (Tier 1)
# ---------------------------------------------------------------------------


def extract_duquette_blocks(doc: pymupdf.Document) -> list[PageBlock]:
    """docs/KNOWLEDGE_SOURCES.md section 3.1.

    The running header OCRs differently on different pages, so it is
    stripped *by position* (always the first block of the page) rather
    than by string match. No footer boilerplate was observed for this
    source. Printed-book page numbers are not tracked here - the OCR noise
    makes them unreliable to extract; chunks from this source carry PDF
    page numbers as their provenance instead (see `segment.py`).
    """
    blocks: list[PageBlock] = []
    for page_index in range(doc.page_count):
        raw_blocks = doc[page_index].get_text("blocks")
        if not raw_blocks:
            continue
        body = list(raw_blocks[1:])  # drop header: always the first block
        if sum(len(b[4]) for b in body) < MIN_PAGE_CHARS:
            continue  # image-only page (e.g. PDF page 81 - zero characters)
        for b in body:
            text = b[4].strip()
            if text:
                blocks.append(PageBlock(text=text, pdf_page=page_index + 1, printed_page=None))
    return blocks


# ---------------------------------------------------------------------------
# Ziegler companion (Tier 1)
# ---------------------------------------------------------------------------


def extract_page_text(doc: pymupdf.Document, pdf_page: int) -> str:
    """Plain per-page text, 1-indexed. Ziegler's text layer extracts cleanly
    (docs/KNOWLEDGE_SOURCES.md section 4.1) - no stripping needed here;
    `segment.segment_ziegler` locates section boundaries by page range."""
    return doc[pdf_page - 1].get_text()
