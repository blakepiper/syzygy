"""Syzygy's colours, for the widgets that build Rich styles in Python.

`syzygy.tcss` is the authoritative copy - it is what every screen and most
widgets are styled from. But `Text`/`Style` objects built inside widgets
(the wheel rim, the card face, the reading body) cannot reach a TCSS
variable, and before this module they each carried their own hex
literals. Changing the palette then meant finding every one of them, which
is exactly how a colour survives being "removed" (M12.1).

The two copies are kept honest by `tests/tui/test_palette.py`, which
parses the `$name: #value;` declarations out of `syzygy.tcss` and asserts
they match the constants here. Change a colour in both places, or the
test says so.
"""

from __future__ import annotations

from typing import Final

FIELD: Final = "#0a0b0d"
PANEL: Final = "#131417"
BONE: Final = "#e6ddc9"
MUTED: Final = "#8a8272"
DIM: Final = "#4a4438"

#: The calculated-fact accent: astrology, correspondences, headings. White
#: rather than the previous gold (M12.1), so it reads as brighter than
#: `BONE` body text instead of as a second warm tone beside it.
ACCENT: Final = "#ffffff"

LUNAR: Final = "#7ea6c9"
OXIDE: Final = "#8f3a2a"

#: Reserved for chance and reveal - never for anything calculated.
EMBER: Final = "#ff4d1f"

#: Only used for the alignment widget's connecting rule. Has no TCSS
#: counterpart, so it is excluded from the drift test by not appearing
#: there; keep it that way or add it to both.
RULE: Final = "#6b6455"

#: The subset that must exist, identically, in `syzygy.tcss`. Keys are the
#: TCSS variable names without their `$`.
TCSS_EQUIVALENTS: Final[dict[str, str]] = {
    "syz-field": FIELD,
    "syz-panel": PANEL,
    "syz-bone": BONE,
    "syz-muted": MUTED,
    "syz-dim": DIM,
    "syz-accent": ACCENT,
    "syz-lunar": LUNAR,
    "syz-oxide": OXIDE,
    "syz-ember": EMBER,
}
