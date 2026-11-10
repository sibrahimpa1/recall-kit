"""Embeddings for the vector half of hybrid retrieval.

The default embedder is a deterministic *feature-hashing* model: word unigrams, bigrams and
character trigrams are hashed into a fixed-size signed vector and L2-normalised. It needs no
model download and no API key, so retrieval works offline, in CI and on a 1 GB VPS. It catches
morphology ("invoices" ~ "invoice", "billing" ~ "billed") that plain BM25 misses, but it is not a
semantic model. Swap in a real embedding model by implementing `Embedder` (see docs/handover.md).
"""

from __future__ import annotations

import hashlib
import itertools
import math
import re
import struct
from typing import Protocol

_WORD = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, text: str) -> list[float]: ...


class HashingEmbedder:
    def __init__(self, dim: int = 384) -> None:
        self.dim = dim
        self.name = f"hashing-v1-{dim}"

    def _bucket(self, feature: str) -> tuple[int, float]:
        h = hashlib.blake2b(feature.encode(), digest_size=8).digest()
        n = int.from_bytes(h, "little")
        return n % self.dim, 1.0 if (n >> 63) & 1 else -1.0

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        words = _WORD.findall(text.lower())
        feats: list[tuple[str, float]] = [(f"w:{w}", 1.0) for w in words]
        feats += [(f"b:{a}_{b}", 0.7) for a, b in itertools.pairwise(words)]
        for w in words:
            padded = f"#{w}#"
            feats += [(f"c:{padded[i : i + 3]}", 0.35) for i in range(len(padded) - 2)]
        for feat, weight in feats:
            i, sign = self._bucket(feat)
            vec[i] += sign * weight
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))


def pack(vec: list[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


def default_embedder() -> Embedder:
    return HashingEmbedder()
