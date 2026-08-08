"""Sanity checks for the small extracted-page fixtures (M6.9,
docs/THOTH_INGESTION_MAP.md section 13) - these document real Book of
Thoth page structure without committing the book itself."""

from pathlib import Path

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "thoth_pdf_pages"


def _body(name: str) -> str:
    text = (FIXTURES_DIR / name).read_text(encoding="utf-8")
    return text.split("---\n", 1)[1]


def test_major_fixture_has_a_major_heading():
    assert "II. THE HIGH PRIESTESS" in _body("major_page_45.txt")


def test_minor_fixture_has_minor_prose():
    assert "primordial Energy" in _body("minor_page_172.txt")


def test_court_fixture_has_page_marker():
    body = _body("court_page_141.txt")
    assert "KNIGHT OF WANDS" in body or "Knight of Wands" in body
    assert "P.152" in body


def test_image_gallery_fixture_is_under_the_skip_threshold():
    # THOTH_INGESTION_MAP.md section 9: after header/footer stripping, a
    # gallery page's remaining text is under ~50 characters. This fixture
    # has no header/footer to strip (it's the entire page) - both its
    # lines are footer-shaped (`^file:///`), so the real per-page content
    # after normalize.py's stripping is empty.
    body = _body("image_gallery_page_90.txt")
    lines = [line for line in body.splitlines() if line.strip()]
    assert all(line.startswith("file:///") for line in lines)
