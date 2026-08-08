"""Guards the one fact every later ingestion task depends on: that the PDF
in the repository is still the exact file docs/THOTH_INGESTION_MAP.md was
written against. If this test fails, the source file changed and the
ingestion map (page ranges, heading anchors, hash) needs to be
re-verified, not just re-hashed.
"""

import hashlib
from pathlib import Path

EXPECTED_SHA256 = "5942febc85fd73e38ac4dfb9fc32e4ba9591883f6d2709ea829e4827ae1083a0"


def test_book_of_thoth_pdf_hash_matches_ingestion_map():
    pdf_path = Path(__file__).resolve().parents[2] / "docs" / "book_of_thoth.pdf"
    assert pdf_path.exists(), "docs/book_of_thoth.pdf is missing"
    digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    assert digest == EXPECTED_SHA256, (
        "docs/book_of_thoth.pdf has changed since docs/THOTH_INGESTION_MAP.md "
        "was written - re-verify the page-range and heading-anchor tables "
        "in that document before trusting them"
    )
