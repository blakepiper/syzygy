from syzygy.iching.book import get_hexagram, load_hexagrams, number_for_lines


def test_canonical_book_has_all_64_unique_king_wen_hexagrams() -> None:
    hexagrams = load_hexagrams()

    assert len(hexagrams) == 64
    assert [item.number for item in hexagrams] == list(range(1, 65))
    assert len({tuple(item.lines_bottom_up) for item in hexagrams}) == 64
    assert all(number_for_lines(item.lines_bottom_up) == item.number for item in hexagrams)


def test_every_hexagram_has_complete_legge_text_and_entry_level_citations() -> None:
    for item in load_hexagrams():
        assert item.judgment
        assert item.image
        assert len(item.line_texts) == 6
        assert all(item.line_texts)
        assert item.citation.text_pages
        assert item.citation.image_pages
        assert item.citation.source.endswith("(Oxford, 1882)")
        assert item.citation.source_url.endswith(f"ic{item.number:02d}.htm")


def test_source_spot_checks_pin_transcription_and_trigrams() -> None:
    creative = get_hexagram(1)
    receptive = get_hexagram(2)
    after_completion = get_hexagram(63)

    assert creative.name == "Khien"
    assert creative.judgment.startswith("Khien (represents) what is great and originating")
    assert creative.line_texts[0].endswith("It is not the time for active doing.")
    assert creative.image.startswith("Heaven, in its motion")
    assert creative.lower_trigram.value == creative.upper_trigram.value == "heaven"
    assert receptive.lower_trigram.value == receptive.upper_trigram.value == "earth"
    assert after_completion.lower_trigram.value == "fire"
    assert after_completion.upper_trigram.value == "water"
