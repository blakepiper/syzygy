"""The maintainer evaluation harness (M16.3b/c).

**Not part of the normal test suite.** It needs a running model, minutes
of compute, and a machine whose hardware you intend to report. `pytest`
must never touch it; `syzygy dev evaluate-local` runs it, and only with
`SYZYGY_DEV` set.

What it exists for: a general benchmark score says nothing about whether a
model can write *this* application's two registers without inventing a
card. So the harness runs Syzygy's own fixtures through the real prompt
contract and the real parse/repair path, and records what happened -
schema-valid on first pass, repair rate, truncation, latency, and rubric
scores for factual fidelity and usable prose.

Its output is the `evidence_id` a catalog entry needs before it may claim
`support_status: supported`. Until an artifact has one, the validator in
`local_models.catalog` refuses to let it claim full support, and the
wizard says the quality has not been measured.
"""

from __future__ import annotations
