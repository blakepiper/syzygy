"""Card art: a drawn card's id -> its Thoth deck illustration.

`src/syzygy/resources/art/` holds the same status as `thoth_deck.yaml` -
reference data, read via `importlib.resources` rather than assumed to be a
real filesystem path, so this keeps working from a zipped wheel install
and not just an editable checkout.

Rendering is terminal half-block pixels via `rich_pixels`
(`HalfcellRenderer`, ANSI truecolor) - not a terminal graphics protocol
(Kitty/iTerm2/Sixel), so it works in any terminal Textual already
supports, at the cost of image fidelity. That tradeoff, and the exact
on-screen size, is expected to be revisited once styling work starts;
this module's job for now is only "the correct card's art, somewhere on
screen."
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


@cache
def render_card_pixels(card_id: str, size: tuple[int, int]) -> Pixels | None:
    """`card_id`'s illustration rendered as terminal half-block pixels at
    `size` = (columns, rows), or `None` if no art is mapped for `card_id`.

    Cached per `(card_id, size)` - there are only 78 cards, and decoding
    and resizing the source PNG on every redraw (e.g. reopening the same
    day's reading) would be wasted work.
    """
    relative_path = art_relative_path(card_id)
    if relative_path is None:
        return None
    package_files = resources.files("syzygy.resources")
    with package_files.joinpath("art", relative_path).open("rb") as raw, Image.open(raw) as image:
        image.load()
        return Pixels.from_image(image, resize=size)
