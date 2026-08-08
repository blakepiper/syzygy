"""Development-only affordances (M11.6).

Nothing in here is part of the ritual. It exists so the reveal and reading
flow can be exercised repeatedly during development instead of once per
day, and every entry point is gated on `dev_mode_enabled()` so a normal
run cannot reach it - not by a stray keypress, not by a mistyped command.

**Why this needs saying out loud.** `AGENTS.md` states two invariants that
a "reroll" button sounds like a violation of:

- the card is committed to storage immediately after the draw, before any
  LLM call, and a failed or retried interpretation must never redraw it;
- there is exactly one canonical reading per
  `(profile_id, consultation_local_date)`, enforced by the database.

`discard_todays_reading` keeps both. It does not mutate a drawn card, does
not relax `ALLOWED_TRANSITIONS`, and does not write a second row for the
day: it *deletes* the day's reading outright, after which the ordinary
`draw_todays_reading` path runs from the beginning and draws a genuinely
new card through `syzygy.sortes`. At every moment there is either one
reading for the date or none, and the `UNIQUE` constraint is still the
thing enforcing that.

What it is, plainly, is destructive: it throws away a real reading and a
real interpretation. That is why it is dev-gated and why both entry points
confirm first.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Mapping

#: Set to any of these (case-insensitive) to turn dev affordances on.
_TRUTHY = frozenset({"1", "true", "yes", "on"})

DEV_MODE_ENV_VAR = "SYZYGY_DEV"


def dev_mode_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Is `SYZYGY_DEV` set to something affirmative?

    Read at call time rather than import time so a test can set it around
    a single case, and so the TUI reflects the environment it was actually
    launched with.
    """
    value = (environ if environ is not None else os.environ).get(DEV_MODE_ENV_VAR, "")
    return value.strip().lower() in _TRUTHY


def discard_todays_reading(
    conn: sqlite3.Connection, profile_id: str, consultation_local_date: str
) -> bool:
    """Delete `profile_id`'s reading for `consultation_local_date`.

    Returns True if a reading was actually deleted. Callers are expected
    to follow this with the normal `draw_todays_reading`, which will then
    prepare and draw a fresh reading exactly as it does on any other first
    consultation of a day - see the module docstring on why this is a
    delete rather than a redraw.
    """
    if not dev_mode_enabled():
        raise RuntimeError(
            f"discard_todays_reading is a development affordance; "
            f"set {DEV_MODE_ENV_VAR}=1 to enable it"
        )
    deleted = conn.execute(
        "DELETE FROM readings WHERE profile_id = ? AND consultation_local_date = ?",
        (profile_id, consultation_local_date),
    ).rowcount
    return deleted > 0
