"""GGUF header parsing (M16.6c).

Headers are built here byte by byte rather than shipped as fixtures - a
real GGUF is gigabytes, and the interesting cases (a declared string
length of 2^60, a truncated file) cannot be produced by any real
publisher anyway.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from syzygy.local_models.gguf import (
    GgufError,
    inspect_gguf_file,
    parse_gguf_header,
)

_STRING, _UINT32, _ARRAY = 8, 4, 9


def _kv_string(key: str, value: str) -> bytes:
    return _key(key) + struct.pack("<I", _STRING) + _string(value)


def _kv_uint32(key: str, value: int) -> bytes:
    return _key(key) + struct.pack("<I", _UINT32) + struct.pack("<I", value)


def _key(key: str) -> bytes:
    return _string(key)


def _string(text: str) -> bytes:
    raw = text.encode("utf-8")
    return struct.pack("<Q", len(raw)) + raw


def header(entries: list[bytes], *, version: int = 3, tensor_count: int = 291) -> bytes:
    return (
        b"GGUF"
        + struct.pack("<I", version)
        + struct.pack("<Q", tensor_count)
        + struct.pack("<Q", len(entries))
        + b"".join(entries)
    )


QWEN_LIKE = [
    _kv_string("general.architecture", "qwen3"),
    _kv_string("general.name", "Qwen3 8B"),
    _kv_uint32("qwen3.block_count", 36),
    _kv_uint32("qwen3.embedding_length", 4096),
    _kv_uint32("qwen3.context_length", 40960),
    _kv_uint32("qwen3.attention.head_count", 32),
    _kv_uint32("qwen3.attention.head_count_kv", 8),
    _kv_uint32("qwen3.attention.key_length", 128),
    _kv_uint32("qwen3.attention.value_length", 128),
    _kv_string("tokenizer.chat_template", "{% for message in messages %}"),
]


def test_a_well_formed_header_is_parsed() -> None:
    metadata = parse_gguf_header(header(QWEN_LIKE))

    assert metadata.architecture == "qwen3"
    assert metadata.block_count == 36
    assert metadata.head_count_kv == 8
    assert metadata.context_length == 40960
    assert metadata.has_chat_template is True
    assert metadata.tensor_count == 291


def test_kv_cache_size_is_exact_arithmetic() -> None:
    metadata = parse_gguf_header(header(QWEN_LIKE))

    # 8192 x 36 layers x 8 kv heads x (128 + 128) x 2 bytes
    assert metadata.kv_cache_bytes(8192) == 8192 * 36 * 8 * 256 * 2
    assert metadata.kv_cache_bytes(4096) == metadata.kv_cache_bytes(8192) // 2


def test_missing_key_and_value_lengths_fall_back_to_the_head_dimension() -> None:
    entries = [entry for entry in QWEN_LIKE if b"length" not in entry or b"embedding" in entry]
    metadata = parse_gguf_header(header(entries))

    assert metadata.key_length is None
    # 4096 / 32 heads = 128, which is what llama.cpp itself assumes.
    assert metadata.kv_cache_bytes(8192) == 8192 * 36 * 8 * 256 * 2


def test_an_incomplete_attention_shape_yields_no_estimate() -> None:
    entries = [
        _kv_string("general.architecture", "mystery"),
        _kv_uint32("mystery.block_count", 12),
    ]
    metadata = parse_gguf_header(header(entries))

    assert metadata.kv_cache_bytes(8192) is None


def test_a_non_gguf_file_is_rejected() -> None:
    with pytest.raises(GgufError, match="bad magic number"):
        parse_gguf_header(b"NOTGGUF" + b"\0" * 100)


def test_an_unsupported_version_is_rejected() -> None:
    with pytest.raises(GgufError, match="unsupported GGUF version"):
        parse_gguf_header(header(QWEN_LIKE, version=1))


def test_a_truncated_header_is_rejected_rather_than_crashing() -> None:
    with pytest.raises(GgufError, match="truncated"):
        parse_gguf_header(header(QWEN_LIKE)[:60])


def test_an_implausible_string_length_is_rejected_without_allocating() -> None:
    payload = (
        b"GGUF"
        + struct.pack("<I", 3)
        + struct.pack("<Q", 1)
        + struct.pack("<Q", 1)
        + struct.pack("<Q", 2**60)  # a key claiming to be an exabyte long
    )

    with pytest.raises(GgufError, match="implausible"):
        parse_gguf_header(payload)


def test_an_implausible_metadata_count_is_rejected() -> None:
    payload = (
        b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", 1) + struct.pack("<Q", 10**9)
    )

    with pytest.raises(GgufError, match="metadata entries"):
        parse_gguf_header(payload)


def test_a_string_array_is_skipped_rather_than_materialized() -> None:
    """A tokenizer vocabulary is 150k strings. Reading it into a list
    would cost more memory than the header is worth, so the parser
    consumes and discards it - but must still land on the next key."""
    vocabulary = (
        _key("tokenizer.ggml.tokens")
        + struct.pack("<I", _ARRAY)
        + struct.pack("<I", _STRING)
        + struct.pack("<Q", 3)
        + _string("a")
        + _string("b")
        + _string("c")
    )
    metadata = parse_gguf_header(header([vocabulary, *QWEN_LIKE]))

    assert metadata.architecture == "qwen3"
    assert metadata.block_count == 36


def test_a_header_without_an_architecture_is_rejected() -> None:
    with pytest.raises(GgufError, match="general.architecture"):
        parse_gguf_header(header([_kv_string("general.name", "nameless")]))


def test_inspect_reads_only_a_bounded_prefix(tmp_path: Path) -> None:
    target = tmp_path / "model.gguf"
    # A header followed by "weights" that must never be read.
    target.write_bytes(header(QWEN_LIKE) + b"\xff" * (2 * 1024 * 1024))

    metadata = inspect_gguf_file(target, read_bytes=4096)
    assert metadata.architecture == "qwen3"


def test_inspect_reports_an_unreadable_file_clearly(tmp_path: Path) -> None:
    with pytest.raises(GgufError, match="could not read"):
        inspect_gguf_file(tmp_path / "absent.gguf")
