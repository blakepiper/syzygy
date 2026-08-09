"""List rows whose selection is visible without colour (M17.4).

The highlighted row used to be `$syz-panel` on a row of `$syz-field` -
two neighbouring near-blacks, reported as "too subtle to see" on the
profile list. `syzygy.tcss` now inverts the row instead (accent
background, panel-dark text), but a reversal is still a *colour* signal:
it disappears on a monochrome terminal, and it is exactly the kind of
difference some colour-blind viewers have to hunt for.

So the row also carries a glyph. `docs/old/DESIGN.md` section 18's rule -
colour is never the sole carrier of meaning - applied to the one piece of
state every list has.

Every list in the application uses this rather than a bare `ListItem`:
`SyzygyScreen` moves the marker as the highlight moves, so a screen never
has to remember to.
"""

from __future__ import annotations

from textual.widgets import Label, ListItem

#: The marker itself, and the same number of cells' worth of blank for the
#: rows that do not have it - so moving the highlight never re-flows the
#: text of a list.
HIGHLIGHT_MARKER = "▍"
MARKER_WIDTH = 2


class MarkedListItem(ListItem):
    """A `ListItem` that shows `HIGHLIGHT_MARKER` when it is highlighted."""

    def __init__(
        self,
        label: str,
        *,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        self._label = label
        self._marked = False
        super().__init__(
            Label(self._rendered(False), markup=False),
            id=id,
            classes=classes,
            disabled=disabled,
        )

    def _rendered(self, marked: bool) -> str:
        prefix = HIGHLIGHT_MARKER if marked else " "
        return f"{prefix}{' ' * (MARKER_WIDTH - 1)}{self._label}"

    @property
    def label_text(self) -> str:
        """The row's own words, without the marker column."""
        return self._label

    def on_mount(self) -> None:
        self._render_label()

    def set_marked(self, marked: bool) -> None:
        self._marked = marked
        self._render_label()

    def _render_label(self) -> None:
        """Repaint the row, if there is a row yet.

        `ListView` posts `Highlighted` as it is rebuilt, which can reach a
        row whose `Label` has not mounted (or has already gone). The state
        is kept on the item either way and applied when it mounts, so a
        marker is never lost to the order two message queues happened to
        drain in.
        """
        labels = self.query(Label)
        if labels:
            labels.first(Label).update(self._rendered(self._marked))
