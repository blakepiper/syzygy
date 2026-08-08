"""Card art: a drawn card's id -> its Thoth deck illustration.

`src/syzygy/resources/art/` holds the same status as `thoth_deck.yaml` -
reference data, read via `importlib.resources` rather than assumed to be a
real filesystem path, so this keeps working from a zipped wheel install
and not just an editable checkout.

This module is only the card-id -> file mapping. Everything about
rendering an image into terminal cells - the aspect arithmetic, the size
limits, the cache - lives in `pixel_art`, which the brand assets share;
read its docstring before changing any size here.
"""

from __future__ import annotations

from syzygy.tui.widgets import pixel_art
from syzygy.tui.widgets.pixel_art import Pixels

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


def card_aspect_ratio(card_id: str) -> float | None:
    """`height / width` of `card_id`'s source illustration, or `None` if
    no art is mapped for it."""
    relative_path = art_relative_path(card_id)
    if relative_path is None:
        return None
    return pixel_art.aspect_ratio(f"art/{relative_path}")


def art_size_for(card_id: str, columns: int, cell_rows: int) -> tuple[int, int] | None:
    """The largest aspect-correct `resize` argument for `card_id` that fits
    in `columns` x `cell_rows` terminal cells, or `None` if the space is
    too small to be worth drawing in. See `pixel_art.fit_size`."""
    relative_path = art_relative_path(card_id)
    if relative_path is None:
        return None
    return pixel_art.fit_size(f"art/{relative_path}", columns, cell_rows)


def render_card_pixels(card_id: str, size: tuple[int, int]) -> Pixels | None:
    """`card_id`'s illustration rendered as terminal half-block pixels at
    `size` = (image width, image height), or `None` if no art is mapped
    for `card_id`. Sizes should come from `art_size_for`."""
    relative_path = art_relative_path(card_id)
    if relative_path is None:
        return None
    return pixel_art.render_pixels(f"art/{relative_path}", size)
