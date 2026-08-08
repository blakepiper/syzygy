"""A single significant transit, as a modifier attached to the card.

Astrology behaves like modifiers around the card, not as the subject
(DESIGN.md section 33's UX invariants) - hence a compact badge rather
than a table row. What counts as significant was already decided by
`syzygy.astrology.policy` and `syzygy.astrology.ranking`; this widget only
displays rank order it is given.
"""

from __future__ import annotations

from textual.widgets import Static

from syzygy.domain.astrology import RankedTransit
from syzygy.tui.widgets.glyph import GlyphSet, default_glyphs, format_orb


def format_transit(ranked: RankedTransit, glyphs: GlyphSet | None = None) -> str:
    """`♄ □ ♀ 0°48' applying` - transiting body, aspect, natal target, orb."""
    marks = glyphs or default_glyphs()
    aspect = ranked.aspect
    return (
        f"{marks.body(aspect.transiting_body)} {marks.aspect(aspect.aspect)} "
        f"{marks.body(aspect.natal_target)} {format_orb(aspect.orb_degrees)} "
        f"{aspect.movement}"
    )


class TransitBadge(Static):
    """One ranked transit. `applying`/`separating` are exposed as CSS
    classes so movement is never carried by color alone (DESIGN.md 18.4).
    """

    def __init__(
        self,
        ranked: RankedTransit,
        *,
        glyphs: GlyphSet | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__(
            format_transit(ranked, glyphs),
            id=id,
            classes=f"transit-badge {ranked.aspect.movement}",
        )
        self.ranked = ranked
