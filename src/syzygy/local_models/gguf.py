"""Reading a GGUF file's header without loading its weights (M16.6c).

A GGUF file starts with a magic number, a version, tensor and metadata
counts, and then a flat key/value table. Everything Syzygy needs - which
architecture it is, how many layers, the attention shape, the trained
context length, whether it carries a chat template - is in that table,
which is a few hundred kilobytes at the front of a file that may be nine
gigabytes. So this reads a bounded prefix and stops; it never touches a
tensor, never allocates model memory, and cannot be made to by a
malformed file.

Two defences, because this parses an attacker-influenceable file:

* **Bounded everything.** A declared string length, array count, or
  metadata count larger than `MAX_*` is rejected outright rather than
  believed - a four-byte edit to a downloaded file must not turn into a
  multi-gigabyte allocation.
* **Bounded reads.** The parser works over a byte buffer the caller
  supplies, so `inspect_gguf_file` can hand it the first
  `HEADER_READ_BYTES` and a truncated parse is a clean
  `GgufError`, not a crash.

The KV-cache figure this yields is arithmetic, not estimation:
`context × layers × kv_heads × (key_length + value_length) × 2 bytes`
is exactly what llama.cpp allocates for an f16 cache.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

MAGIC: Final = b"GGUF"

#: Versions this parser understands. v1 used 32-bit lengths and is long
#: gone from every publisher Syzygy would list.
SUPPORTED_VERSIONS: Final = (2, 3)

#: How much of the file to read for the header. Generous: a Qwen3 tokenizer
#: table alone runs to a few megabytes.
HEADER_READ_BYTES: Final = 16 * 1024 * 1024

MAX_METADATA_ENTRIES: Final = 100_000
MAX_STRING_BYTES: Final = 64 * 1024 * 1024
MAX_ARRAY_ENTRIES: Final = 4_000_000

#: GGUF value type tags.
_UINT8, _INT8, _UINT16, _INT16, _UINT32, _INT32 = 0, 1, 2, 3, 4, 5
_FLOAT32, _BOOL, _STRING, _ARRAY, _UINT64, _INT64, _FLOAT64 = 6, 7, 8, 9, 10, 11, 12

_SCALAR_FORMATS: Final[dict[int, tuple[str, int]]] = {
    _UINT8: ("<B", 1),
    _INT8: ("<b", 1),
    _UINT16: ("<H", 2),
    _INT16: ("<h", 2),
    _UINT32: ("<I", 4),
    _INT32: ("<i", 4),
    _FLOAT32: ("<f", 4),
    _BOOL: ("<?", 1),
    _UINT64: ("<Q", 8),
    _INT64: ("<q", 8),
    _FLOAT64: ("<d", 8),
}

#: f16 KV cache, which is llama.cpp's default and what Syzygy's launch
#: profile requests. Quantized caches exist and are not used here: the
#: point of the estimate is to be an upper bound.
KV_CACHE_BYTES_PER_ELEMENT: Final = 2


class GgufError(ValueError):
    """The file is not a GGUF Syzygy can read. Always actionable: the
    caller turns it into "this file isn't a model Syzygy understands"."""


@dataclass(frozen=True)
class GgufMetadata:
    """The subset of the header Syzygy actually uses."""

    architecture: str
    name: str | None
    block_count: int | None
    embedding_length: int | None
    head_count: int | None
    head_count_kv: int | None
    key_length: int | None
    value_length: int | None
    context_length: int | None
    file_type: int | None
    has_chat_template: bool
    tensor_count: int
    version: int

    def kv_cache_bytes(self, context_tokens: int) -> int | None:
        """Exact f16 KV cache size at `context_tokens`, or `None` when the
        header did not carry enough of the attention shape.

        `key_length`/`value_length` are optional in GGUF; when absent they
        default to `embedding_length / head_count`, which is what
        llama.cpp itself assumes.
        """
        if not self.block_count or not self.head_count_kv:
            return None
        key_length = self.key_length
        value_length = self.value_length
        if key_length is None or value_length is None:
            if not self.embedding_length or not self.head_count:
                return None
            head_dim = self.embedding_length // self.head_count
            key_length = key_length or head_dim
            value_length = value_length or head_dim
        return (
            context_tokens
            * self.block_count
            * self.head_count_kv
            * (key_length + value_length)
            * KV_CACHE_BYTES_PER_ELEMENT
        )


class _Reader:
    """A cursor over a byte buffer that refuses to read past the end."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._offset = 0

    def take(self, count: int) -> bytes:
        if count < 0 or self._offset + count > len(self._data):
            raise GgufError("GGUF header is truncated")
        chunk = self._data[self._offset : self._offset + count]
        self._offset += count
        return chunk

    def scalar(self, value_type: int) -> Any:
        fmt, size = _SCALAR_FORMATS[value_type]
        return struct.unpack(fmt, self.take(size))[0]

    def u32(self) -> int:
        return int(struct.unpack("<I", self.take(4))[0])

    def u64(self) -> int:
        return int(struct.unpack("<Q", self.take(8))[0])

    def string(self) -> str:
        length = self.u64()
        if length > MAX_STRING_BYTES:
            raise GgufError(f"GGUF string length {length} is implausible")
        return self.take(length).decode("utf-8", errors="replace")

    def value(self, value_type: int) -> Any:
        if value_type in _SCALAR_FORMATS:
            return self.scalar(value_type)
        if value_type == _STRING:
            return self.string()
        if value_type == _ARRAY:
            return self.array()
        raise GgufError(f"unknown GGUF value type {value_type}")

    def array(self) -> list[Any]:
        element_type = self.u32()
        count = self.u64()
        if count > MAX_ARRAY_ENTRIES:
            raise GgufError(f"GGUF array of {count} entries is implausible")
        # Arrays of strings are the expensive case (a 150k-token vocabulary).
        # Syzygy never reads one, so they are skipped rather than
        # materialized: the length is consumed, the contents discarded.
        if element_type == _STRING:
            for _ in range(count):
                self.string()
            return []
        if element_type in _SCALAR_FORMATS:
            _, size = _SCALAR_FORMATS[element_type]
            self.take(size * count)
            return []
        raise GgufError(f"unknown GGUF array element type {element_type}")


def parse_gguf_header(data: bytes) -> GgufMetadata:
    """Parse the metadata table out of a GGUF file's leading bytes."""
    reader = _Reader(data)
    if reader.take(4) != MAGIC:
        raise GgufError("not a GGUF file (bad magic number)")
    version = reader.u32()
    if version not in SUPPORTED_VERSIONS:
        raise GgufError(f"unsupported GGUF version {version}")
    tensor_count = reader.u64()
    metadata_count = reader.u64()
    if metadata_count > MAX_METADATA_ENTRIES:
        raise GgufError(f"GGUF declares {metadata_count} metadata entries")

    wanted_prefixes = (
        "general.architecture",
        "general.name",
        "general.file_type",
        "tokenizer.chat_template",
    )
    values: dict[str, Any] = {}
    for _ in range(metadata_count):
        key = reader.string()
        value_type = reader.u32()
        value = reader.value(value_type)
        # Keep only the handful of keys that matter, so a model with a
        # 150k-entry tokenizer does not leave a dictionary of it behind.
        if key.startswith(wanted_prefixes) or ".attention." in key or key.endswith(
            (".block_count", ".embedding_length", ".context_length")
        ):
            values[key] = value

    architecture = values.get("general.architecture")
    if not isinstance(architecture, str) or not architecture:
        raise GgufError("GGUF header has no general.architecture")

    def integer(suffix: str) -> int | None:
        value = values.get(f"{architecture}.{suffix}")
        return int(value) if isinstance(value, int) else None

    name = values.get("general.name")
    file_type = values.get("general.file_type")
    return GgufMetadata(
        architecture=architecture,
        name=name if isinstance(name, str) else None,
        block_count=integer("block_count"),
        embedding_length=integer("embedding_length"),
        head_count=integer("attention.head_count"),
        head_count_kv=integer("attention.head_count_kv"),
        key_length=integer("attention.key_length"),
        value_length=integer("attention.value_length"),
        context_length=integer("context_length"),
        file_type=int(file_type) if isinstance(file_type, int) else None,
        has_chat_template=bool(values.get("tokenizer.chat_template")),
        tensor_count=tensor_count,
        version=version,
    )


def inspect_gguf_file(path: Path, *, read_bytes: int = HEADER_READ_BYTES) -> GgufMetadata:
    """Read `path`'s header only. Raises `GgufError` for anything that is
    not a GGUF file Syzygy can use - which is the answer the "choose an
    existing model file" flow needs, and is reached without ever mapping
    the weights."""
    try:
        with path.open("rb") as handle:
            data = handle.read(read_bytes)
    except OSError as exc:
        raise GgufError(f"could not read {path.name}: {exc}") from exc
    return parse_gguf_header(data)
