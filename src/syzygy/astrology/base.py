"""The astrology engine boundary.

This is the only interface the rest of the application is allowed to
depend on for astrological calculation. `syzygy.astrology.kerykeion_backend`
(Milestone 2, not yet implemented - see IMPLEMENTATION_PLAN.md) is the
production implementation. Nothing outside `syzygy.astrology` may import
`kerykeion` directly (AGENTS.md).

Implementations are trusted to calculate correctly - Syzygy does not
re-verify celestial mechanics (ARCHITECTURE_HANDOFF.md section 12). What
Syzygy owns is everything downstream: which aspects count
(`syzygy.astrology.policy`), how they're ranked (`syzygy.astrology.ranking`,
Milestone 2), and how raw engine output is normalized into
`syzygy.domain.astrology` types.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from syzygy.domain.astrology import BirthData, NatalChart, TransitSnapshot


class AstrologyEngine(Protocol):
    """Calculates Self (natal) and Cosmos (transit) facts.

    Must never be asked to select a tarot card, evaluate current-location
    astrology, or make an interpretive judgment - it returns facts only.
    """

    def calculate_natal(self, birth: BirthData) -> NatalChart:
        """Calculate a natal chart from exact birth data. Pure function of
        its input: the same `BirthData` must always produce the same
        `NatalChart` (modulo the engine's own version, which the caller is
        responsible for recording alongside the result).
        """
        ...

    def calculate_transits(self, natal: NatalChart, instant: datetime) -> TransitSnapshot:
        """Calculate geocentric current planetary positions and their
        aspects to `natal`, evaluated at `instant` (must be timezone-aware,
        UTC by convention). Does not filter or rank aspects - that is
        `syzygy.astrology.policy` and `syzygy.astrology.ranking`'s job,
        applied by the caller to this method's output.
        """
        ...
