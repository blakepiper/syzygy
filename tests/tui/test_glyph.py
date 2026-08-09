"""`default_glyphs` terminal capability detection (docs/old/DESIGN.md section 18.5,
`TASKS.md` M9.2) - `SYZYGY_ASCII=1` always wins; otherwise selection
follows the output stream's encoding (falling back to the process locale
when the stream doesn't expose one).
"""

from __future__ import annotations

from syzygy.tui.widgets.glyph import ASCII_GLYPHS, UNICODE_GLYPHS, default_glyphs


class _FakeStream:
    def __init__(self, encoding: str | None) -> None:
        self.encoding = encoding


def test_utf8_stream_selects_unicode_glyphs(monkeypatch):
    monkeypatch.delenv("SYZYGY_ASCII", raising=False)
    monkeypatch.setattr("sys.stdout", _FakeStream("utf-8"))

    assert default_glyphs() == UNICODE_GLYPHS


def test_non_utf8_stream_selects_ascii_glyphs(monkeypatch):
    monkeypatch.delenv("SYZYGY_ASCII", raising=False)
    monkeypatch.setattr("sys.stdout", _FakeStream("ascii"))

    assert default_glyphs() == ASCII_GLYPHS


def test_missing_stream_encoding_falls_back_to_locale(monkeypatch):
    monkeypatch.delenv("SYZYGY_ASCII", raising=False)
    monkeypatch.setattr("sys.stdout", _FakeStream(None))
    monkeypatch.setattr("locale.getpreferredencoding", lambda do_setlocale=True: "UTF-8")

    assert default_glyphs() == UNICODE_GLYPHS


def test_syzygy_ascii_env_var_always_wins(monkeypatch):
    monkeypatch.setenv("SYZYGY_ASCII", "1")
    monkeypatch.setattr("sys.stdout", _FakeStream("utf-8"))

    assert default_glyphs() == ASCII_GLYPHS
