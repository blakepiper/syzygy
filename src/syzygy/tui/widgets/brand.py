"""Syzygy's logo and mascot, rendered into terminal cells (M12.2).

`src/syzygy/resources/brand/` holds PNGs, not the SVGs at the repository
root: a terminal cannot display SVG, and rasterizing at runtime would mean
a rendering dependency (cairosvg/librsvg) for two images that never
change. The SVGs stay the editable source and the PNGs are generated from
them at author time - see `docs/BRAND_ASSETS.md` for the command.

Both are keyed to transparency so the terminal's own background shows
through rather than a near-black rectangle. Sizing and rendering are
`pixel_art`'s, shared with the card illustrations; read its docstring
before changing a size here.
"""

from __future__ import annotations

from rich.console import RenderableType
from rich.text import Text
from textual.widgets import Static

from syzygy.tui import palette
from syzygy.tui.widgets import pixel_art

LOGO_PATH = "brand/logo.png"
MASCOT_PATH = "brand/mascot.png"

#: Fallback wordmark. Shown when the terminal is too small for the logo
#: image, and it is also what the title bar uses - pixel art needs more
#: rows than a one-line bar has.
WORDMARK = "SYZYGY"

#: The logo is a wide wordmark (4:1), so it is width-limited rather than
#: height-limited and can go wider than `pixel_art.MAX_COLUMNS`, which is
#: tuned for portrait card art.
MAX_LOGO_COLUMNS = 64

#: An ASCII wordmark for when the image will not fit. Kept as a literal
#: rather than generated, so it never depends on a font being installed.
ASCII_WORDMARK = r"""
 ███████ ██    ██ ███████ ██    ██  ██████  ██    ██
 ██       ██  ██     ███   ██  ██  ██        ██  ██
 ███████    ██      ███     ████   ██  ███     ██
      ██    ██     ███       ██    ██   ██     ██
 ███████    ██    ███████    ██     ██████     ██
"""


class BrandImage(Static):
    """A bundled brand PNG, sized to whatever box it is given.

    Falls back to `fallback_text` when the box is too small for a legible
    image, and to nothing at all if the resource is missing - a brand
    asset is decoration, and must never be the reason a screen fails to
    render.
    """

    def __init__(
        self,
        relative_path: str,
        *,
        fallback_text: str = "",
        max_columns: int = pixel_art.MAX_COLUMNS,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        self._relative_path = relative_path
        self._fallback_text = fallback_text
        self._max_columns = max_columns
        super().__init__("", id=id, classes=classes)

    def on_mount(self) -> None:
        self.update(self._content())

    def on_resize(self) -> None:
        self.update(self._content())

    def _content(self) -> RenderableType:
        size = self.size
        if not size.width or not size.height:
            return Text(self._fallback_text, style=palette.ACCENT)
        fitted = pixel_art.fit_size(
            self._relative_path, size.width, size.height, max_columns=self._max_columns
        )
        if fitted is None:
            return Text(self._fallback_text, style=palette.ACCENT)
        pixels = pixel_art.render_pixels(self._relative_path, fitted)
        if pixels is None:
            return Text(self._fallback_text, style=palette.ACCENT)
        return pixels


class Logo(BrandImage):
    """The SYZYGY wordmark."""

    def __init__(self, *, id: str | None = None, classes: str | None = None) -> None:
        super().__init__(
            LOGO_PATH,
            fallback_text=ASCII_WORDMARK,
            max_columns=MAX_LOGO_COLUMNS,
            id=id,
            classes=classes,
        )


class Mascot(BrandImage):
    """The hierophant at the wheel."""

    def __init__(self, *, id: str | None = None, classes: str | None = None) -> None:
        super().__init__(MASCOT_PATH, id=id, classes=classes)
