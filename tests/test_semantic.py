"""The optional local semantic model (`uv sync --extra semantic`). Skipped when it is not installed."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from recall_kit.embed import HashingEmbedder

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("fastembed") is None, reason="semantic extra not installed"
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))


@pytest.fixture(scope="module")
def semantic():
    from recall_kit.embed import FastEmbedEmbedder

    return FastEmbedEmbedder()


def test_paraphrase_recall_with_no_shared_words(home: Path, semantic) -> None:
    from recall_kit.store import MemoryStore

    store = MemoryStore(home, embedder=semantic)
    mem = store.remember("Tallow & Tide Candles pays invoices on net-30 terms.", source="call")
    store.remember("The agent VPS has 2 vCPU and 4 GB RAM.", source="user")
    hit = store.recall("how long does the candle company have to settle a bill?")["results"][0]
    assert hit["id"] == mem["id"] and hit["source"]["origin"] == "call"
    assert store.recall("recipe for sourdough bread")["results"] == []


def test_switching_embedder_reindexes_automatically(home: Path, semantic) -> None:
    from recall_kit.store import MemoryStore

    first = MemoryStore(home, embedder=HashingEmbedder())
    first.remember("The office is closed from 24 December to 2 January.", source="user")
    first.close()
    second = MemoryStore(home, embedder=semantic)  # same store, different model
    assert second.index.vector_models() == {semantic.name}
    assert second.recall("when are we off over Christmas?")["results"]
    assert second.doctor()["ok"]


def test_benchmark_floor(semantic) -> None:
    """Regression guard on evals/retrieval_bench.py (tuning set). Real numbers are in the README."""
    import retrieval_bench as rb

    hashing = rb.evaluate(HashingEmbedder(), "hybrid")
    assert hashing["keyword"]["hit@1"] >= 0.9 and hashing["unrelated"]["correctly_empty"] >= 0.8
    sem = rb.evaluate(semantic, "hybrid")
    assert sem["keyword"]["hit@1"] >= 0.95
    assert sem["paraphrase"]["hit@3"] >= 0.7
    assert sem["unrelated"]["correctly_empty"] >= 0.9
