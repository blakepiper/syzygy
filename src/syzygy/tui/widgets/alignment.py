"""SELF - COSMOS - CHANCE, drawn as three points on one axis.

The alignment is the app's status display and its central motif at once
(docs/old/DESIGN.md sections 6.3, 18.3): each point resolves in the ritual's fixed
order, and the connecting line only reaches as far as the last resolved
point. It reports state; it never advances itself.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import RenderResult
from textual.reactive import reactive
from textual.widget import Widget

from syzygy.tui import palette

RESOLVED = "●"
PENDING = "○"

_LABEL_STYLE = palette.MUTED
_RESOLVED_STYLE = palette.BONE
_PENDING_STYLE = palette.DIM
_CHANCE_STYLE = f"bold {palette.EMBER}"
_LINE_STYLE = palette.RULE


class AlignmentWidget(Widget):
    """Three named points, lit as they resolve."""

    DEFAULT_CSS = """
    AlignmentWidget {
        width: 1fr;
        height: 2;
    }
    """

    self_resolved: reactive[bool] = reactive(False)
    cosmos_resolved: reactive[bool] = reactive(False)
    chance_resolved: reactive[bool] = reactive(False)

    def render(self) -> RenderResult:
        width = max(self.size.width, 24)
        left = 1
        middle = width // 2
        right = width - 2

        labels = [" "] * width
        for start, label in ((left, "SELF"), (middle - 3, "COSMOS"), (right - 5, "CHANCE")):
            start = max(0, min(start, width - len(label)))
            labels[start : start + len(label)] = list(label)

        axis = Text()
        axis.append("".join(labels).rstrip(), style=_LABEL_STYLE)
        axis.append("\n")

        def point(resolved: bool, resolved_style: str) -> tuple[str, str]:
            return (RESOLVED, resolved_style) if resolved else (PENDING, _PENDING_STYLE)

        def span(length: int, resolved: bool) -> tuple[str, str]:
            # Solid only as far as the ritual has actually got.
            return (("─" if resolved else "·") * length, _LINE_STYLE)

        segments = [
            point(self.self_resolved, _RESOLVED_STYLE),
            span(middle - left - 1, self.cosmos_resolved),
            point(self.cosmos_resolved, _RESOLVED_STYLE),
            span(right - middle - 1, self.chance_resolved),
            point(self.chance_resolved, _CHANCE_STYLE),
        ]

        axis.append(" ")
        for text, style in segments:
            axis.append(text, style=style)
        return axis
