from pathlib import Path

import pytest

from syzygy.knowledge.ingest import (
    SOURCE_TYPES,
    UnknownSourceTypeError,
    _chunk_text,
    default_source_paths,
    detect_source_type,
)


def test_default_source_paths_are_the_complete_docs_set():
    assert default_source_paths() == [
        ("book_of_thoth", Path("docs/book_of_thoth.pdf")),
        ("duquette_companion", Path("docs/understanding_crowley_thoth_tarot.pdf")),
        ("ziegler_mirror_of_soul", Path("docs/mirror_of_the_soul.pdf")),
    ]
    assert tuple(source_type for source_type, _ in default_source_paths()) == SOURCE_TYPES


def test_detect_source_type_book_of_thoth():
    assert detect_source_type(Path("docs/book_of_thoth.pdf")) == "book_of_thoth"


def test_detect_source_type_duquette():
    assert (
        detect_source_type(Path("/x/understanding_crowley_thoth_tarot.pdf"))
        == "duquette_companion"
    )


def test_detect_source_type_ziegler():
    assert detect_source_type(Path("mirror_of_the_soul.pdf")) == "ziegler_mirror_of_soul"


def test_detect_source_type_unknown_raises():
    with pytest.raises(UnknownSourceTypeError):
        detect_source_type(Path("some_other_book.pdf"))


def test_chunk_text_short_section_is_one_chunk():
    text = "First paragraph.\n\nSecond paragraph."
    assert _chunk_text(text) == [text]


def test_chunk_text_empty_returns_no_chunks():
    assert _chunk_text("") == []
    assert _chunk_text("   \n\n  ") == []


def test_chunk_text_splits_at_word_budget():
    # Each paragraph is ~600 words; two of them exceed the 900-word target,
    # so they should land in separate chunks.
    paragraph = " ".join(["word"] * 600)
    text = f"{paragraph}\n\n{paragraph}\n\n{paragraph}"
    chunks = _chunk_text(text)
    assert len(chunks) == 3
    assert all(chunk == paragraph for chunk in chunks)


def test_chunk_text_never_crosses_a_paragraph_mid_split():
    paragraph = " ".join(["word"] * 10)
    text = "\n\n".join([paragraph] * 5)  # well under the word budget as a whole
    chunks = _chunk_text(text)
    assert len(chunks) == 1
    assert chunks[0] == text
