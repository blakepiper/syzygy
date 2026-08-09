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

from enum import StrEnum

from rich.align import Align
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
        fallback = Text(self._fallback_text, style=palette.ACCENT, justify="center")
        if not size.width or not size.height:
            return fallback
        try:
            fitted = pixel_art.fit_size(
                self._relative_path, size.width, size.height, max_columns=self._max_columns
            )
            pixels = (
                None if fitted is None else pixel_art.render_pixels(self._relative_path, fitted)
            )
        except Exception:  # noqa: BLE001 - decoration must never break a screen
            # `pixel_art` already turns a missing or unreadable file into
            # `None`; this is the belt to that braces. A brand asset that
            # cannot be decoded degrades to its text fallback, exactly as
            # `SilentTheme` degrades a missing audio device (M17.3c).
            return fallback
        if pixels is None:
            return fallback
        # Centred inside the renderable rather than by `content-align`
        # (M17.6b): the art renders at whatever width `fit_size` chose,
        # which is rarely the full width of the box it was given.
        return Align.center(pixels)


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


class MascotState(StrEnum):
    """What the mascot is reacting to (M17.3b).

    Three states, tied to semantic events the application already emits -
    not a new animation vocabulary, and not new artwork: there is one
    mascot PNG (`docs/BRAND_ASSETS.md`) and each state is a treatment of
    it, so adding a state costs a CSS rule rather than an asset.
    """

    #: Nothing has happened yet today. The default.
    WAITING = "waiting"
    #: Chance is entering the alignment.
    DRAWING = "drawing"
    #: Today's reading exists and is finished.
    COMPLETE = "complete"


class Mascot(BrandImage):
    """The hierophant at the wheel."""

    def __init__(self, *, id: str | None = None, classes: str | None = None) -> None:
        super().__init__(MASCOT_PATH, id=id, classes=classes)
        #: `None` until a screen says otherwise: a mascot that is only
        #: decoration (the opening sequence, the welcome copy) has no
        #: state to be in, and giving it one would mean the startup logo
        #: and the startup mascot disagreed about how the launch is going.
        self.state: MascotState | None = None

    def on_mount(self) -> None:
        super().on_mount()
        self._apply_state()

    def _content(self) -> RenderableType:
        """Render the detailed monochrome mascot as crisp Braille line art."""
        size = self.size
        if not size.width or not size.height:
            return Text("")
        try:
            fitted = pixel_art.fit_braille_size(
                MASCOT_PATH, size.width, size.height, max_columns=self._max_columns
            )
            art = None if fitted is None else pixel_art.render_braille(MASCOT_PATH, fitted)
        except Exception:  # noqa: BLE001 - decorative fallback
            return Text("")
        return Text("") if art is None else Align.center(art)

    def set_state(self, state: MascotState) -> None:
        """Move to `state`, as a class `syzygy.tcss` styles."""
        self.state = state
        self._apply_state()

    def _apply_state(self) -> None:
        for candidate in MascotState:
            self.set_class(candidate is self.state, f"-mascot-{candidate.value}")
