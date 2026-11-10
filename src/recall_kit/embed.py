"""Embeddings for the vector half of hybrid retrieval.

The default embedder is a deterministic *feature-hashing* model: word unigrams, bigrams and
character trigrams are hashed into a fixed-size signed vector and L2-normalised. It needs no
model download and no API key, so retrieval works offline, in CI and on a 1 GB VPS. It catches
morphology ("invoices" ~ "invoice", "billing" ~ "billed") that plain BM25 misses, but it is not a
semantic model. Swap in a real embedding model by implementing `Embedder` (see docs/handover.md).
"""

from __future__ import annotations

import hashlib
import importlib.util
import itertools
import math
import os
import re
import struct
from collections.abc import Iterable
from typing import Any, Protocol

_WORD = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    name: str
    dim: int
    min_similarity: float  # cosine floor for a vector-only hit to count as relevant
    conflict_similarity: float  # cosine above which two memories are "about the same thing"
    vector_weight: float  # weight of the vector ranking in fusion (keyword ranking = 1.0)

    def embed(self, text: str) -> list[float]: ...

    def embed_query(self, text: str) -> list[float]: ...


class HashingEmbedder:
    def __init__(self, dim: int = 384) -> None:
        self.dim = dim
        self.name = f"hashing-v1-{dim}"
        self.min_similarity = 0.3
        self.conflict_similarity = 0.45
        self.vector_weight = 1.0

    def embed_query(self, text: str) -> list[float]:
        return self.embed(text)

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


class FastEmbedEmbedder:
    """Local semantic model (ONNX, CPU) via the optional `semantic` extra. No API key.

    The model (~90 MB) is downloaded once on first use and cached. all-MiniLM-L6-v2 was chosen by
    measurement: on evals/retrieval_bench.py it ranked the right memory first for more paraphrased
    questions than bge-small, and its similarity scores separate "related" from "unrelated" better.
    """

    def __init__(self, model: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        if importlib.util.find_spec("fastembed") is None:
            raise RuntimeError("RECALL_EMBEDDER=semantic needs: uv sync --extra semantic")
        self._model_name = model
        self._loaded: Any = None  # loaded on first use: `rk resume` or `rk brief` never pay for it
        self.name = f"fastembed:{model}"
        self.dim = 384
        self.min_similarity = 0.3
        self.conflict_similarity = 0.7
        self.vector_weight = 2.0  # measured: the semantic ranking is the more reliable of the two

    @property
    def _model(self) -> Any:
        if self._loaded is None:
            from fastembed import TextEmbedding

            cache = (
                os.path.expanduser(os.environ["RECALL_MODEL_CACHE"])
                if os.environ.get("RECALL_MODEL_CACHE")
                else None
            )

            self._loaded = TextEmbedding(self._model_name, cache_dir=cache)
        return self._loaded

    @staticmethod
    def _unit(vec: Iterable[float]) -> list[float]:
        out = [float(v) for v in vec]
        norm = math.sqrt(sum(v * v for v in out)) or 1.0
        return [v / norm for v in out]

    def embed(self, text: str) -> list[float]:
        return self._unit(next(iter(self._model.embed([text]))))

    def embed_query(self, text: str) -> list[float]:
        return self._unit(next(iter(self._model.query_embed(text))))


def default_embedder() -> Embedder:
    """RECALL_EMBEDDER = auto (default) | semantic | hashing.

    auto uses the local semantic model when the `semantic` extra is installed and falls back to
    the zero-dependency hashing embedder otherwise. The store re-indexes itself when this changes.
    """
    choice = os.environ.get("RECALL_EMBEDDER", "auto").lower()
    if choice not in ("auto", "semantic", "hashing"):
        raise RuntimeError(f"unknown RECALL_EMBEDDER={choice!r} (use auto, semantic or hashing)")
    if choice == "semantic" or (choice == "auto" and importlib.util.find_spec("fastembed")):
        return FastEmbedEmbedder()
    return HashingEmbedder()
