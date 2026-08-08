# ADR 0003: Ship a derived knowledge index, without any source text

**Status:** Accepted
**Date:** 2026-08-08

## Context

`syzygy knowledge ingest` builds the knowledge base by parsing three PDFs
that are deliberately **not** in the repository (`.gitignore`: `docs/*.pdf`;
`docs/KNOWLEDGE_SOURCES.md`). They are personal reference copies used as
ingestion input:

| Tier | Source | Status |
|---|---|---|
| 0 | Crowley, *The Book of Thoth* | canonical, the only source `thoth_deck.yaml` is grounded against |
| 1 | DuQuette, *Understanding Aleister Crowley's Thoth Tarot* | supplementary retrieval only |
| 1 | Ziegler, *Tarot: Mirror of the Soul* | supplementary retrieval only |

The consequence is that a fresh clone has an **empty** knowledge base. The
ingestion pipeline exists and works, but nobody who has not separately
obtained the books gets anything from it. `feedback.md` asks for the
processed sources to be committed as artifacts "that all users get".

`.gitignore`'s own note anticipates this and says derived data is fine to
commit:

> What ingestion produces from them (chunks, FTS index, any future
> embedding index) is derived/processed data and is fine to commit - only
> the raw PDFs themselves are excluded here.

That note is too permissive as written. Chunked full text of three
in-copyright books is, in substance, the books: ingestion splits them into
~900-word passages and stores the prose verbatim. Committing that to a
public AGPL repository is redistribution of the works, whatever directory
it lands in. All three are in copyright; none are licensed for
redistribution.

## Options considered

1. **Derived, non-reproducible artifacts only** — vectors and citation
   metadata; no verbatim text.
2. **Short quoted excerpts**, under a documented length cap.
3. **Full chunk text.**

Option 3 is redistribution and was rejected. Option 2 is defensible as
fair dealing / fair use in some jurisdictions but is a judgement call that
scales badly: 290 chunks × even a two-sentence excerpt is a meaningful
portion of three books, assembled and machine-readable, and "how short is
short enough" has no principled answer.

## Decision

**Option 1.** Ship `src/syzygy/resources/knowledge/`:

- `index.json` — per chunk: its source, section id and type, `card_id`,
  heading, page range, chunk index, SHA-256 of the text, and word count.
  Sorted and human-readable specifically so a reviewer can confirm there
  is no prose in it.
- `vectors.npy` — one unit-length `float32[256]` row per chunk.

Every install therefore knows **where** each of the 78 cards is discussed
in all three books, and can search that index, without carrying a word of
what those pages say.

### The vectors are hashed lexical signatures, not neural embeddings

`syzygy.knowledge.embedding` implements the signed hashing trick over
stop-worded word tokens with sublinear term frequency. Two chunks are
similar when they share vocabulary, not when they share meaning.

A real sentence-embedding model would give genuine semantic similarity,
but it has to run at *query* time as well as build time — a query must
land in the same vector space as the corpus — which makes
`sentence-transformers`/`torch` a runtime dependency of a local-first
terminal app, for a few hundred short documents. `AGENTS.md` already rules
out a vector database and a hosted service for the same reason, and
`IMPLEMENTATION_PLAN.md` M13.3d asks specifically for "a small local model
producing vectors committed to the repo, queried with plain numpy". A
hashed signature is the version of that with no model at all.

It also happens to be the safer choice for this ADR's purpose: a ~900-word
chunk collapses to 256 floats with word order discarded, so the vectors
are not invertible to text.

## Consequences

**What a fresh install gains.** The full structural map of all three
books: `retrieve_for_card` returns citations for every card, and
`syzygy knowledge search` ranks the index by vector similarity. Readings
can point at where their card is discussed.

**What it does not gain — stated plainly.** Source *passages* still
require the user's own PDFs and `syzygy knowledge ingest`. Citation-only
chunks are filtered out of the interpretation context
(`reading_service._select_knowledge_chunks`): a citation rendered under
the prompt's "SOURCE PASSAGES" heading with nothing beneath it invites the
model to invent the contents, which is exactly what `DESIGN.md` section 23
forbids. So **for the reading itself, this changes nothing** for a user
without the books — the prompt says "none supplied - do not imply you
consulted a source text", as it did before.

That is the real cost of Option 1, and it is worth being explicit that the
milestone's user-visible payoff is citations and search, not better
readings.

**Upgrading works.** Ingesting a real PDF replaces that source's citations
with full text. This needed a fix: the artifact records the same
`file_hash` and `ingestion_version` a real ingest would, so `ingest`'s
idempotency check reported "already ingested" and did nothing.
It now also requires that the existing source actually has text.

**Tier policy is unchanged.** `docs/book_of_thoth.pdf` remains Tier 0 and
the only source `thoth_deck.yaml` is grounded against; nothing in this
artifact may be used to add to or "correct" the deck file.

**numpy becomes a runtime dependency** (BSD-3, permissive, AGPL-compatible)
to load and query the matrix. It was already present transitively via
Pillow and `timezonefinder`.

**Regeneration is reproducible.** `syzygy knowledge build-artifact`
rebuilds both files byte-for-byte from the same PDFs at the same
`INGESTION_VERSIONS`/`VECTOR_VERSION`, so the committed artifact can be
audited against its inputs by anyone who has the books.
