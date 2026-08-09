"""Heading detection: normalized page blocks -> card-scoped `Section`s.

One detector per source, per AGENTS.md's "per-source strategies" rule -
docs/THOTH_INGESTION_MAP.md section 8 (Book of Thoth) and
docs/KNOWLEDGE_SOURCES.md sections 3.2/4.2-4.3 (DuQuette, Ziegler) each
describe a different heading convention. A section never crosses a
detected heading boundary (docs/old/DESIGN.md section 11.3 step 5) - chunking
*within* a section is `ingest.py`'s job, not this module's.

Card mapping never uses fuzzy/semantic matching (docs/old/DESIGN.md section 11.3
step 4): Major Arcana headings are matched against
`TarotCard.book_of_thoth_aliases` (falling back to a small per-source
title-override table only for Ziegler's "The Priestess"/"The Magus"-style
variant titles - documented locally here, per `docs/old/IMPLEMENTATION_PLAN.md`
Milestone 6, rather than growing the canonical deck file with
non-canonical-source naming). Numbered Minor and Court cards need no
alias table at all - their headings already spell out `<rank> of <suit>`/
`<court> of <suit>`, so the card_id is reconstructed deterministically and
checked against `syzygy.sortes.deck.get_card` as a fail-fast sanity check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pymupdf

from syzygy.knowledge.normalize import (
    PageBlock,
    extract_book_of_thoth_blocks,
    extract_duquette_blocks,
    extract_page_text,
)
from syzygy.sortes.deck import get_card, load_deck

_RANK_WORDS: dict[int, str] = {
    1: "ace", 2: "two", 3: "three", 4: "four", 5: "five",
    6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
}
_SUITS = ("wands", "cups", "swords", "disks")
_COURTS = ("knight", "queen", "prince", "princess")


@dataclass(frozen=True)
class Section:
    """A single card-scoped (or card-class-scoped) region of source text."""

    section_id: str
    section_type: str  # "card" | "card_appendix"
    card_id: str | None
    title: str
    page_start: int
    page_end: int
    text: str


def _normalize_heading(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().upper()


def _rank_suit_card_id(rank_word: str, suit_word: str) -> str:
    card_id = f"{rank_word}_of_{suit_word}"
    get_card(card_id)  # fail fast if the naming assumption is ever wrong
    return card_id


def _court_suit_card_id(court_word: str, suit_word: str) -> str:
    card_id = f"{court_word}_of_{suit_word}"
    get_card(card_id)
    return card_id


def _build_major_alias_index(extra: dict[str, str] | None = None) -> dict[str, str]:
    """normalized alias/title text -> card_id, for the 22 Major Arcana."""
    index: dict[str, str] = {}
    for card in load_deck():
        if card.arcana != "major":
            continue
        for alias in card.book_of_thoth_aliases:
            index[_normalize_heading(alias)] = card.id
        index[_normalize_heading(card.display_name)] = card.id
    for title, card_id in (extra or {}).items():
        index[_normalize_heading(title)] = card_id
    return index


_SUIT_RE = "(WANDS|CUPS|SWORDS|DISKS)"
_COURT_RE = "(KNIGHT|QUEEN|PRINCE|PRINCESS)"
_RANK_WORD_RE = "(ACE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN)"

_COURT_HEADING_RE = re.compile(rf"^{_COURT_RE} OF {_SUIT_RE}$")
_RANK_HEADING_RE = re.compile(rf"^{_RANK_WORD_RE} OF {_SUIT_RE}$")
_NUMBERED_RANK_HEADING_RE = re.compile(
    rf"^(TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN) OF {_SUIT_RE}$"
)


def _rank_word_to_card_id(rank_word: str, suit_word: str) -> str:
    return _rank_suit_card_id(rank_word.lower(), suit_word.lower())


def _court_word_to_card_id(court_word: str, suit_word: str) -> str:
    return _court_suit_card_id(court_word.lower(), suit_word.lower())


# ---------------------------------------------------------------------------
# Book of Thoth (Tier 0)
# ---------------------------------------------------------------------------

# THOTH_INGESTION_MAP.md section 6: Parts Two-Four plus the six-trump
# appendix, i.e. exactly the per-card content. Front matter (1-26) and the
# non-card appendices (219+) are deliberately excluded - scanning them for
# heading-shaped text risks false positives against the book's own
# contents listing on pages 1-3.
_BOT_CARD_CONTENT_PAGE_RANGE = (27, 218)

_BOT_MAJOR_HEADING_RE = re.compile(r"^(0|[IVXL]+)\.\s*(.+)$")

# THOTH_INGESTION_MAP.md section 6: PDF pages 112-137 are a second,
# appendix-only essay "for six specific trumps" (The Fool, The Magus,
# Fortune, Lust, Art, The Universe). In practice this reads as one
# continuous, unsegmented philosophical essay (quoting Liber cordis
# material) that only touches those trumps' themes in passing - it does
# not carry six separate per-card headings the way the main text does.
# The only heading-shaped marker found in this range is the lead line
# "The Fool---i. Silence; ii. De Sapientia et Stultitia; ..." on PDF page
# 112 (a contents-style listing of the essay's own subsections, not a
# per-card split). Rather than force an artificial 6-way split this
# module cannot support with a real structural signal, the whole range is
# captured as a single `card_appendix` section anchored to the one card
# whose title *is* marked - `the_fool` - which correctly keeps it out of
# both `the_universe`'s primary section (ends at the prior heading) and
# `knight_of_wands`'s primary section (starts at the next one).
_BOT_APPENDIX_CARDS = ("the_fool",)
_BOT_APPENDIX_HEADING_RE = re.compile(r"^([A-Za-z ]{3,20})---")

_MAJOR_ALIAS_INDEX = _build_major_alias_index()


@dataclass(frozen=True)
class _Heading:
    block_index: int
    span: int  # number of consecutive blocks this heading itself occupies
    section_type: str
    card_id: str
    title: str


def _detect_book_of_thoth_headings(blocks: list[PageBlock]) -> list[_Heading]:
    appendix_titles = {
        _normalize_heading(get_card(cid).display_name): cid for cid in _BOT_APPENDIX_CARDS
    }
    headings: list[_Heading] = []
    i = 0
    while i < len(blocks):
        text = blocks[i].text.strip()

        major_match = _BOT_MAJOR_HEADING_RE.match(text)
        if major_match:
            remainder = _normalize_heading(major_match.group(2))
            card_id = next(
                (cid for alias, cid in _MAJOR_ALIAS_INDEX.items() if remainder.startswith(alias)),
                None,
            )
            if card_id is not None:
                headings.append(_Heading(i, 1, "card", card_id, text))
                i += 1
                continue

        appendix_match = _BOT_APPENDIX_HEADING_RE.match(text)
        if appendix_match:
            card_id = appendix_titles.get(_normalize_heading(appendix_match.group(1)))
            if card_id is not None:
                headings.append(_Heading(i, 1, "card_appendix", card_id, text))
                i += 1
                continue

        normalized = _normalize_heading(text)
        court_match = _COURT_HEADING_RE.match(normalized)
        if court_match and text.isupper():
            card_id = _court_word_to_card_id(court_match.group(1), court_match.group(2))
            headings.append(_Heading(i, 1, "card", card_id, text))
            i += 1
            continue

        rank_match = _RANK_HEADING_RE.match(normalized)
        if rank_match and text.isupper():
            card_id = _rank_word_to_card_id(rank_match.group(1), rank_match.group(2))
            headings.append(_Heading(i, 1, "card", card_id, text))
            i += 1
            continue

        # Two-line numbered-Minor heading: a short all-caps title block
        # immediately followed by the "<RANK> OF <SUIT>" block (Aces are
        # single-line - handled by _RANK_HEADING_RE above).
        if i + 1 < len(blocks):
            next_normalized = _normalize_heading(blocks[i + 1].text)
            next_match = _NUMBERED_RANK_HEADING_RE.match(next_normalized)
            if next_match and blocks[i + 1].text.isupper():
                card_id = _rank_word_to_card_id(next_match.group(1), next_match.group(2))
                headings.append(_Heading(i, 2, "card", card_id, f"{text} / {blocks[i + 1].text}"))
                i += 2
                continue

        i += 1
    return headings


def segment_book_of_thoth(doc: pymupdf.Document) -> list[Section]:
    all_blocks = extract_book_of_thoth_blocks(doc)
    lo, hi = _BOT_CARD_CONTENT_PAGE_RANGE
    blocks = [b for b in all_blocks if lo <= b.pdf_page <= hi]
    headings = _detect_book_of_thoth_headings(blocks)
    return _build_sections("book_of_thoth", blocks, headings)


def _build_sections(
    source_type: str, blocks: list[PageBlock], headings: list[_Heading]
) -> list[Section]:
    sections: list[Section] = []
    for n, heading in enumerate(headings):
        start = heading.block_index
        end = headings[n + 1].block_index if n + 1 < len(headings) else len(blocks)
        section_blocks = blocks[start:end]
        if not section_blocks:
            continue
        printed_pages = [b.printed_page for b in section_blocks if b.printed_page is not None]
        page_start = min(printed_pages) if printed_pages else section_blocks[0].pdf_page
        page_end = max(printed_pages) if printed_pages else section_blocks[-1].pdf_page
        sections.append(
            Section(
                section_id=f"{source_type}:{n:03d}:{heading.section_type}:{heading.card_id}",
                section_type=heading.section_type,
                card_id=heading.card_id,
                title=heading.title,
                page_start=page_start,
                page_end=page_end,
                text="\n\n".join(b.text for b in section_blocks),
            )
        )
    return sections


# ---------------------------------------------------------------------------
# DuQuette companion (Tier 1)
# ---------------------------------------------------------------------------

# docs/KNOWLEDGE_SOURCES.md section 3.2: verified via direct inspection to
# be PDF pages 275 ("CHAPTER TWENTY" / "Method of Divination and the
# Meaning of the Cards" running header first appears) through 290 (last
# page carrying that running header; 291 is "CHAPTER TWENTY-ONE", an
# unrelated glossary chapter). Excluded entirely from ingestion rather
# than mapped per-card: its compressed, noisier restatement of material
# already covered by the main per-card essays adds more retrieval noise
# than value for a Tier 1 source (docs/old/IMPLEMENTATION_PLAN.md Milestone 6
# explicitly allows this).
DUQUETTE_QUICK_REFERENCE_PAGES = (275, 290)

_DUQUETTE_MAJOR_ALIAS_INDEX = _build_major_alias_index()


def _detect_duquette_headings(blocks: list[PageBlock]) -> list[_Heading]:
    """Card headings share a block with an adjacent line (a Golden Dawn
    subtitle for Majors, e.g. "ATUO\\nTHE FOOL"; the card's Thoth title for
    numbered Minors, e.g. "TWO OF WANDS\\nDOMINION") rather than standing
    alone as their own block - check each line of a block individually,
    not the block's full joined text (docs/KNOWLEDGE_SOURCES.md section
    3.2 samples)."""
    headings: list[_Heading] = []
    for i, block in enumerate(blocks):
        for line in block.text.split("\n"):
            line = line.strip()
            if not line or not line.isupper():
                continue
            normalized = _normalize_heading(line)

            card_id = _DUQUETTE_MAJOR_ALIAS_INDEX.get(normalized)
            if card_id is not None:
                headings.append(_Heading(i, 1, "card", card_id, line))
                break

            court_match = _COURT_HEADING_RE.match(normalized)
            if court_match:
                card_id = _court_word_to_card_id(court_match.group(1), court_match.group(2))
                headings.append(_Heading(i, 1, "card", card_id, line))
                break

            rank_match = _RANK_HEADING_RE.match(normalized)
            if rank_match:
                card_id = _rank_word_to_card_id(rank_match.group(1), rank_match.group(2))
                headings.append(_Heading(i, 1, "card", card_id, line))
                break
    return headings


# Per-card essays run PDF pages 97 ("ATUO / THE FOOL", Chapter 14's first
# card) through 272 ("TEN OF DISKS"), per docs/KNOWLEDGE_SOURCES.md
# section 3.2's table. Earlier pages (front matter, and Tree-of-Life /
# attribution diagram captions at PDF pages 47 and 88-96 whose OCR'd text
# happens to consist of bare card-name-shaped words like "LUST", "ART",
# "DEATH") are excluded - without this bound those diagram fragments are
# indistinguishable from real headings and produce spurious extra
# sections for those cards.
_DUQUETTE_CARD_CONTENT_PAGE_RANGE = (97, 272)


def segment_duquette(doc: pymupdf.Document) -> list[Section]:
    content_lo, content_hi = _DUQUETTE_CARD_CONTENT_PAGE_RANGE
    quick_ref_lo, quick_ref_hi = DUQUETTE_QUICK_REFERENCE_PAGES
    blocks = [
        b
        for b in extract_duquette_blocks(doc)
        if content_lo <= b.pdf_page <= content_hi
        and not (quick_ref_lo <= b.pdf_page <= quick_ref_hi)
    ]
    headings = _detect_duquette_headings(blocks)
    return _build_sections("duquette_companion", blocks, headings)


# ---------------------------------------------------------------------------
# Ziegler companion (Tier 1)
# ---------------------------------------------------------------------------

# docs/KNOWLEDGE_SOURCES.md section 4.2: Ziegler's own table of contents
# (PDF pages 5-7) states every card's printed-book page number. Segment by
# that page range rather than by in-page heading detection, because many
# card sections have no extractable heading text at all - the card's
# title is embedded in a full-page illustration on the section's opening
# page (confirmed for e.g. Three of Cups, PDF page 125), not in the text
# layer.
_ZIEGLER_TOC_PAGES = (5, 7)
_ZIEGLER_TITLE_OVERRIDES = {"the_high_priestess": "The Priestess"}
_ZIEGLER_MAJOR_HEADING_RE = re.compile(r"^(0|O|[IVXL]+)\s+(.+)$")


def _ziegler_ordered_cards() -> list[tuple[str, str]]:
    """(card_id, title-as-printed-in-Ziegler), in the book's own order:
    Major Arcana (0-XXI), then Court Cards, then numbered Minor Arcana."""
    roman_order = [
        "0", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
        "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX",
        "XX", "XXI",
    ]
    majors = sorted(
        (c for c in load_deck() if c.arcana == "major"),
        key=lambda c: roman_order.index(c.roman_numeral or "0"),
    )
    ordered = [
        (c.id, _ZIEGLER_TITLE_OVERRIDES.get(c.id, c.display_name)) for c in majors
    ]
    for suit in _SUITS:
        for court in _COURTS:
            card_id = _court_suit_card_id(court, suit)
            ordered.append((card_id, f"{court.capitalize()} of {suit.capitalize()}"))
    for suit in _SUITS:
        for rank in range(1, 11):
            card_id = _rank_suit_card_id(_RANK_WORDS[rank], suit)
            ordered.append((card_id, f"{_RANK_WORDS[rank].capitalize()} of {suit.capitalize()}"))
    return ordered


def _parse_ziegler_toc_page_numbers(doc: pymupdf.Document, titles: list[str]) -> list[int]:
    """Extract the printed-book page number for each title, in order, from
    the TOC's own line structure (one title per line, immediately followed
    by its page-number line) - not a whitespace-collapsed substring
    search, which loses the line boundary that distinguishes a card's own
    page number from the *next* card's roman-numeral line bleeding into
    it. A rare font/cmap defect in this PDF renders some page-number
    digits as look-alike letters (e.g. printed page 111 extracts as the
    line "H I") - repaired here as a fixed, verified substitution
    (docs/KNOWLEDGE_SOURCES.md section 4.2 flags this as unverified;
    confirmed and repaired during Milestone 6 ingestion)."""
    lo, hi = _ZIEGLER_TOC_PAGES
    lines: list[str] = []
    for page_number in range(lo, hi + 1):
        for line in doc[page_number - 1].get_text().split("\n"):
            line = line.strip()
            if line:
                lines.append(line)
    normalized_lines = [_normalize_heading(line) for line in lines]

    page_numbers: list[int] = []
    cursor = 0
    for title in titles:
        target = _normalize_heading(title)
        idx = next(
            (i for i in range(cursor, len(normalized_lines)) if normalized_lines[i] == target),
            None,
        )
        if idx is None or idx + 1 >= len(lines):
            raise ValueError(f"Ziegler TOC: could not locate title {title!r}")
        repaired = lines[idx + 1].replace("H", "11").replace("I", "1").replace("O", "0")
        digits = re.sub(r"\D", "", repaired)
        if not digits:
            raise ValueError(
                f"Ziegler TOC: unparseable page number after {title!r}: {lines[idx + 1]!r}"
            )
        page_numbers.append(int(digits))
        cursor = idx + 2
    return page_numbers


def _find_ziegler_offset(
    doc: pymupdf.Document, cards: list[tuple[str, str]], page_numbers: list[int]
) -> int:
    """Cross-check the printed-page -> PDF-page offset against real
    in-body Major Arcana headings, rather than trusting a single
    hardcoded constant (docs/KNOWLEDGE_SOURCES.md section 4.2 gives ~7 as
    an estimate "from one data point")."""
    title_to_printed_page = {
        card_id: page_numbers[i] for i, (card_id, _title) in enumerate(cards)
    }
    offsets: set[int] = set()
    for page_index in range(doc.page_count):
        for block in doc[page_index].get_text("blocks"):
            text = block[4].strip().split("\n")[0].strip()
            match = _ZIEGLER_MAJOR_HEADING_RE.match(text)
            if not match:
                continue
            normalized = _normalize_heading(match.group(2))
            card_id = next(
                (cid for alias, cid in _MAJOR_ALIAS_INDEX.items() if normalized.startswith(alias)),
                None,
            )
            if card_id is None or card_id not in title_to_printed_page:
                continue
            offsets.add((page_index + 1) - title_to_printed_page[card_id])
    if not offsets:
        raise ValueError("Ziegler: could not cross-check any Major Arcana heading to derive offset")
    if len(offsets) > 1:
        raise ValueError(f"Ziegler: inconsistent printed-to-PDF page offsets found: {offsets}")
    return offsets.pop()


def _find_ziegler_anchor_page(doc: pymupdf.Document, heading_text: str) -> int:
    """First PDF page whose block starts with an exact (isupper) match of
    `heading_text` - used to anchor the Court/Minor arithmetic below."""
    target = _normalize_heading(heading_text)
    for page_index in range(doc.page_count):
        for block in doc[page_index].get_text("blocks"):
            first_line = block[4].strip().split("\n")[0].strip()
            if first_line.isupper() and _normalize_heading(first_line) == target:
                return page_index + 1
    raise ValueError(f"Ziegler: could not find anchor heading {heading_text!r}")


def segment_ziegler(doc: pymupdf.Document) -> list[Section]:
    all_cards = _ziegler_ordered_cards()
    majors = [c for c in all_cards if get_card(c[0]).arcana == "major"]
    courts = [c for c in all_cards if get_card(c[0]).court is not None]
    minors = [c for c in all_cards if get_card(c[0]).court is None and get_card(c[0]).rank]

    major_titles = [title for _card_id, title in majors]
    major_page_numbers = _parse_ziegler_toc_page_numbers(doc, major_titles)
    offset = _find_ziegler_offset(doc, majors, major_page_numbers)
    major_starts = {
        card_id: printed_page + offset
        for (card_id, _title), printed_page in zip(majors, major_page_numbers, strict=True)
    }

    # Court and numbered-Minor headings are not reliably present as
    # extractable text for every card (many card sections' titles are
    # embedded in a full-page illustration instead - confirmed e.g. for
    # Three of Cups, PDF page 125). But wherever a heading *is*
    # extractable, every card within each of these two groups sits
    # exactly 2 PDF pages after the previous one (verified directly
    # against 13/16 Court headings and the first 12/40 Minor headings) -
    # so a single real anchor plus that fixed step locates every card in
    # the group, without needing every individual heading to be present.
    court_anchor = _find_ziegler_anchor_page(doc, "KNIGHT OF WANDS")
    minor_anchor = _find_ziegler_anchor_page(doc, "ACE OF WANDS")
    court_starts = {card_id: court_anchor + 2 * i for i, (card_id, _title) in enumerate(courts)}
    minor_starts = {card_id: minor_anchor + 2 * i for i, (card_id, _title) in enumerate(minors)}

    starts = {**major_starts, **court_starts, **minor_starts}

    sections: list[Section] = []
    for n, (card_id, title) in enumerate(all_cards):
        page_start = starts[card_id]
        if card_id in major_starts:
            following = [starts[c] for c, _t in all_cards if starts.get(c, 0) > page_start]
            page_end = min(following) - 1 if following else doc.page_count
        else:
            page_end = page_start + 1  # the fixed 2-PDF-page cadence above
        page_end = min(page_end, doc.page_count)
        if page_end < page_start:
            continue
        text = "\n\n".join(
            extract_page_text(doc, p) for p in range(page_start, page_end + 1)
        ).strip()
        if not text:
            continue
        sections.append(
            Section(
                section_id=f"ziegler_mirror_of_soul:{n:03d}:card:{card_id}",
                section_type="card",
                card_id=card_id,
                title=title,
                page_start=page_start,
                page_end=page_end,
                text=text,
            )
        )
    return sections
