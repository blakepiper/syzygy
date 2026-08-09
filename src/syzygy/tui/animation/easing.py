"""Easing curves (`docs/animation.md` section 6).

Four curves, each with a job:

    ease_out_cubic     movement
    ease_out_back      opening / appearing (with a modest overshoot)
    ease_in_cubic      closing / disappearing
    ease_in_out_quad   reorganization

`linear` exists for the cases where a curve would be wrong rather than
merely unfashionable - a typewriter reveal, a glyph cycle, a particle's
age. "Linear should rarely be used for visible UI *movement*" is not the
same as "never call it".

Every function takes and returns a float. Input is clamped to `[0, 1]`;
output is not, because `ease_out_back` overshoots past 1 on purpose and
clamping it would silently delete the overshoot.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final, TypeAlias

Easing: TypeAlias = Callable[[float], float]

#: The overshoot constant from the standard `easeOutBack`. About one
#: terminal cell of overshoot on a 10-cell move, which is what
#: `docs/animation.md` section 13 asks for - the curve peaks near 1.10.
_BACK_C1: Final = 1.70158
_BACK_C3: Final = _BACK_C1 + 1.0


def _clamp(t: float) -> float:
    return 0.0 if t < 0.0 else 1.0 if t > 1.0 else t


def linear(t: float) -> float:
    return _clamp(t)


def ease_out_cubic(t: float) -> float:
    t = _clamp(t)
    return 1.0 - (1.0 - t) ** 3


def ease_in_cubic(t: float) -> float:
    t = _clamp(t)
    return t**3


def ease_in_out_quad(t: float) -> float:
    t = _clamp(t)
    if t < 0.5:
        return 2.0 * t * t
    return 1.0 - ((-2.0 * t + 2.0) ** 2) / 2.0


def ease_out_back(t: float) -> float:
    """Overshoots past 1 around three-quarters through, then settles.

    Deliberately not clamped: the returned value is fed to an
    interpolation, and a value above 1 is how the element gets past its
    destination before returning to it.
    """
    t = _clamp(t)
    return 1.0 + _BACK_C3 * (t - 1.0) ** 3 + _BACK_C1 * (t - 1.0) ** 2


#: By name, for settings files and debugging. Not a plugin point - the
#: four curves above are the vocabulary, and adding a fifth should be a
#: deliberate change to `docs/animation.md` section 6, not a config value.
EASINGS: Final[dict[str, Easing]] = {
    "linear": linear,
    "ease_out_cubic": ease_out_cubic,
    "ease_in_cubic": ease_in_cubic,
    "ease_in_out_quad": ease_in_out_quad,
    "ease_out_back": ease_out_back,
}


def lerp(start: float, end: float, progress: float) -> float:
    """Interpolate, without clamping `progress` - see `ease_out_back`."""
    return start + (end - start) * progress
