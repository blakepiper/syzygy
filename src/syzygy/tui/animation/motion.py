"""How much motion this run is allowed (`docs/animation.md` section 34).

Three levels, persisted as a section of `AppPaths.settings_path`:

    full      the whole vocabulary
    reduced   no shake, no particles, no large movement, no overshoot,
              and shorter transitions - but every state change still gets
              visible feedback
    off       final states, immediately

`off` is not "skip the animations and hope". It is a hard guarantee that
`Animator.run` finishes a timeline synchronously before returning, so the
screen that triggered it reaches exactly the state it would have reached
at the end of the animation. `tests/tui/test_animation_off.py` holds that
guarantee to the fire.

There is no terminal escape sequence or termcap entry for "the user
prefers reduced motion", so the closest available signal is the
environment: `SYZYGY_ANIMATIONS` (this application's own, and the only one
that can select all three levels), then the `NO_MOTION` /
`PREFERS_REDUCED_MOTION` conventions that other terminal programs have
settled on. Precedence, highest first:

    1. SYZYGY_ANIMATIONS=full|reduced|off   this run, explicitly
    2. the saved setting                    this user, deliberately
    3. NO_MOTION / PREFERS_REDUCED_MOTION   this machine, probably

A saved `full` therefore beats a machine-wide `NO_MOTION`, because
choosing the level in this application is a more specific statement than
a variable exported in a shell profile years ago.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from syzygy.settings import ANIMATION_SECTION, load_section, save_section

__all__ = [
    "ANIMATION_SECTION",
    "LEVEL_ENV_VAR",
    "MotionLevel",
    "MotionSettings",
    "SPEED_ENV_VAR",
    "load_motion",
    "next_level",
    "resolve_motion",
    "save_motion_level",
]

LEVEL_ENV_VAR: Final = "SYZYGY_ANIMATIONS"

#: The debug slow-motion multiplier (`docs/animation.md` section 39).
#: `SYZYGY_ANIMATION_SPEED=0.25` makes everything take four times as long,
#: which is the only practical way to inspect a 180 ms composite by eye.
SPEED_ENV_VAR: Final = "SYZYGY_ANIMATION_SPEED"

#: Environment conventions other terminal programs use for "this machine
#: prefers reduced motion". Neither is a standard; both are cheap to
#: honour and free to ignore.
_REDUCED_ENV_VARS: Final = ("NO_MOTION", "PREFERS_REDUCED_MOTION")

_TRUTHY: Final = frozenset({"1", "true", "yes", "on"})

#: What `reduced` does to a duration. Shorter, not instant - the point of
#: reduced motion is to keep the feedback and drop the spectacle.
REDUCED_DURATION_SCALE: Final = 0.55

#: Sane bounds on the debug multiplier. A speed of 0 would mean an
#: infinite animation, and 20x is already indistinguishable from `off`.
MIN_SPEED: Final = 0.05
MAX_SPEED: Final = 20.0


class MotionLevel(StrEnum):
    FULL = "full"
    REDUCED = "reduced"
    OFF = "off"


#: The order `[F2]` cycles through in the interface.
_CYCLE: Final = (MotionLevel.FULL, MotionLevel.REDUCED, MotionLevel.OFF)


def next_level(level: MotionLevel) -> MotionLevel:
    return _CYCLE[(_CYCLE.index(level) + 1) % len(_CYCLE)]


@dataclass(frozen=True)
class MotionSettings:
    """The motion budget, as one immutable value.

    Everything that wants to know "may I shake this?" or "how long is a
    Level 2 transition here?" asks this object rather than re-reading a
    setting or checking an environment variable of its own.
    """

    level: MotionLevel = MotionLevel.FULL
    speed: float = 1.0

    @property
    def enabled(self) -> bool:
        """Whether anything animates at all."""
        return self.level is not MotionLevel.OFF

    @property
    def allows_shake(self) -> bool:
        return self.level is MotionLevel.FULL

    @property
    def allows_particles(self) -> bool:
        return self.level is MotionLevel.FULL

    @property
    def allows_large_motion(self) -> bool:
        """Movement beyond a cell or two, and overshoot past a target."""
        return self.level is MotionLevel.FULL

    @property
    def allows_continuous(self) -> bool:
        """Whether a frame loop may run for as long as something is
        visibly moving - the Wheel's rim, and nothing else."""
        return self.level is not MotionLevel.OFF

    @property
    def time_scale(self) -> float:
        """Multiplier applied to every duration by `Animator.run`.

        One number for both jobs: `reduced` shortens transitions, and the
        debug speed stretches them. Applied once, centrally, so no
        primitive has to remember to scale itself.
        """
        if self.level is MotionLevel.OFF:
            return 0.0
        scale = REDUCED_DURATION_SCALE if self.level is MotionLevel.REDUCED else 1.0
        return scale / _clamp_speed(self.speed)


def _clamp_speed(speed: float) -> float:
    return min(MAX_SPEED, max(MIN_SPEED, speed))


def _parse_level(raw: str | None) -> MotionLevel | None:
    if raw is None:
        return None
    try:
        return MotionLevel(raw.strip().lower())
    except ValueError:
        return None


def _parse_speed(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        return _clamp_speed(float(raw))
    except ValueError:
        return None


def load_motion(settings_path: Path | None) -> MotionLevel | None:
    """The saved level, or `None` if the user has never chosen one.

    `None` rather than a default, so `resolve_motion` can tell "chose
    full" apart from "said nothing" - only the second defers to a
    machine-wide reduced-motion signal.
    """
    if settings_path is None:
        return None
    return _parse_level(load_section(settings_path, ANIMATION_SECTION).get("level"))


def save_motion_level(settings_path: Path, level: MotionLevel) -> None:
    save_section(settings_path, ANIMATION_SECTION, {"level": level.value})


def resolve_motion(
    settings_path: Path | None = None, environ: Mapping[str, str] | None = None
) -> MotionSettings:
    """The motion budget for this run - see the module docstring for the
    precedence. Never raises: an unreadable settings file, an unparseable
    level, or a nonsense speed all mean "no preference expressed"."""
    env = environ if environ is not None else os.environ

    level = _parse_level(env.get(LEVEL_ENV_VAR))
    if level is None:
        level = load_motion(settings_path)
    if level is None:
        prefers_reduced = any(
            env.get(name, "").strip().lower() in _TRUTHY for name in _REDUCED_ENV_VARS
        )
        level = MotionLevel.REDUCED if prefers_reduced else MotionLevel.FULL

    return MotionSettings(level=level, speed=_parse_speed(env.get(SPEED_ENV_VAR)) or 1.0)
