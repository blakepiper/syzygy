"""Bundled images as terminal half-block pixels.

Shared by the card illustrations (`card_art`) and the brand assets
(`brand`). Both need the same three things - the source's aspect ratio,
the largest aspect-correct size that fits a given cell box, and a cached
render - and the sizing arithmetic is subtle enough (see below) that
having two copies of it is how one of them ends up wrong.

**Sizes are in image pixels, not cells.** `Pixels.from_image`'s `resize`
takes `(width, height)` in pixels, and the half-cell renderer packs *two*
image rows into every cell row, so `resize=(22, 17)` occupies 22 columns
by 9 rows, not 17.

That also makes the aspect arithmetic simpler than it first looks. A
terminal cell is roughly twice as tall as it is wide, and each cell row
holds two stacked image pixels, so an image pixel is approximately square
on screen: the source's own width:height ratio goes into `resize`
directly. Correcting for the 1:2 cell ratio *as well* squashes the image
to half its proper height - which is exactly the bug M11.5 fixed.

Rendering is `rich_pixels` half-blocks in ANSI truecolor, not a terminal
graphics protocol (Kitty/iTerm2/Sixel), so it works in any terminal
Textual already supports, at the cost of fidelity. Fully transparent
pixels render as blank cells with no background, so a keyed-out image
lets the terminal's own background show through.
"""

from __future__ import annotations

from functools import cache
from importlib import resources

from PIL import Image
from rich.text import Text
from rich_pixels import Pixels

from syzygy.tui import palette

#: The smallest art worth drawing. Below this an illustration is an
#: unreadable smear and whatever text accompanies it carries the meaning
#: better.
MIN_COLUMNS = 10
MIN_CELL_ROWS = 6

#: Half-cell art stops gaining detail long before it stops costing render
#: time, and an image that fills a wide terminal edge to edge reads as a
#: screenshot rather than an illustration.
MAX_COLUMNS = 40

#: Quantise requested widths before they reach `render_pixels`, whose
#: cache is keyed on the result. A widget dragged across a hundred
#: intermediate widths would otherwise decode and resize the source a
#: hundred times and keep every one of them alive in the cache.
WIDTH_STEP = 2

#: The package every path here is resolved against. `importlib.resources`
#: rather than a filesystem path, so this keeps working from a zipped
#: wheel and not just an editable checkout.
_RESOURCE_PACKAGE = "syzygy.resources"


@cache
def aspect_ratio(relative_path: str) -> float | None:
    """`height / width` of the bundled image at `relative_path`, or `None`
    if there is no such resource. Opens the file only to read its
    header."""
    try:
        package_files = resources.files(_RESOURCE_PACKAGE)
        with package_files.joinpath(relative_path).open("rb") as raw, Image.open(raw) as image:
            width, height = image.size
    except (FileNotFoundError, OSError):
        return None
    return height / width


def fit_size(
    relative_path: str,
    columns: int,
    cell_rows: int,
    *,
    max_columns: int = MAX_COLUMNS,
) -> tuple[int, int] | None:
    """The largest aspect-correct `resize` argument for `relative_path`
    that fits in `columns` x `cell_rows` terminal cells, or `None` if the
    space is too small to be worth drawing in.

    Width is always the free variable and the height always follows from
    it, so the ratio is never traded away to make something fit. If no
    width down to `MIN_COLUMNS` produces a short enough image, the answer
    is `None` - a squashed image is worse than whatever the caller falls
    back to.
    """
    ratio = aspect_ratio(relative_path)
    if ratio is None:
        return None
    if columns < MIN_COLUMNS or cell_rows < MIN_CELL_ROWS:
        return None

    width = (min(columns, max_columns) // WIDTH_STEP) * WIDTH_STEP
    while width >= MIN_COLUMNS:
        height = round(width * ratio)
        if -(-height // 2) <= cell_rows:  # ceil: two image rows per cell row
            return width, height
        width -= WIDTH_STEP
    return None


def fit_braille_size(
    relative_path: str,
    columns: int,
    cell_rows: int,
    *,
    max_columns: int = MAX_COLUMNS,
) -> tuple[int, int] | None:
    """Fit line art as terminal cells for a 2×4-dot Braille renderer.

    Half-block pixels give a cell only two vertical samples. That is ideal
    for colour illustrations, but dense monochrome line art collapses into
    a grey mass at mascot sizes. Braille carries eight binary samples per
    cell and preserves the drawing's negative space.
    """
    ratio = aspect_ratio(relative_path)
    if ratio is None or columns < MIN_COLUMNS or cell_rows < MIN_CELL_ROWS:
        return None
    width = (min(columns, max_columns) // WIDTH_STEP) * WIDTH_STEP
    while width >= MIN_COLUMNS:
        rows = round(width * ratio / 2)
        if rows <= cell_rows:
            return width, max(1, rows)
        width -= WIDTH_STEP
    return None


@cache
def render_pixels(relative_path: str, size: tuple[int, int]) -> Pixels | None:
    """The bundled image at `relative_path` rendered as half-block pixels
    at `size` = (image width, image height), or `None` if there is no such
    resource.

    Cached per `(path, size)`: decoding and resizing the source on every
    redraw would be wasted work. Callers should size through `fit_size`,
    which quantises widths so a resize drag cannot fill this cache with
    near-identical entries.
    """
    try:
        package_files = resources.files(_RESOURCE_PACKAGE)
        with package_files.joinpath(relative_path).open("rb") as raw, Image.open(raw) as image:
            image.load()
            return Pixels.from_image(image, resize=size)
    except (FileNotFoundError, OSError):
        return None


_BRAILLE_BITS = (
    (0, 0, 0x01),
    (0, 1, 0x02),
    (0, 2, 0x04),
    (1, 0, 0x08),
    (1, 1, 0x10),
    (1, 2, 0x20),
    (0, 3, 0x40),
    (1, 3, 0x80),
)


@cache
def render_braille(relative_path: str, size: tuple[int, int]) -> Text | None:
    """Render monochrome line art into a `size`-cell Braille canvas."""
    columns, rows = size
    try:
        package_files = resources.files(_RESOURCE_PACKAGE)
        with package_files.joinpath(relative_path).open("rb") as raw, Image.open(raw) as image:
            rgba = image.convert("RGBA").resize(
                (columns * 2, rows * 4), Image.Resampling.LANCZOS
            )
    except (FileNotFoundError, OSError):
        return None

    pixel = rgba.load()
    lines: list[str] = []
    for cell_y in range(rows):
        chars: list[str] = []
        for cell_x in range(columns):
            bits = 0
            for dx, dy, bit in _BRAILLE_BITS:
                red, green, blue, alpha = pixel[cell_x * 2 + dx, cell_y * 4 + dy]
                luminance = (red * 299 + green * 587 + blue * 114) // 1000
                if luminance * alpha // 255 >= 105:
                    bits |= bit
            chars.append(chr(0x2800 + bits) if bits else " ")
        lines.append("".join(chars).rstrip())
    return Text("\n".join(lines), style=palette.ACCENT)
