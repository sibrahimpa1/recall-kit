"""Continuity suite: the five behaviours the job post asks for, each across fresh sessions.

Every `run_session(...)` / `one_call(...)` starts a NEW `rk serve` process and connects with the
official MCP client. Sessions share nothing but the store directory.
"""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pytest

from .conftest import Session, cli_json, one_call, run_session

pytestmark = pytest.mark.continuity


def test_sessions_are_separate_processes(home: Path) -> None:
    pid1 = one_call(home, "memory_stats")["server_pid"]
    pid2 = one_call(home, "memory_stats")["server_pid"]
    assert pid1 != pid2


# 1 ------------------------------------------------------------------------------------------
def test_recall_fact_agreed_in_earlier_session(home: Path) -> None:
    created = one_call(
        home,
        "memory_remember",
        content="Tallow & Tide Candles pays invoices on net-30 terms; invoices go to accounts@tallow-tide.example.",
        source="user in Claude Code, call on 2026-11-03",
        type="fact",
        tags=["client", "billing"],
    )
    assert created["status"] == "created"

    # a different, later session, phrased differently ("payment terms" vs "pays invoices")
    res = one_call(home, "memory_recall", query="what payment terms does Tallow and Tide have?", k=3)
    top = res["results"][0]
    assert top["id"] == created["id"]
    assert "net-30" in top["content"]
    assert top["source"]["origin"] == "user in Claude Code, call on 2026-11-03"
    assert top["citation"] == f"[mem:{created['id']}]"


# 2 ------------------------------------------------------------------------------------------
def test_correcting_stale_information(home: Path) -> None:
    old = one_call(
        home,
        "memory_remember",
        content="The weekly sync with Northwind Bikes is on Tuesday at 10:00.",
        source="user, 2026-10-01",
        key="client.northwind.weekly-sync",
    )

    async def session2(s: Session) -> dict:
        return await s.call(
            "memory_correct",
            id=old["id"],
            content="The weekly sync with Northwind Bikes moved to Thursday at 14:00.",
            source="user, 2026-11-05",
            reason="client changed the slot",
        )

    new = run_session(home, session2)
    assert new["supersedes"] == old["id"]

    async def session3(s: Session) -> tuple[dict, dict, dict]:
        current = await s.call("memory_recall", query="when is the weekly sync with Northwind?")
        everything = await s.call(
            "memory_recall", query="weekly sync Northwind Tuesday", include_superseded=True
        )
        hist = await s.call("memory_history", id=old["id"])
        return current, everything, hist

    current, everything, hist = run_session(home, session3)
    contents = [r["content"] for r in current["results"]]
    assert any("Thursday at 14:00" in c for c in contents)
    assert not any("Tuesday" in c for c in contents), "stale version returned as current"
    stale = next(r for r in everything["results"] if r["id"] == old["id"])
    assert stale["status"] == "superseded" and stale["superseded_by"] == new["id"]
    assert hist["current"] == new["id"]
    assert [v["id"] for v in hist["versions"]] == [old["id"], new["id"]]

    # a later remember() with the same key is also a correction (single-valued slot)
    third = one_call(
        home,
        "memory_remember",
        content="The weekly sync with Northwind Bikes is now on Friday at 09:30.",
        source="user, 2026-11-09",
        key="client.northwind.weekly-sync",
    )
    assert third["superseded"] == [new["id"]]
    res = one_call(home, "memory_recall", query="weekly sync Northwind")
    syncs = [r for r in res["results"] if "weekly sync" in r["content"]]
    assert [r["id"] for r in syncs] == [third["id"]]


# 3 ------------------------------------------------------------------------------------------
SECRET = "Storage unit gate code is 4471-ZEBRA at the Elm Street depot"


def _layers_containing(home: Path, needle: str) -> list[str]:
    hits = []
    if any(needle in p.read_text() for p in home.rglob("*.md")):
        hits.append("markdown files")
    if needle in (home / "audit.jsonl").read_text():
        hits.append("audit log")
    db = sqlite3.connect(home / "index.sqlite")
    if db.execute("SELECT count(*) FROM memories WHERE content LIKE ?", (f"%{needle}%",)).fetchone()[0]:
        hits.append("index table")
    if db.execute("SELECT count(*) FROM memories_fts WHERE memories_fts MATCH ?", ('"ZEBRA"',)).fetchone()[0]:
        hits.append("FTS index")
    db.close()
    for f in home.glob("index.sqlite*"):
        if needle.encode() in f.read_bytes() or b"ZEBRA" in f.read_bytes():
            hits.append(f"raw bytes of {f.name}")
    git = subprocess.run(
        ["git", "log", "--all", "-p", "--reflog"], cwd=home, capture_output=True, text=True
    ).stdout
    if "ZEBRA" in git:
        hits.append("git log")
    objects = subprocess.run(
        ["git", "cat-file", "--batch-all-objects", "--batch"], cwd=home, capture_output=True
    ).stdout
    if b"ZEBRA" in objects:
        hits.append("git object store")
    return hits


def test_forget_on_request_removes_every_layer(home: Path) -> None:
    mem = one_call(home, "memory_remember", content=SECRET, source="user, 2026-11-01")
    one_call(home, "memory_remember", content="Elm Street depot opens at 07:00.", source="user, 2026-11-01")
    corrected = one_call(
        home,
        "memory_correct",
        id=mem["id"],
        content=SECRET.replace("4471", "9902"),
        source="user, 2026-11-02",
    )
    assert "markdown files" in _layers_containing(home, "ZEBRA")

    # without confirm nothing happens
    refused = one_call(home, "memory_forget", id=corrected["id"])
    assert refused["status"] == "not_deleted"
    assert one_call(home, "memory_recall", query="gate code")["results"]

    forgotten = one_call(home, "memory_forget", id=corrected["id"], confirm=True)
    assert set(forgotten["ids"]) == {mem["id"], corrected["id"]}  # every version of it

    res = one_call(home, "memory_recall", query="storage unit gate code ZEBRA", include_superseded=True)
    assert all("ZEBRA" not in r["content"] for r in res["results"])
    assert _layers_containing(home, "ZEBRA") == []
    # unrelated memories survive, the audit log records the deletion without the content
    assert any(
        "07:00" in r["content"] for r in one_call(home, "memory_recall", query="depot opens")["results"]
    )
    audit = (home / "audit.jsonl").read_text()
    assert mem["id"] in audit and '"forget"' in audit
    # rebuilding the index from disk cannot bring it back
    cli_json(home, "reindex")
    assert _layers_containing(home, "ZEBRA") == []
    assert cli_json(home, "doctor")["ok"]


# 4 ------------------------------------------------------------------------------------------
def test_every_retrieved_item_cites_a_verifiable_source(home: Path) -> None:
    sources = {
        "Prefers invoices as PDF attachments, not links.": "user in Claude Desktop, 2026-10-12",
        "Harbor Lane Studio's fiscal year starts in April.": "email thread 'FY planning', 2026-09-30",
        "Decided to host the agent on a single VPS with Docker Compose.": "planning call, 2026-11-01",
        "Harbor Lane Studio wants monthly reports on the first Monday.": "user in Codex CLI, 2026-11-04",
    }

    async def session1(s: Session) -> None:
        for content, src in sources.items():
            await s.call("memory_remember", content=content, source=src)

    run_session(home, session1)

    async def session2(s: Session) -> list[dict]:
        out = []
        for q in ("Harbor Lane Studio", "invoices", "where is the agent hosted", "reports"):
            out += (await s.call("memory_recall", query=q, k=4))["results"]
        return out

    results = run_session(home, session2)
    assert {r["content"] for r in results} == set(sources)  # every memory reachable, nothing extra
    for r in results:
        assert r["citation"] == f"[mem:{r['id']}]"
        src = r["source"]
        assert src["origin"] == sources[r["content"]], "source attributed to the wrong memory"
        path = home / src["file"]
        assert path.exists()
        text = path.read_text()
        assert f"id: {r['id']}" in text and r["content"] in text
        committed = subprocess.run(
            ["git", "show", f"{src['commit']}:{src['file']}"], cwd=home, capture_output=True, text=True
        ).stdout
        assert r["content"] in committed, "cited commit does not contain the cited content"


# 5 ------------------------------------------------------------------------------------------
def test_resume_project_with_status_and_next_steps(home: Path) -> None:
    async def session1(s: Session) -> None:
        await s.call(
            "project_update",
            slug="harbor-portal",
            name="Harbor Lane client portal",
            summary="Client portal for (fictional) Harbor Lane Studio.",
            status="active",
            note="kick-off",
        )
        await s.call("project_add", slug="harbor-portal", kind="next_step", text="Draft the data model")
        await s.call("project_add", slug="harbor-portal", kind="next_step", text="Set up staging on the VPS")
        await s.call(
            "project_add", slug="harbor-portal", kind="next_step", text="Write onboarding email copy"
        )
        await s.call(
            "project_add", slug="harbor-portal", kind="blocker", text="Waiting for SSO metadata from IT"
        )
        await s.call(
            "project_add",
            slug="harbor-portal",
            kind="followup",
            text="Chase IT for SSO metadata",
            due="2026-11-14",
            owner="me",
        )
        await s.call(
            "project_decide",
            slug="harbor-portal",
            decision="Use Postgres, not MongoDB.",
            rationale="Relational reporting needs; team already knows SQL.",
            source="planning call 2026-11-03",
        )
        await s.call("project_close", slug="harbor-portal", item_id="n1")
        await s.call("project_update", slug="harbor-portal", note="data model approved")

    run_session(home, session1)

    brief = one_call(home, "project_resume", slug="harbor-portal")
    assert brief["project"] == "Harbor Lane client portal"
    assert brief["status"] == "blocked"  # an open blocker blocks the project
    assert [n["text"] for n in brief["next_steps"]] == [
        "Set up staging on the VPS",
        "Write onboarding email copy",
    ]
    assert [b["text"] for b in brief["open_blockers"]] == ["Waiting for SSO metadata from IT"]
    assert brief["followups"][0]["due"] == "2026-11-14"
    assert brief["recent_decisions"][0]["content"] == "Use Postgres, not MongoDB."
    assert "Relational reporting" in brief["recent_decisions"][0]["rationale"]
    assert brief["last_status_note"]["note"] == "data model approved"
    assert "Set up staging on the VPS" in brief["markdown"]

    # another tool entirely (the CLI) sees the same state
    via_cli = cli_json(home, "resume", "harbor-portal", "--json")
    assert via_cli["next_steps"] == brief["next_steps"]

    # unblock in a third session -> status flips back
    one_call(home, "project_close", slug="harbor-portal", item_id="b1")
    assert one_call(home, "project_resume", slug="harbor-portal")["status"] == "active"
