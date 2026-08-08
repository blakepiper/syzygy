# ADR 0001: License Syzygy under AGPL-3.0 because of Kerykeion

**Status:** Accepted
**Date:** 2026-08-07

## Context

`DESIGN.md` section 22 flags a licensing constraint that must be resolved
before application code is built deeply around the astrology backend:

> The initial astrology backend selection creates a licensing constraint
> that must be respected by the repository... If the desired repository
> license is incompatible, resolve that before building application code
> deeply around the backend.

Kerykeion (the preferred astrology library, per `DESIGN.md` §9.1 and
`ARCHITECTURE_HANDOFF.md` §12) is licensed **AGPL-3.0**, confirmed directly
from its `pyproject.toml`, `LICENSE` file, and PyPI classifiers as of
version 5.12.9 (2026-08-07). The maintainer states explicitly that a
project importing Kerykeion directly should be open-sourced under a
compatible license, and offers a separate paid hosted API for closed-source
use.

AGPL-3.0 is a strong copyleft license. Its network-use clause (Section 13)
extends the normal GPL copyleft trigger to cover software made available
over a network, not just distributed binaries.

## Decision

**License the entire Syzygy repository under AGPL-3.0.**

This is the simplest available resolution:

- Syzygy is a local-first, personal, source-available art project. There is
  no hosted service, so the AGPL network clause has no practical bite here,
  but adopting AGPL keeps the license story simple and unambiguous rather
  than trying to carve out a compatible-but-different license for the rest
  of the codebase.
- The alternative — swapping the astrology backend to a permissively
  licensed library — was rejected. `ARCHITECTURE_HANDOFF.md` §12 and
  `DESIGN.md` §9.1 are explicit that Kerykeion is the preferred backend and
  that re-litigating "does the astrology library work" is not a good use of
  implementation effort. No investigation surfaced a concrete technical
  reason to avoid Kerykeion (its API is clean, offline-capable, and
  Pydantic-based — see `docs/adr/0002-kerykeion-adapter-notes.md` if later
  created, or `IMPLEMENTATION_PLAN.md` Milestone 2 for adapter details).

## Consequences

- `LICENSE` at the repository root is the verbatim GNU AGPL-3.0 text.
- `pyproject.toml` declares `license = "AGPL-3.0-or-later"`.
- If Syzygy ever grows a hosted/network-accessible mode (explicitly out of
  scope for v0.1 per `DESIGN.md` §31), the AGPL network clause will apply
  and users interacting with it over a network must be offered the
  corresponding source.
- Any future dependency must be checked for AGPL compatibility before
  being added. Permissive licenses (MIT, BSD, Apache-2.0) are always
  compatible. Other copyleft licenses need individual review.
- The Book of Thoth PDF and any extracted knowledge-base content are
  **not** covered by this decision — that material has its own copyright
  status (Crowley/OTO), is not redistributed as part of the package (see
  `docs/THOTH_INGESTION_MAP.md`), and remains a local, user-supplied input.
