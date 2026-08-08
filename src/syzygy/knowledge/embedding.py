"""Fixed-length vectors for knowledge chunks (M13.3).

These are **hashed lexical signatures**, not neural embeddings, and the
distinction is worth being precise about: two chunks score as similar here
when they share vocabulary, not when they share meaning. A paraphrase with
no words in common scores near zero.

That is a deliberate trade, recorded in
`docs/adr/0003-ship-derived-knowledge-index-without-source-text.md`. A
real sentence-embedding model would give genuine semantic similarity, but
it has to run at *query* time as well as at build time - a query has to
land in the same vector space as the corpus - which would make
`sentence-transformers`/`torch` a runtime dependency of a local-first
terminal app, for a few hundred short documents. `AGENTS.md` already rules
out a vector database and a hosted service for the same reason.

The scheme is the signed hashing trick (random indexing): every token is
hashed to two of `DIMENSIONS` buckets with opposite signs and accumulated
with sublinear term frequency, then the vector is L2-normalised so cosine
similarity is a plain dot product.

Two properties this has to keep:

- **Deterministic across processes and platforms.** Hashing uses
  `blake2b`, never Python's `hash()`, which is salted per process.
- **Not invertible to text.** A ~900-word chunk collapses to 256 floats,
  and word order is discarded entirely. This is what lets the vectors be
  redistributed when the source text cannot be.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from typing import Final

import numpy as np

#: Bumped whenever tokenisation, weighting, or dimensionality changes -
#: a bundled artifact built under a different version cannot be compared
#: against freshly computed query vectors.
VECTOR_VERSION: Final = "lexical-v1"

DIMENSIONS: Final = 256

#: Two buckets per token: one positive, one negative. Cheap, and it
#: halves the collision rate compared with a single bucket.
_HASHES_PER_TOKEN: Final = 2

_TOKEN = re.compile(r"[a-z][a-z'-]{1,}")

#: Function words carry no retrieval signal and would otherwise dominate
#: every vector. Deliberately short - this is a stop list, not a
#: linguistic model.
_STOPWORDS: Final[frozenset[str]] = frozenset(
    """
    a an and are as at be been but by for from had has have he her his i in into is it
    its of on or she that the their them there they this to was were which who will
    with would you your not no nor so if then than when where what how all any both
    each few more most other some such only own same too very can just
    """.split()
)


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens, minus stopwords. Punctuation, digits and
    single characters are dropped: page numbers and stray OCR marks are
    noise here, not signal."""
    return [token for token in _TOKEN.findall(text.lower()) if token not in _STOPWORDS]


def _buckets(token: str) -> list[tuple[int, float]]:
    """The (dimension, sign) pairs `token` contributes to."""
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    pairs: list[tuple[int, float]] = []
    for index in range(_HASHES_PER_TOKEN):
        shifted = value >> (index * 24)
        dimension = (shifted >> 1) % DIMENSIONS
        sign = 1.0 if shifted & 1 else -1.0
        pairs.append((dimension, sign))
    return pairs


def lexical_vector(text: str) -> np.ndarray:
    """`text` as a unit-length `float32` vector of `DIMENSIONS`.

    All-stopword or empty input yields a zero vector, which scores zero
    against everything rather than raising - an empty query is a query
    with no answer, not an error.
    """
    vector = np.zeros(DIMENSIONS, dtype=np.float32)
    counts = Counter(tokenize(text))
    if not counts:
        return vector

    for token, count in counts.items():
        # Sublinear term frequency: a word used 50 times is not 50 times
        # more indicative than one used once.
        weight = 1.0 + math.log(count)
        for dimension, sign in _buckets(token):
            vector[dimension] += sign * weight

    norm = float(np.linalg.norm(vector))
    if norm == 0.0:  # exactly cancelling collisions; vanishingly unlikely
        return vector
    return (vector / norm).astype(np.float32)


def similarities(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Cosine similarity of `query` against every row of `matrix`.

    Both sides are unit-length by construction, so this is a dot product.
    """
    if matrix.size == 0:
        return np.zeros(0, dtype=np.float32)
    return matrix @ query.astype(np.float32)
