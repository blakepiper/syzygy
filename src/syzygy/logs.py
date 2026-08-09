"""Nothing a dependency logs may land on top of the ritual.

A full-screen terminal application owns the screen. Anything that writes
to stdout or stderr while Textual is drawing paints over it - the frame is
not redrawn, so the text stays there, in whatever cells it happened to
land on, until the next full repaint. What was actually appearing over the
Oracle was this:

    INFO: HTTP Request: GET http://127.0.0.1:.../health "503 Service …"

`httpx` logs every request at INFO, which is normally invisible: with no
handler on the root logger, `logging.lastResort` only emits WARNING and
above. But `just_playback` - the theme player's audio library - calls
`logging.basicConfig(level=INFO, format="%(levelname)s: %(message)s")` at
*import* time. Importing it therefore hands the root logger a stderr
handler at INFO and turns every library's debug chatter into visible
output. The health polling of a local model server starting up is simply
the loudest example; the leak is general.

The fix is to configure the root logger first, once, at the entry points
(`syzygy.cli.main` and `syzygy.tui.app.run`). `logging.basicConfig` is a
no-op when the root logger already has a handler, so a dependency that
calls it later - now or in some future version - changes nothing. This is
also why the handler is installed rather than the root level merely being
set: a level can be overwritten, an existing handler cannot be
un-noticed.

Silencing is not discarding. `SYZYGY_LOG_FILE=/path/to/log` routes
everything to that file at INFO instead, which is how you read the health
poll of a local server that is refusing to come up without a terminal
full of it.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Final

__all__ = ["LOG_FILE_ENV_VAR", "NOISY_LOGGERS", "quiet_library_logging"]

#: Where to send library logging instead of nowhere. Unset in normal use.
LOG_FILE_ENV_VAR: Final = "SYZYGY_LOG_FILE"

#: Loggers pinned explicitly as well as by the root level, because these
#: are the ones a dependency is most likely to raise on its own. `httpx`
#: is the one that actually reached the screen; the rest are the same
#: class of thing and cost a line each.
NOISY_LOGGERS: Final = (
    "httpx",
    "httpcore",
    "urllib3",
    "kerykeion",
    "just_playback",
    "asyncio",
    "markdown_it",
)

#: Marks the handler this module installed, so a second call replaces its
#: own work rather than stacking another handler on the root logger.
_MARKER: Final = "_syzygy_quiet"


def quiet_library_logging(log_path: Path | str | None = None) -> None:
    """Take the terminal away from the logging system. Never raises.

    Call once, as early as an entry point can. `log_path` (or
    `SYZYGY_LOG_FILE`) diverts records to a file at INFO; with neither,
    records below WARNING are never emitted at all.
    """
    root = logging.getLogger()

    for existing in list(root.handlers):
        if getattr(existing, _MARKER, False) or _writes_to_terminal(existing):
            root.removeHandler(existing)

    destination = log_path if log_path is not None else os.environ.get(LOG_FILE_ENV_VAR)
    to_file = _file_handler(destination) if destination else None
    handler: logging.Handler = to_file if to_file is not None else logging.NullHandler()
    level = logging.INFO if to_file is not None else logging.WARNING
    setattr(handler, _MARKER, True)

    root.addHandler(handler)
    root.setLevel(level)
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(level)


def _writes_to_terminal(handler: logging.Handler) -> bool:
    """Whether this handler paints on the screen Syzygy is drawing on.

    Deliberately narrow: a `StreamHandler` over anything else - a
    `StringIO`, a file, pytest's capture - is somebody else's arrangement
    and is left alone.
    """
    if not isinstance(handler, logging.StreamHandler):
        return False
    stream = getattr(handler, "stream", None)
    return stream is sys.stdout or stream is sys.stderr


def _file_handler(destination: Path | str) -> logging.Handler | None:
    """A file handler for `destination`, or `None` if it cannot be opened.

    An unwritable path means the same thing as no path: quiet. Diagnostics
    that cannot be written are not worth failing a launch over.
    """
    try:
        path = Path(destination).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.FileHandler(path, encoding="utf-8")
    except OSError:
        return None
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    return handler
