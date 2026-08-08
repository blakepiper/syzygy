"""The palette has two homes; they must agree (M12.1).

`syzygy.tcss` styles the screens, `syzygy.tui.palette` styles the Rich
`Text`/`Style` objects that widgets build in Python. Neither can read the
other, and before M12.1 the Python side was a scattering of hex literals -
which is how the gold accent survived being "removed" from the
stylesheet in three separate widgets.
"""

from __future__ import annotations

import re
from importlib import resources

from syzygy.tui import palette

_DECLARATION = re.compile(r"^\$([\w-]+):\s*(#[0-9a-fA-F]{3,8})\s*;", re.MULTILINE)


def tcss_variables() -> dict[str, str]:
    source = resources.files("syzygy.tui").joinpath("syzygy.tcss").read_text()
    return {name: value.lower() for name, value in _DECLARATION.findall(source)}


def test_every_shared_colour_matches_the_stylesheet():
    declared = tcss_variables()
    for name, value in palette.TCSS_EQUIVALENTS.items():
        assert name in declared, f"${name} is missing from syzygy.tcss"
        assert declared[name] == value.lower(), (
            f"${name} is {declared[name]} in syzygy.tcss but {value} in palette.py"
        )


def test_the_stylesheet_declares_no_colour_the_palette_has_not_heard_of():
    """A new `$syz-*` colour should be added to both, or the Python side
    will quietly drift again."""
    undeclared = set(tcss_variables()) - set(palette.TCSS_EQUIVALENTS)
    assert undeclared == set(), f"add these to palette.TCSS_EQUIVALENTS: {sorted(undeclared)}"


def test_no_widget_hardcodes_a_colour():
    """The point of `palette.py`: changing a colour is one edit, not a
    hunt through every widget that builds a Rich style."""
    hex_literal = re.compile(r'"#[0-9a-fA-F]{6}"')
    offenders = []
    for module in resources.files("syzygy.tui").joinpath("widgets").iterdir():
        if module.name.endswith(".py"):
            for number, line in enumerate(module.read_text().splitlines(), start=1):
                if hex_literal.search(line):
                    offenders.append(f"widgets/{module.name}:{number}: {line.strip()}")
    assert offenders == [], "\n".join(offenders)


def test_the_gold_accent_is_gone():
    """The literal request: no more 'piss yellow'. Comments are stripped
    first - the palette comment names the old colour deliberately, to say
    what changed and why."""
    source = resources.files("syzygy.tui").joinpath("syzygy.tcss").read_text()
    rules = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    assert "#cf9b3f" not in rules
    assert "$syz-gold" not in rules


def test_the_accent_is_brighter_than_body_text():
    """It has to out-rank `$syz-bone`, or emphasis reads as noise."""

    def luminance(colour: str) -> float:
        red, green, blue = (int(colour[index : index + 2], 16) for index in (1, 3, 5))
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue

    assert luminance(palette.ACCENT) > luminance(palette.BONE)
    assert luminance(palette.BONE) > luminance(palette.MUTED)
    assert luminance(palette.MUTED) > luminance(palette.DIM)
    assert luminance(palette.DIM) > luminance(palette.FIELD)
