"""Nothing a dependency logs may reach the terminal (`syzygy.logs`)."""

from __future__ import annotations

import logging
import sys

import pytest

from syzygy.logs import LOG_FILE_ENV_VAR, quiet_library_logging


@pytest.fixture(autouse=True)
def restore_root_logging():
    """Root logging is global state; put it back exactly as it was."""
    root = logging.getLogger()
    handlers = list(root.handlers)
    level = root.level
    levels = {name: logging.getLogger(name).level for name in ("httpx", "httpcore")}
    yield
    root.handlers[:] = handlers
    root.setLevel(level)
    for name, saved in levels.items():
        logging.getLogger(name).setLevel(saved)


def test_a_dependencys_basic_config_can_no_longer_take_the_terminal(monkeypatch):
    """The actual bug: `just_playback` runs this at import time, and after
    it every `httpx` request printed an INFO line over the interface."""
    monkeypatch.delenv(LOG_FILE_ENV_VAR, raising=False)
    root = logging.getLogger()
    # pytest has already configured root logging, and `basicConfig` does
    # nothing to a root logger that has handlers - which is the whole
    # mechanism under test. Start from the state a real launch starts in.
    root.handlers.clear()

    quiet_library_logging()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)
    assert not any(_writes_to_terminal(handler) for handler in root.handlers)


def test_without_the_guard_that_basic_config_would_have_taken_it(monkeypatch):
    """The control for the test above: the leak is real and this is it."""
    monkeypatch.delenv(LOG_FILE_ENV_VAR, raising=False)
    root = logging.getLogger()
    root.handlers.clear()
    # Root logging is process-wide and another test in this run may have
    # called the guard already; start from a logger nobody has pinned.
    logging.getLogger("httpx").setLevel(logging.NOTSET)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    assert logging.getLogger("httpx").isEnabledFor(logging.INFO)
    assert any(_writes_to_terminal(handler) for handler in root.handlers)


def test_an_existing_terminal_handler_is_removed(monkeypatch):
    """A dependency imported before the entry point runs still cannot
    keep the handler it installed."""
    monkeypatch.delenv(LOG_FILE_ENV_VAR, raising=False)
    # What `basicConfig` would have installed. Added directly because
    # under pytest the root logger already has handlers, which is exactly
    # the condition that makes `basicConfig` a no-op.
    logging.getLogger().addHandler(logging.StreamHandler(sys.stderr))
    assert any(_writes_to_terminal(handler) for handler in logging.getLogger().handlers)

    quiet_library_logging()

    assert not any(_writes_to_terminal(handler) for handler in logging.getLogger().handlers)


def test_it_does_not_touch_handlers_it_did_not_install(monkeypatch):
    """pytest's capture, and anyone else's arrangement, is not ours to
    remove - only handlers writing to the real stdout/stderr are."""
    monkeypatch.delenv(LOG_FILE_ENV_VAR, raising=False)
    import io

    theirs = logging.StreamHandler(io.StringIO())
    root = logging.getLogger()
    root.addHandler(theirs)

    quiet_library_logging()

    assert theirs in root.handlers


def test_repeated_calls_do_not_stack_handlers(monkeypatch):
    monkeypatch.delenv(LOG_FILE_ENV_VAR, raising=False)
    root = logging.getLogger()

    quiet_library_logging()
    settled = len(root.handlers)
    quiet_library_logging()
    quiet_library_logging()

    # Counted from after the first call, not from before it: another test
    # in this run may have left this process already quieted, in which
    # case the first call replaces a handler rather than adding one.
    assert len(root.handlers) == settled


def test_a_log_file_gets_the_records_the_terminal_does_not(tmp_path, monkeypatch):
    """Silencing is not discarding: the health poll that was on screen is
    still readable, in a file, when asked for."""
    monkeypatch.delenv(LOG_FILE_ENV_VAR, raising=False)
    log_path = tmp_path / "logs" / "syzygy.log"

    quiet_library_logging(log_path)
    logging.getLogger("httpx").info('HTTP Request: GET /health "503 Service Unavailable"')
    for handler in logging.getLogger().handlers:
        handler.flush()

    assert "503 Service Unavailable" in log_path.read_text(encoding="utf-8")
    assert not any(_writes_to_terminal(handler) for handler in logging.getLogger().handlers)


def test_an_unwritable_log_file_is_quiet_rather_than_fatal(tmp_path, monkeypatch):
    monkeypatch.delenv(LOG_FILE_ENV_VAR, raising=False)
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")

    quiet_library_logging(blocker / "nested" / "syzygy.log")

    assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)


def _writes_to_terminal(handler: logging.Handler) -> bool:
    stream = getattr(handler, "stream", None)
    return isinstance(handler, logging.StreamHandler) and stream in (sys.stdout, sys.stderr)
