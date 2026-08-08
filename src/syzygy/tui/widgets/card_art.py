"""Card art: a drawn card's id -> its Thoth deck illustration.

`src/syzygy/resources/art/` holds the same status as `thoth_deck.yaml` -
reference data, read via `importlib.resources` rather than assumed to be a
real filesystem path, so this keeps working from a zipped wheel install
and not just an editable checkout.

Rendering is terminal half-block pixels via `rich_pixels`
(`HalfcellRenderer`, ANSI truecolor) - not a terminal graphics protocol
(Kitty/iTerm2/Sixel), so it works in any terminal Textual already
supports, at the cost of image fidelity.

**The size argument is in image pixels, not cells** (M11.5). `resize`
takes `(width, height)` and the half-cell renderer packs *two* image rows
into each cell row, so `resize=(22, 17)` occupies 22 columns by 9 rows,
not 17. That also makes the aspect arithmetic simpler than it looks: a
terminal cell is roughly twice as tall as it is wide, and each cell row
holds two stacked image pixels, so an image pixel is approximately square
on screen and the source's own width:height ratio can be preserved
directly in `resize`. Correcting for the 1:2 cell ratio *as well* - which
the previous fixed `(22, 17)` did - squashes the art to half its proper
height.
"""

from __future__ import annotations

from functools import cache
from importlib import resources

from PIL import Image
from rich_pixels import Pixels

#: Major arcana card id -> `art/majorarcana/<stem>.png`. Not a simple
#: transform of the id (`the_hanged_man` -> `hangedman`, `the_high_priestess`
#: -> `priestess`, `the_aeon` -> `aeon`, ...), so this is an explicit table
#: rather than a derivation rule.
_MAJOR_ARCANA_FILES: dict[str, str] = {
    "the_fool": "fool",
    "the_magus": "magus",
    "the_high_priestess": "priestess",
    "the_empress": "empress",
    "the_emperor": "emperor",
    "the_hierophant": "hierophant",
    "the_lovers": "lovers",
    "the_chariot": "chariot",
    "adjustment": "adjustment",
    "the_hermit": "hermit",
    "fortune": "fortune",
    "lust": "lust",
    "the_hanged_man": "hangedman",
    "death": "death",
    "art": "art",
    "the_devil": "devil",
    "the_tower": "tower",
    "the_star": "star",
    "the_moon": "moon",
    "the_sun": "sun",
    "the_aeon": "aeon",
    "the_universe": "universe",
}

_MINOR_SUITS = ("wands", "cups", "swords", "disks")

#: The one minor-arcana file that doesn't match its rank word: the Thoth
#: deck's own title for the Ten of Disks is "Wealth" (see `thoth_deck.yaml`
#: `ten_of_disks.display_name`), and that's what the art was exported as.
_TEN_OF_DISKS_FILENAME = "wealth"


def art_relative_path(card_id: str) -> str | None:
    """The path under `art/` for `card_id`'s illustration, or `None` if
    `card_id` isn't recognized (defensive - every id in `thoth_deck.yaml`
    is expected to resolve to a real file)."""
    if card_id in _MAJOR_ARCANA_FILES:
        return f"majorarcana/{_MAJOR_ARCANA_FILES[card_id]}.png"

    if "_of_" not in card_id:
        return None
    rank_or_court, suit = card_id.split("_of_", 1)
    if suit not in _MINOR_SUITS:
        return None
    is_ten_of_disks = (suit, rank_or_court) == ("disks", "ten")
    filename = _TEN_OF_DISKS_FILENAME if is_ten_of_disks else rank_or_court
    return f"{suit}/{filename}.png"


#: The smallest art worth drawing. Below this the illustration is an
#: unreadable smear and the text card carries the meaning better
#: (M11.5c).
MIN_ART_COLUMNS = 10
MIN_ART_CELL_ROWS = 6

#: Half-cell art stops gaining detail long before it stops costing render
#: time, and a card that fills a wide terminal edge to edge reads as a
#: screenshot rather than a card. Caps how large the illustration goes
#: however much room the layout offers.
MAX_ART_COLUMNS = 40

#: Quantise requested widths before they reach `render_card_pixels`, whose
#: cache is keyed on the result. A widget dragged across a hundred
#: intermediate widths would otherwise decode and resize the PNG a hundred
#: times and keep every one of them alive in the cache.
_WIDTH_STEP = 2


@cache
def card_aspect_ratio(card_id: str) -> float | None:
    """`height / width` of `card_id`'s source illustration, or `None` if
    no art is mapped for it. Cached: the deck is fixed, and this opens the
    PNG only to read its header."""
    relative_path = art_relative_path(card_id)
    if relative_path is None:
        return None
    package_files = resources.files("syzygy.resources")
    with package_files.joinpath("art", relative_path).open("rb") as raw, Image.open(raw) as image:
        width, height = image.size
    return height / width


def art_size_for(card_id: str, columns: int, cell_rows: int) -> tuple[int, int] | None:
    """The largest aspect-correct `resize` argument for `card_id` that fits
    in `columns` x `cell_rows` terminal cells, or `None` if the space is
    too small to be worth drawing in.

    Returned in image pixels (see the module docstring): the height is
    about twice the cell rows the art will occupy.

    Width is always the free variable and the height always follows from
    it, so the ratio is never traded away to make something fit. If no
    width down to `MIN_ART_COLUMNS` produces a short enough image, the
    answer is `None` - a squashed illustration is worse than the text card
    the caller falls back to.
    """
    aspect = card_aspect_ratio(card_id)
    if aspect is None:
        return None
    if columns < MIN_ART_COLUMNS or cell_rows < MIN_ART_CELL_ROWS:
        return None

    width = (min(columns, MAX_ART_COLUMNS) // _WIDTH_STEP) * _WIDTH_STEP
    while width >= MIN_ART_COLUMNS:
        height = round(width * aspect)
        if -(-height // 2) <= cell_rows:  # ceil: two image rows per cell row
            return width, height
        width -= _WIDTH_STEP
    return None


@cache
def render_card_pixels(card_id: str, size: tuple[int, int]) -> Pixels | None:
    """`card_id`'s illustration rendered as terminal half-block pixels at
    `size` = (image width, image height), or `None` if no art is mapped
    for `card_id`.

    Cached per `(card_id, size)` - there are only 78 cards, and decoding
    and resizing the source PNG on every redraw (e.g. reopening the same
    day's reading) would be wasted work. Callers should size through
    `art_size_for`, which quantises widths so a resize drag cannot fill
    this cache with near-identical entries.
    """
    relative_path = art_relative_path(card_id)
    if relative_path is None:
        return None
    package_files = resources.files("syzygy.resources")
    with package_files.joinpath("art", relative_path).open("rb") as raw, Image.open(raw) as image:
        image.load()
        return Pixels.from_image(image, resize=size)
