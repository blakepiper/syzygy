# Knowledge Sources — multi-source policy and companion-source structure

`docs/THOTH_INGESTION_MAP.md` covers *The Book of Thoth* in exhaustive
detail because it is the **canonical, primary source** — it is what
`src/syzygy/resources/thoth_deck.yaml`'s correspondences are grounded
against, and it is the source Tier 1 structural retrieval (`DESIGN.md`
section 11.2) always checks first for the drawn card.

Two companion sources were added to `docs/` after that document was
written:

- **Lon Milo DuQuette, *Understanding Aleister Crowley's Thoth Tarot*
  (2002)** — `docs/understanding_crowley_thoth_tarot.pdf`
- **Gerd Ziegler, *Tarot: Mirror of the Soul* (1988, trans. of *Tarot:
  Spiegel der Seele*, 1986)** — `docs/mirror_of_the_soul.pdf`

This document defines how they fit into the knowledge architecture and
records the same category of structural facts
`docs/THOTH_INGESTION_MAP.md` recorded for the primary source — at a
depth proportional to their role (supplementary, not canonical).

## 1. Source policy

### 1.1 Tiers

```text
Tier 0 (canonical)     The Book of Thoth
                        - grounds thoth_deck.yaml correspondences
                        - always retrieved first for the drawn card
                        - the only source consulted by anything that
                          claims to state a Thoth correspondence as fact

Tier 1 (supplementary)  DuQuette, Ziegler
                        - retrieved alongside Tier 0 material as
                          additional interpretive color
                        - never used to populate or override
                          thoth_deck.yaml
                        - never allowed to contradict Tier 0 silently -
                          if a companion source frames a card differently
                          (see section 4), that's fine for interpretive
                          texture, but it must not become the
                          "correspondence" the app treats as fact
```

This mirrors `DESIGN.md` section 11's own two-tier retrieval design
(deterministic structural lookup first, semantic/lexical second) — tiering
*sources* is an orthogonal, additional axis on top of that, not a
replacement for it. A single drawn card's context can pull: the Tier 0
structural chunk (always), plus Tier 1 structural chunks from either or
both companion sources (if their ingestion successfully mapped a section
to that `card_id`), before any lexical/semantic retrieval is even
considered.

### 1.2 Distribution

None of the three source PDFs are committed to this repository — see
`.gitignore` (`docs/*.pdf`). This matches `DESIGN.md` section 11.1 ("The
repository should not contain the complete book text unless distribution
rights are clearly established") and section 22's redistribution-rights
note. What ingestion *produces* from them — chunks, hashes, the FTS index,
and any future embedding index, all inside the SQLite database or a
generated artifact under `src/syzygy/resources/` or a data directory —
is fine to commit once Milestone 6 exists, since that's derived,
attributed, chunked material with page-level provenance, not a redistributed
copy of the book.

Each source's raw-file hash is recorded below so ingestion can verify it's
processing the same file this document was written against, the same way
`docs/THOTH_INGESTION_MAP.md` section 1 does for the primary source.

## 2. Source registry

| id | `source_type` | Title | Author | File | SHA-256 | Pages |
|---|---|---|---|---|---|---|
| tier 0 | `book_of_thoth` | The Book of Thoth | Aleister Crowley | `docs/book_of_thoth.pdf` | `5942febc85fd73e38ac4dfb9fc32e4ba9591883f6d2709ea829e4827ae1083a0` | 294 (see `docs/THOTH_INGESTION_MAP.md`) |
| tier 1 | `duquette_companion` | Understanding Aleister Crowley's Thoth Tarot | Lon Milo DuQuette | `docs/understanding_crowley_thoth_tarot.pdf` | `d306a29aa8e216c1aa335da371f28be6232331adb9835e3de64591c01a248437` | 334 |
| tier 1 | `ziegler_mirror_of_soul` | Tarot: Mirror of the Soul | Gerd Ziegler | `docs/mirror_of_the_soul.pdf` | `10657a1eb29cfb6641484e57d562ba2b3ca693212840f9257ed21bb10870daf5` | 197 |

`source_type` values above are the convention M6's `syzygy.knowledge.ingest`
should use for `knowledge_sources.source_type` — no schema change was
needed for multi-source support: `syzygy.domain.knowledge.KnowledgeSource`
already has a free-text `source_type` field and per-source `file_hash`
(`DESIGN.md` section 16.1's `knowledge_sources` table already models
"one of possibly several sources").

## 3. DuQuette — *Understanding Aleister Crowley's Thoth Tarot*

### 3.1 Provenance and text quality

PDF metadata: `Creator: Digitized by the Internet Archive`,
`Producer: Recoded by LuraDocument PDF v2.65`. **This is an OCR'd scan**,
not a born-digital or web-capture text layer like the primary source. Text
quality is uneven:

- Body prose pages (sampled: pages 6, 21, 41, 151, 201, 251, 301) extract
  as mostly-correct, readable English with scattered character-level OCR
  errors (`"UndtntandmiAkitter Crsvdey's TbtJib T^t"` for "Understanding
  Aleister Crowley's Thoth Tarot" in a running header; `"tbe"` for "the"
  style substitutions; occasional smart-quote/ligature corruption).
- At least one page (334-page document, page 81 in this session's sample)
  extracted with **zero characters** — an image-only page (likely a card
  illustration), same skip-empty-page handling as
  `docs/THOTH_INGESTION_MAP.md` section 9 recommends for the primary
  source applies here too.
- The stylized title-page text (page 1) OCR'd nearly unusably
  (`"authuruuiivc exiimiriiitiiin"`) — expect similar degradation on any
  page using decorative typography rather than body text.

**Implication for ingestion**: the primary source's exact-string
header/footer stripping (`docs/THOTH_INGESTION_MAP.md` section 4) will
**not** work here, because the same running header OCRs differently on
different pages (four different garblings of the same title string were
observed across five sampled pages). Use a heuristic instead: the header
is reliably a short (~15-45 character) line, isolated as its own block,
positioned first or last on the page, adjacent to an isolated 1-3 digit
page number — detect and strip *by position and length*, not by string
match. Do not attempt to "fix" the OCR text into correct spelling
(`DESIGN.md` section 11.2's normalization rule — don't rewrite spelling —
applies at least as strongly here as it does to the primary source's minor
transcription artifacts).

### 3.2 Structure

No PDF bookmarks (`get_toc()` returns empty). Card sections were located
by scanning for heading-shaped lines (`ATU <roman>`, `<RANK> OF <SUIT>`,
`<COURT> OF <SUIT>`) directly, confirming a full three-part structure:

| Approx. PDF pages | Content |
|---|---|
| ~100–160 | Major Arcana, one section per trump. Heading format is inconsistent — some cards heading as `ATU <roman>` on its own line (confirmed: IV, VI, VII, VIII, IX, XI–XVIII, XXI), others apparently formatted differently (0, I, II, III, V, X, XIX, XX were not caught by an `ATU <roman>`-anchored scan and need a broader pattern, e.g. also matching a bare card title). **Do not assume every Major Arcana section starts with literal "ATU"** — verify per-card at ingestion time. |
| ~167–170 | The four Aces — clean `ACE OF <SUIT>` headings |
| ~176–204 | The 16 Court cards — clean `<COURT> OF <SUIT>` headings, e.g. `KNIGHT OF WANDS` at ~176 through `PRINCESS OF DISKS` at ~204 |
| ~214–272 | The 36 numbered Minors (Two–Ten) — clean `<RANK> OF <SUIT>` headings, e.g. `TWO OF WANDS` at ~214 through `TEN OF DISKS` at ~272 |
| ~280+ | **A second, different section** that also contains card-name-shaped lines (`"TWo OF Wands"`, `"Six OF Wands"`, mixed-case, at pages 282–287+ in the sample) — this reads as a compressed quick-reference/divinatory-summary appendix, distinct from the main per-card essays above. **Do not let this section's chunks collide with the main section's chunks for the same `card_id`** — tag it with a distinct `section_type` (e.g. `"quick_reference"`) so retrieval can prefer the main essay and treat this as lower-priority supplementary text, or exclude it from v0.1 ingestion entirely if it adds more noise than value. Verify its exact boundaries before ingesting it.

### 3.3 Per-card content is rich and structurally consistent (when clean)

Where extraction is clean, per-card sections carry more structured
metadata than the primary source's prose-only essays — useful supplementary
fields for retrieval context, e.g. (Eight of Swords, page ~251):

```
EIGHT OF SWORDS
INTERFERENCE
(Jupiter in Gemini)
0° to 10° Gemini
May 21 to May 31
Original Title: Lord of Shortened Force.
Golden Dawn Model: ...
```

and (Queen of Disks, page ~201):

```
QUEEN OF DISKS
Water of Earth
20° Sagittarius to 20° Capricorn
December 13 to January 9
Rules 10 of Wands; 2 of Disks; 3 of Disks
Original Titles: The Queen of the Thrones of Earth; Queen of the Gnomes.
```

These decan/date-range/element lines are a **useful cross-check** against
`thoth_deck.yaml`'s independently-sourced (from the primary text)
correspondences — the Eight of Swords sample above (`Jupiter in Gemini`,
decan 1) matches this session's Chaldean-decan derivation exactly. Do not,
however, treat a mismatch (should one turn up during full ingestion) as
grounds to change `thoth_deck.yaml` without first re-checking the primary
source directly — DuQuette is Tier 1.

## 4. Ziegler — *Tarot: Mirror of the Soul*

### 4.1 Provenance and text quality

PDF metadata: `Creator: pdftk 1.41`, `Producer: itext-paulo-155`. Text
extracts **cleanly** — no OCR-style character corruption observed in any
sampled page (title page, foreword, body prose, and multiple card
sections). Treat this source as having primary-source-quality text
extraction, unlike DuQuette.

### 4.2 Structure — from the book's own table of contents

No PDF bookmarks, but PDF pages 5–7 contain a complete, clean, exact
contents listing (verbatim page numbers, printed-book pagination):

```text
Foreword                     1
The System of the Tarot      1
The Crowley-Thoth Tarot      3
The Use of the Tarot         5
The Major Arcana             11
  0  The Fool                13
  I  The Magus                16
  II The Priestess            18
  ...                         (through)
  XXI The Universe            58
The Court Cards               61
  Knight of Wands             63
  ...                         (through)
  Princess of Disks           93
The Minor Arcana              95
  Ace of Wands                97
  Two of Wands                99
  ...                         (through)
  Ten of Disks                175
Systems for Using the Cards  177
Commonly Occurring Symbols   191
```

This is a full, precise printed-page map for all 78 cards — better than
what was extractable from DuQuette. **PDF-page-to-printed-page offset**:
PDF page 8 contains the `FOREWORD` heading, and the TOC above states
Foreword begins at printed page 1 — so the offset is approximately
`pdf_page = printed_page + 7`, i.e. The Fool (printed 13) should be around
PDF page 20. This is a rough estimate from one data point; **verify it
properly at ingestion time** (check whether this source has its own
embedded `p.NNN`-style page markers the way the primary source does,
per `docs/THOTH_INGESTION_MAP.md` section 5 — this was not checked during
this session and should be the first thing M6 confirms for this source).

Card titles in this TOC use "The Priestess" and "The Magus" rather than
the primary source's "The High Priestess" — add both forms to that card's
retrieval-time alias matching (`thoth_deck.yaml`'s
`book_of_thoth_aliases` is specific to the primary source's own text and
should not be edited for this; keep companion-source aliasing local to
the M6 ingestion/segmentation code, e.g. a small per-source alias table,
rather than growing the canonical deck file with non-canonical-source
naming variants).

### 4.3 Per-card heading pattern

Confirmed (Ace of Cups, PDF page 121):

```
ACE OF CUPS
Key Words: Overflowing love; emotional clarity, deep love of the self;
giving and receiving.
<prose interpretation follows>
```

Card title as an isolated all-caps line, immediately followed by a
`Key Words:` field, then prose — a simpler and more consistent pattern
than either other source. This `Key Words:` line is a good candidate for
a short-form supplementary field if the context builder ever wants a
one-line companion gloss rather than a full chunk.

### 4.4 Not yet verified

Header/footer repeated-boilerplate pattern (if any — page samples in this
session showed no obvious repeated header text, but this was not checked
as systematically as it was for the primary source in
`docs/THOTH_INGESTION_MAP.md` section 4); presence/absence of embedded
page-number markers; exact PDF-page boundaries for each of the 78 card
sections (the printed-page TOC above plus the approximate offset gets
close, but should be confirmed against actual heading positions, the same
way `docs/THOTH_INGESTION_MAP.md` section 10 did for the primary source).

## 5. What this changes in the ingestion pipeline

See `IMPLEMENTATION_PLAN.md` Milestone 6 for the updated task breakdown.
In short: `syzygy.knowledge.segment` needs source-specific heading
detectors (the three sources use three different heading conventions),
`syzygy.knowledge.normalize` needs a position/length-based header-stripping
mode for DuQuette specifically (its OCR noise defeats exact-string
matching), and `syzygy.knowledge.retrieve`'s structural lookup should
return Tier 0 chunks first, then Tier 1 chunks from whichever companion
sources have been ingested — a source that hasn't been ingested simply
contributes nothing, so ingesting DuQuette and/or Ziegler is optional and
additive, never required for the app to function (consistent with
`DESIGN.md` section 23's "knowledge unavailable" failure mode already
covering the "no companion sources ingested" case for free).
