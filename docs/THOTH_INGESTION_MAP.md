# Book of Thoth — Ingestion Map

**Purpose:** concrete, inspected facts about the actual file at
`docs/book_of_thoth.pdf`, so the M6 ingestion parser (`src/syzygy/knowledge/`)
can be built deterministically without re-discovering the PDF's structure
from scratch. See `docs/old/IMPLEMENTATION_PLAN.md` Milestone 6 for the code this
document feeds.

This document covers the **Book of Thoth only** — the canonical, Tier 0
source. Two supplementary Tier 1 companion sources (DuQuette, Ziegler)
were added later; see `docs/KNOWLEDGE_SOURCES.md` for the multi-source
policy and their own structural notes. Nothing in this document changes
as a result — the Book of Thoth remains the sole source
`thoth_deck.yaml`'s correspondences are grounded against.

This document describes the file, not the book's content. Only short
excerpts (a few lines) are quoted here for illustration, consistent with
`docs/old/DESIGN.md` §11.1 (do not redistribute large amounts of the book text).

## 1. File identity

| Field | Value |
|---|---|
| Path | `docs/book_of_thoth.pdf` |
| SHA-256 | `5942febc85fd73e38ac4dfb9fc32e4ba9591883f6d2709ea829e4827ae1083a0` |
| PDF version | 1.5 |
| PDF page count | **294** (`pymupdf.open(...).page_count`; do not trust generic `file(1)` page-count output — it undercounts on this file) |
| PDF metadata `/Title` | `The Book of Toth` (sic — typo in the original metadata) |
| PDF metadata `/Author` | `Alistar Crowley` (sic) |
| PDF metadata `/Creator` | Acrobat Web Capture 6.0 |
| PDF metadata `/CreationDate` | 2004-02-28 |

**Ingestion must store this hash in `knowledge_sources.file_hash`** (per
`docs/old/DESIGN.md` §16.1) and compare on re-ingestion to detect a swapped/updated
source file.

## 2. Provenance and what kind of document this is

This PDF is **not a clean scan of the printed book**. Its metadata
(`Acrobat Web Capture 6.0`) and internal artifacts (`E:\THOTH\THOTH2B.HTM`,
`file:///D:/Books/.../thoth.htm`, per-page `.htm (N of M)` footers) show it
was produced by capturing an old multi-page HTML website version of *The
Book of Thoth* (file names `thoth.htm`, `thoth2a.htm`, `thoth2b.htm`,
`thoth3.htm`, `thoth4.htm`, `thoth5.htm`, `thoth6.htm`) into a single PDF,
one browser "page" per PDF page. The title page states the text is
"partly linked, mostly proofread" — i.e. a community transcription, not an
OCR of scanned pages. This explains several extraction quirks documented
below (word-splitting artifacts, embedded page-number tokens, a "partly
proofread" typo rate).

Card artwork was part of this capture as separate image files
(`major00.jpg` … `disks10.jpg`). **These pages have no usable text** — see
§5.

## 3. Text layer quality

The text layer is a real, selectable text layer (not scanned raster text
needing OCR). `page.get_text()` via PyMuPDF returns clean paragraph text for
every prose page. **No OCR fallback is needed for this file.**

Quality caveats found during inspection (source-transcription artifacts,
not PDF-extraction artifacts — do not "fix" these by guessing, per
`docs/old/DESIGN.md` §11.2's instruction not to rewrite spelling):

- Occasional stray typos carried over from the web transcription, e.g.
  `"tbe floor"` for `"the floor"`.
- Occasional spurious mid-word space splits from the original HTML line
  wrapping, e.g. `"plane tary"` for `"planetary"`, `"in creas­ing"` for
  `"increasing"`. These are **not** consistently hyphenated, so a simple
  "rejoin hyphen + linebreak" rule will not catch all of them. Do not
  attempt automatic dictionary-based rejoining — it risks corrupting
  genuine two-word phrases and Crowley's invented/Latinized terms
  (`"Bacchus Diphues"`, `"Hoor-Pa-Kraat"`, etc). Leave as-is; this is a
  known, bounded source-quality issue, not an ingestion bug.
- Standard `-\n` hyphenation-at-linebreak (e.g. `"micro-\nphone"`) **is**
  safe to rejoin — PyMuPDF's `get_text()` in "text" mode already
  reassembles most of these as unbroken words; verify against a sample
  after implementing, but no evidence of broken hyphenation survived into
  the extracted text during this inspection.

## 4. Repeated headers and footers (strip these)

Every one of the 294 pages has the **same two structural artifacts**,
verified across the whole document:

1. **Header** — the first text block on every page is a repeated
   per-section running header, one of a small fixed set (~9 distinct
   values across the whole document, corresponding to the original HTML
   file names), e.g.:
   - `THE BOOK OF THOTH, CONTENTS PART ONE`
   - `BOOK OF THOTH PART2A`
   - `E:\THOTH\THOTH2B.HTM`
   - `E:\THOTH\THOTH3.HTM`
   - `BOOK OF THOTH PART FOUR THOTH4.HTM`
   - `E:\THOTH\THOTH5.HTM`
   - `E:\THOTH\THOTH6.HTM`

   **Rule:** always drop the first `get_text("blocks")` block of every
   page before further processing.

2. **Footer** — the *last* text block on **all 294/294 pages** matches
   `^file:///` — the original image/HTML file path plus a capture
   timestamp, e.g.:
   `file:///D:/Books/.../thoth4.htm (13 of 44)28.02.2004 22:48:56`.

   **Rule:** always drop the last block matching `^file:///` (verified:
   100% of pages, zero exceptions — safe to treat as unconditional).

After stripping header + footer, remaining blocks are section navigation
boilerplate (`"CONTENTS"`, `"TOP OF THIS SECTION"`, `"PREVIOUS SECTION---..."`,
`"NEXT SECTION---..."`) or real prose. Navigation boilerplate lines are
short, appear only on section-boundary pages, and match a small fixed set
of literal strings — filter by exact/prefix match rather than heuristics.

## 5. Printed-page markers embedded in the text (page provenance)

The original book's printed page numbers survive in-line in the text as
standalone tokens of the form `p.NNN` (e.g. `p.121`, `P.149`; case varies).
**These are a gift for provenance** — they let ingestion attach a real
printed-book page number to every chunk, independent of PDF page index.

Two extraction subtleties, confirmed by inspection:

- **Most `p.NNN` tokens are genuine page-break markers**, occurring as
  their own isolated `get_text("blocks")` block (verified via block-level
  extraction, e.g. page 6 has blocks `'p.5'`, `'p.6'` as standalone
  blocks). Detect these with a block-level scan and a regex anchored to
  the whole block: `^[Pp]\.\s?\d{1,3}\.?$`.
- **A minority are inline cross-references inside a sentence**
  (e.g. a footnote saying "see page 229"), which will falsely match a
  naive full-text regex scan (a whole-page-text regex over PDF page 7
  found `['229', '8', '13']` — only `8` and `13` are real page markers;
  `229` is a footnote cross-reference). **Do not regex over
  `page.get_text()` (plain string) for this** — always operate at the
  `get_text("blocks")` level and require the marker to be the *entire*
  block content, not a substring.

The book's own table of contents (PDF pages 1–3) states the printed-page
ranges of each Part, which cross-checks cleanly against the in-text
markers:

| Part | Printed pages | Approx. PDF pages (see §6) |
|---|---|---|
| Part One — Theory of the Tarot | 3–48 | 1–26 |
| Part Two — The Atu (Trumps) | 53–144 | 27–137 |
| Part Three — The Court Cards | 149–171 | 138–159 |
| Part Four — The Small Cards | 177–218 | 160–218 |
| Invocation and Mnemonics | 218–220 | ~219–221 |
| Appendix A — Behaviour of the Tarot / divination | 249–260 | 219–231 |
| Appendix B — Correspondences | 265–287 | 271–288 |

(PDF-page column derived from PDF bookmarks + spot-checked `p.NNN`
markers; treat as approximate — build the authoritative mapping at
ingestion time from the markers themselves, not from this table.)

## 6. Document structure (PDF page ranges)

Derived from the PDF's own outline/bookmarks (`doc.get_toc()`) plus manual
spot-checks of page text. All ranges are **1-indexed PDF page numbers**.

| PDF pages | Content |
|---|---|
| 1–26 | Front matter: title page, "WHEEL AND — WHOA!" epigraph, full contents listing (Parts One–IV, Appendices A & B with their printed-page ranges and full card-name lists — see §7), Part One theory essay |
| 27–89 | **Part Two: the 22 Atu (Trumps).** Main per-card essays, `0. THE FOOL` through `XXI. THE UNIVERSE`, each with a numbered heading (see §8) |
| 90–111 | Major Arcana card-image gallery (22 pages, `major00.jpg`…`major21.jpg`) — **no usable text**, see §5 below this table... see §9 |
| 112–137 | Part Two **Appendix**: supplementary esoteric essays for six specific trumps only — The Fool, The Magus, Fortune, Lust, Art, The Universe (per the TOC's own "Appendix" listing on PDF page 2). This is *additional* material for those six cards, not the primary card description (which is already complete at pages 27–89) |
| 138–159 | **Part Three: the 16 Court Cards.** General theory (Knights/Queens/Princes/Princesses as Yod/Heh/Vau/Heh-final of Tetragrammaton) followed by per-card sections, `KNIGHT OF WANDS` through `PRINCESS OF DISKS` |
| 160–203 | **Part Four: the 40 numbered Minor Arcana cards** (Ace–Ten × 4 suits), theory intro then per-card sections, `ACE OF WANDS` through `TEN OF DISKS` |
| 204–218 | Court-card image gallery (15 pages — `disks12.jpg`/Queen of Disks bookmark is missing from the PDF outline; verify at ingestion time whether the page itself is present, don't rely solely on bookmarks) — **no usable text** |
| 219–231 | Appendix A: "The Behaviour of the Tarot" — divination/spread methodology, not per-card doctrine |
| 232–270 | Minor Arcana numbered-card image gallery (39 pages; `swords07.jpg` bookmark is similarly missing) — **no usable text** |
| 271–288 | Appendix B: "Correspondences" — Qabalistic/alchemical essay text **plus several large attribution tables that were images in the original capture and are NOT text-extractable** (PDF pages 278–280 contain only header/page-marker/footer, zero prose — the table images did not survive the web capture as text). **Do not expect to extract the "Tables of Correspondence" from this PDF; that data is not present as text.** (This is why `thoth_deck.yaml`, built during this session, sources per-card astrological correspondences from the main card-essay prose at pages 27–218, where Crowley states them in sentences, e.g. "the power of the planet Mars in his own sign Aries" for the Two of Wands — not from this appendix.) |
| 289–294 | Closing diagram images (`keyscale.gif`, `attribution2.jpg`, `chicosmos.gif`, `diagram5.gif`, `p284.gif`) — no usable text |

## 7. The book's own table of contents is a usable heading/alias source

PDF pages 1–3 contain Crowley's own contents listing, which enumerates
**every card's exact Thoth title** in running prose, e.g.:

> Ace of Wands; Dominion-Two of Wands; Virtue-Three of Wands;
> Completion-Four of Wands; Strife-Five of Wands; Victory-Six of Wands;
> Valour-Seven of Wands; Swiftness-Eight of Wands; Strength-Nine of Wands;
> Oppression-Ten of Wands.

and:

> General Remarks; General Characteristics of the Four Dignitaries;
> Summarized description of the Sixteen Court Cards; Knight of Wands;
> Queen of Wands; Prince of Wands; Princess of Wands; ...

This is the authoritative source for the `book_of_thoth_aliases` used in
`thoth_deck.yaml` — every alias in that file's minor/court entries is
copied verbatim from this listing, not invented.

## 8. Card-section heading pattern (for segmentation)

Confirmed via `get_text("dict")` span inspection (font/size/color), not
just plain text:

- **Major Arcana**: each card section starts with a numbered heading as
  its own paragraph block, matching `^(0|[IVXL]+)\.\s+[A-Z]`, e.g.
  `"0. THE FOOL1."`, `"VII. THE CHARIOT"`, `"XV. THE DEVIL"`. All 22 are
  present at PDF pages 27–89 (line-anchored, one per card, in order) — see
  the confirmed anchor list in §10.
- **Minor Arcana (numbered)**: each card section is introduced by a
  **two-line heading**: the card's Thoth *title* on its own line in caps
  (e.g. `DOMINION`), immediately followed by the rank-suit name on its own
  line in caps (e.g. `TWO OF WANDS`). Both lines are short (`isupper()`,
  under ~25 characters) standalone blocks between paragraphs — use that as
  the structural detector, **not font size**: inspection found the title
  line at 14.0pt (same as body) and the rank-suit line at ~12.9pt
  (*smaller* than body, an unhelpful signal), but the rank-suit line's
  span `color` was `255` (pure blue, `0x0000FF`) versus `0` (black) for
  surrounding body text in the one sample checked — treat color as a weak
  secondary signal, not a primary one; the reliable signal is short
  all-caps standalone-block text.
- **Court cards**: single-line heading, e.g. `KNIGHT OF WANDS`,
  `PRINCESS OF DISKS`, matching `^(KNIGHT|QUEEN|PRINCE|PRINCESS) OF
  (WANDS|CUPS|SWORDS|DISKS)$` as a standalone block.
- Aces have a single-line heading `ACE OF (WANDS|CUPS|SWORDS|DISKS)` (no
  "title" line, since Aces represent the unmodified root of the suit's
  element, not a decan — consistent with `thoth_deck.yaml`, where Aces
  have `astrology: null`).

## 9. Pages with no usable text (skip during ingestion)

Every card-artwork gallery page (§6 ranges 90–111, 204–218, 232–270)
contains **only the repeated header + a single `file:///....jpg` link
block + the footer** — typically under 250 characters total, all
boilerplate, zero prose. Example (PDF page 90, verbatim):

```
file:///D:/Books/.../major00.jpg
file:///D:/Books/.../major00.jpg28.02.2004 22:48:44
```

**Recommended ingestion rule:** after stripping header/footer (§4), if
remaining page text is under ~50 characters, skip the page entirely rather
than trying to segment it. Do not treat the presence of a card's own image
filename (e.g. `major09.jpg`) on a page as evidence that page discusses
that card — it doesn't; the text is a dead file-path string from the
original web capture, not a caption.

## 10. Verified Major Arcana heading anchors (PDF page → card)

For direct use by the segmentation code (0-indexed PDF page = table value
− 1, since PyMuPDF pages are 0-indexed):

| PDF page | Heading |
|---|---|
| 27 | `0. THE FOOL` |
| 32 | `I. THE JUGGLER` (Crowley's alias for The Magus/Magician — include both as aliases) |
| 36 | `II. THE HIGH PRIESTESS` |
| 38 | `III. THE EMPRESS` |
| 39 | `IV. THE EMPEROR` |
| 40 | `V. THE HIEROPHANT` |
| 41 | `VI. THE LOVERS OR: (THE BROTHERS)` |
| 44 | `VII. THE CHARIOT` |
| 45 | `VIII. ADJUSTMENT` |
| 47 | `IX. THE HERMIT` |
| 48 | `X. FORTUNE` |
| 49 | `XI. LUST` |
| 54 | `XII. THE HANGED MAN` |
| 58 | `XIII. DEATH` |
| 61 | `XIV. ART` |
| 65 | `XV. THE DEVIL` |
| 69 | `XVI. THE TOWER (OR: WAR)` |
| 72 | `XVII. THE STAR` |
| 74 | `XVIII. THE MOON` |
| 76 | `XIX. THE SUN` |
| 78 | `XX. THE AEON` |
| 80 | `XXI. THE UNIVERSE` |

(PDF-page numbers computed from 1-indexed line offsets inside a
concatenated per-page dump made during this inspection; re-derive
programmatically at ingestion time rather than hard-coding these — this
table is a sanity check, not a substitute for parsing.)

## 11. Confirmed Thoth-specific attribution facts (grounding for `thoth_deck.yaml`)

These were confirmed by reading Crowley's own sentences (not inferred),
and are exactly the kind of thing a generic tarot-astrology table found on
the web gets wrong, because they're specific to Crowley's system:

- **The Emperor is attributed to Tzaddi (Aries)**, and **The Star is
  attributed to Heh (Aquarius)** — the reverse of the "traditional"
  pre-Golden-Dawn assignment (Heh=Aries, Tzaddi=Aquarius). This is
  Crowley's well-known change, citing *Liber AL vel Legis* II:76 ("Tzaddi
  is not the Star..."). Confirmed directly: PDF page 39 (`IV. THE
  EMPEROR`) states *"This card is attributed to the letter Tzaddi, and it
  refers to the sign of Aries"*; PDF page 72 (`XVII. THE STAR`) states
  *"This card is attributed to the letter He'... it refers to the
  Zodiacal sign of Aquarius"*.
- **The Aeon (Shin) is attributed to Spirit**, not generically to Fire —
  Crowley's text (PDF page ~78) says *"the element of Spirit is
  attributed to the letter Shin"*. `thoth_deck.yaml` encodes `element:
  spirit` for The Aeon, not `fire`.
- **Princesses have no zodiacal attribution.** Stated explicitly (PDF page
  140, Part Three general theory): *"The Princesses have no Zodiacal
  attribution."* `thoth_deck.yaml` encodes `astrology.decan: null` for all
  four Princess cards — this is not a data-entry gap, it's a documented
  fact about the system.
- **Court-card zodiac spans are counter-elemental, not the "obvious"
  triplicity.** Confirmed directly, e.g. the Knight of Wands ("the fiery
  part of Fire") is attributed to the *last decan of Scorpio + first two
  decans of Sagittarius* — not Aries, which a naive assumption would
  guess. Crowley's own text flags this as counter-intuitive: *"one might
  anticipate that the fiery part of Fire would refer to... Aries. On the
  contrary..."* (PDF page 138). All 12 zodiac-bearing court-card spans in
  `thoth_deck.yaml` were read directly from their individual card
  sections (PDF pages 141–201), not derived by formula.
- **Minor Arcana decan rulers follow the standard Chaldean 36-decan
  wheel**, applied per suit across its three triplicity signs in
  cardinal→fixed→mutable order (e.g. Wands: Aries, Leo, Sagittarius).
  Spot-checked directly against Crowley's text at multiple points
  (Two of Wands = Mars/Aries; Nine of Wands = Moon/Sagittarius; Two of
  Cups = Venus/Cancer; Six of Disks = Moon/Taurus) and found to match the
  standard table exactly at every checked point — used to fill the
  remaining cards without individually quoting all 36 in this document
  (to avoid reproducing large amounts of the source text; the full
  citations live in the session history that produced `thoth_deck.yaml`,
  not in the repository).

## 12. Recommended ingestion pipeline (concrete, for M6)

1. Open with PyMuPDF (`pymupdf`, imported as `import pymupdf` — the
   `fitz` alias is deprecated in current versions and prints a
   `DeprecationWarning`; import `pymupdf` directly).
2. Hash the file; compare against `knowledge_sources.file_hash`; skip
   re-ingestion if unchanged.
3. For each page: `get_text("blocks")`; drop the first block (header, §4)
   and the last block matching `^file:///` (footer, §4); if remaining
   text < ~50 chars, skip the page (image gallery, §9).
4. Within the remaining blocks, detect standalone `p.NNN` page-marker
   blocks (§5) and attach the nearest preceding marker as `page_start`
   metadata for subsequent chunks, so every chunk carries a real printed
   page number.
5. Detect section headings using the patterns in §8 (Major Arcana numbered
   heading; Minor Arcana two-line caps heading; Court card single-line
   caps heading) to split the document into card-scoped sections. Never
   let a chunk cross a heading boundary (`docs/old/DESIGN.md` §11.3 step 5).
6. Map each detected heading to a canonical `card_id` from
   `thoth_deck.yaml` using the `book_of_thoth_aliases` list on each card
   (built from §7's verbatim TOC listing) — exact string match, not fuzzy
   matching, since the aliases were transcribed directly from the same
   source document.
7. The six-trump appendix (§6, pages 112–137) should be attached to its
   six cards' existing sections as an additional chunk
   (`section_type: "card_appendix"`), not treated as unrelated general
   material.
8. Chunk within sections per `docs/old/DESIGN.md` §11.3 step 5 (~600–1200 tokens,
   small overlap only if a section exceeds that).
9. Store `source_hash`, `section_id`, `section_type`, `card_id`,
   `page_start`, `page_end`, `chunk_index`, `text_hash` per
   `docs/old/DESIGN.md` §16.1's `knowledge_chunks` schema.

## 13. Suggested test fixtures

Per `docs/old/ARCHITECTURE_HANDOFF.md` §16, create small fixtures rather than
duplicating the book. Recommended (to be created alongside the M6 parser,
not in this session): extracted-and-stripped text for one representative
page from each of: a Major Arcana card (e.g. PDF page 45, Adjustment), a
Minor Arcana card (PDF page 172, Two of Wands — already spot-checked
above), a Court card (PDF page 141, Knight of Wands), and one image-gallery
page (PDF page 90) to test the skip-empty-page rule. Store these as
`tests/fixtures/thoth_pdf_pages/*.txt`, a few hundred bytes each, with a
comment noting the source PDF page number — not the full page images.
