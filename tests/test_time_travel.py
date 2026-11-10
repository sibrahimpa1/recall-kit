"""Time travel and supersession-aware recall, across fresh sessions that are weeks apart."""

from __future__ import annotations

from pathlib import Path

import pytest

from recall_kit.store import MemoryStore, StoreError

from .conftest import cli, one_call

pytestmark = pytest.mark.continuity

OCT = "2026-10-12T09:00:00.000Z"
NOV = "2026-11-03T09:00:00.000Z"


def _history(home: Path) -> tuple[dict, dict]:
    old = one_call(
        home,
        "memory_remember",
        at=OCT,
        content="Tallow & Tide pays invoices on net-30 terms.",
        source="kick-off call, 2026-10-12",
    )
    new = one_call(
        home,
        "memory_correct",
        at=NOV,
        id=old["id"],
        source="email, 2026-11-03",
        content="Tallow & Tide pays invoices on net-45 terms from December.",
    )
    return old, new


def test_recall_as_of_answers_from_the_past(home: Path) -> None:
    old, new = _history(home)

    then = one_call(home, "memory_recall", query="Tallow & Tide invoice terms", as_of="2026-10-25")
    assert [r["id"] for r in then["results"]] == [old["id"]]
    assert "net-30" in then["results"][0]["content"]
    assert then["results"][0]["changed_since"] is True  # flagged: no longer the current truth
    assert then["results"][0]["source"]["commit"] == then["snapshot_commit"]

    after = one_call(home, "memory_recall", query="Tallow & Tide invoice terms", as_of="2026-11-04")
    assert [r["id"] for r in after["results"]] == [new["id"]]
    assert "changed_since" not in after["results"][0]

    now = one_call(home, "memory_recall", query="Tallow & Tide invoice terms")
    assert [r["id"] for r in now["results"]] == [new["id"]]

    before_anything = one_call(home, "memory_recall", query="Tallow", as_of="2026-09-01")
    assert before_anything["results"] == [] and "no history" in before_anything["message"]

    assert "net-30" in cli(home, "recall", "Tallow invoice terms", "--as-of", "2026-10-25").stdout


def test_forgotten_memories_are_gone_from_the_past_too(home: Path) -> None:
    """Deletion beats time travel: `forget` rewrites history, so no snapshot can bring it back."""
    mem = one_call(home, "memory_remember", at=OCT, content="Storage unit gate code is 4471.", source="user")
    keep = one_call(
        home, "memory_remember", at=OCT, content="The storage unit is on Elm Street.", source="user"
    )
    assert one_call(home, "memory_recall", query="storage unit gate code", as_of="2026-10-20")["results"]
    one_call(home, "memory_forget", id=mem["id"], confirm=True)
    past = one_call(home, "memory_recall", query="storage unit gate code", as_of="2026-10-20")
    assert [r["id"] for r in past["results"]] == [
        keep["id"]
    ]  # history kept its dates, minus the deleted file


def test_query_matching_an_old_version_returns_the_current_one(home: Path) -> None:
    """The new wording shares no words with the question; the old wording does."""
    old = one_call(
        home, "memory_remember", content="Our hosting provider is Hetzner.", source="user, September"
    )
    new = one_call(
        home,
        "memory_correct",
        id=old["id"],
        content="We moved everything to a box in Frankfurt.",
        source="user, November",
    )
    res = one_call(home, "memory_recall", query="Hetzner hosting provider")
    assert [r["id"] for r in res["results"]] == [new["id"]]
    assert res["results"][0]["matched_earlier_version"] == old["id"]


def test_bad_as_of_is_a_clear_error(home: Path) -> None:
    with pytest.raises(StoreError, match="as_of must be"):
        MemoryStore(home).recall("x", as_of="last tuesday")
