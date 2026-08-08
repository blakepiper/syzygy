# ADR 0002: PyMuPDF's AGPL license is compatible, reviewed under ADR 0001's policy

**Status:** Accepted
**Date:** 2026-08-08

## Context

`ADR 0001` licensed the whole Syzygy repository under AGPL-3.0 because of
Kerykeion, and closed with a standing policy: "Any future dependency must
be checked for AGPL compatibility before being added. Permissive licenses
... are always compatible. Other copyleft licenses need individual
review."

`pymupdf` was added in Milestone 6 (`src/syzygy/knowledge/normalize.py`
and `ingest.py` use it for PDF text/page extraction from the Book of
Thoth and companion sources) without that review being written down. A
Milestone 9 license audit (`TASKS.md` M9.6) found the gap: `pymupdf`'s
installed metadata reports `License: Dual Licensed - GNU AFFERO GPL 3.0 or
Artifex Commercial License` - the same AGPL-3.0 copyleft as Kerykeion, not
a permissive license.

## Decision

**No action needed beyond this record.** `pymupdf`'s AGPL-3.0 option is
compatible with Syzygy's own AGPL-3.0-or-later license, by the same
reasoning ADR 0001 already applied to Kerykeion: a strong-copyleft
dependency is compatible with a strong-copyleft project. Syzygy uses the
free AGPL-3.0 license grant, not Artifex's commercial one - there is no
payment or separate agreement involved.

The rest of Milestone 9's dependency audit (`textual`, `pydantic`,
`platformdirs`, `pyyaml`, `httpx`, `keyring`, `geopy`, `timezonefinder`,
`hatchling`, and the dev-only `pytest`/`pytest-asyncio`/`ruff`/`mypy`) are
all MIT, BSD-3-Clause, or Apache-2.0 - permissive, and so, per ADR 0001's
policy, always compatible without needing individual ADRs of their own.

## Consequences

- No change to `pyproject.toml`, `LICENSE`, or the repository's license.
- ADR 0001's "must be checked... before being added" policy was not
  followed in the moment for `pymupdf` - this ADR is written after the
  fact rather than before, during a scheduled audit rather than at
  dependency-add time. Future dependency additions should get this review
  (and, if copyleft, an ADR like this one) *before* landing, not
  retroactively during the next milestone-9-style audit.
