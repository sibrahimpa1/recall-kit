"""Backups/restore, daily brief, ICS export, token handling."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from icalendar import Calendar

from recall_kit import admin, backup
from recall_kit.auth import AuthError, authenticate, new_token, parse_tokens, require
from recall_kit.projects import ProjectBoard
from recall_kit.store import MemoryStore

from .conftest import cli, cli_json

PASS = "correct horse battery staple"


@pytest.fixture
def seeded(home: Path) -> MemoryStore:
    store = MemoryStore(home)
    from recall_kit.seed import seed

    seed(store)
    return store


# backups -----------------------------------------------------------------------------------
def test_backup_restore_roundtrip(seeded: MemoryStore, tmp_path: Path) -> None:
    before = seeded.recall("Tallow Tide invoice terms")["results"][0]
    info = backup.create(seeded.home, tmp_path / "backups", passphrase=PASS)
    raw = Path(info["path"]).read_bytes()
    assert b"net-30" not in raw and b"Tallow" not in raw  # encrypted, not just compressed

    restored = backup.restore(Path(info["path"]), tmp_path / "restored", passphrase=PASS)
    assert restored["doctor_ok"] and restored["active_memories"] == seeded.stats()["active"]
    again = MemoryStore(tmp_path / "restored")
    after = again.recall("Tallow Tide invoice terms")["results"][0]
    assert (after["id"], after["content"], after["source"]["commit"]) == (
        before["id"],
        before["content"],
        before["source"]["commit"],
    )  # git history came along
    assert ProjectBoard(again).resume("northwind-relaunch")["next_steps"]


def test_backup_rejects_wrong_passphrase_and_tampering(seeded: MemoryStore, tmp_path: Path) -> None:
    path = Path(backup.create(seeded.home, tmp_path / "b", passphrase=PASS)["path"])
    with pytest.raises(backup.BackupError, match="wrong passphrase"):
        backup.restore(path, tmp_path / "r1", passphrase="not the right one")
    blob = bytearray(path.read_bytes())
    blob[-10] ^= 0xFF
    path.write_bytes(bytes(blob))
    with pytest.raises(backup.BackupError, match="modified"):
        backup.restore(path, tmp_path / "r2", passphrase=PASS)


def test_restore_refuses_to_overwrite_without_force(seeded: MemoryStore, tmp_path: Path) -> None:
    path = Path(backup.create(seeded.home, tmp_path / "b", passphrase=PASS)["path"])
    with pytest.raises(backup.BackupError, match="not empty"):
        backup.restore(path, seeded.home, passphrase=PASS)


def test_backup_cli_disaster_recovery(
    seeded: MemoryStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The documented runbook: create -> verify -> lose the disk -> restore -> doctor."""
    monkeypatch.setenv("RECALL_BACKUP_PASSPHRASE", PASS)
    home = seeded.home
    made = cli_json(home, "backup", "create", "--out", str(tmp_path / "bk"))
    assert cli_json(home, "backup", "verify", made["path"])["doctor_ok"]
    seeded.close()
    import shutil

    shutil.rmtree(home)  # the VPS disk is gone
    cli_json(home, "backup", "restore", made["path"], "--to", str(home))
    assert cli_json(home, "doctor")["ok"]
    assert "net-30" in cli(home, "recall", "Tallow invoices").stdout


def test_backup_needs_a_passphrase(
    seeded: MemoryStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("RECALL_BACKUP_PASSPHRASE", raising=False)
    with pytest.raises(backup.BackupError, match="RECALL_BACKUP_PASSPHRASE"):
        backup.create(seeded.home, tmp_path)


def test_prune_keeps_newest(tmp_path: Path) -> None:
    for i in range(5):
        (tmp_path / f"recall-2026110{i}T000000Z-aaaaaa.rkb").write_bytes(b"x")
    removed = backup.prune(tmp_path, keep=2)
    assert len(removed) == 3 and sorted(p.name for p in tmp_path.iterdir())[0].startswith("recall-20261103")


# admin -------------------------------------------------------------------------------------
def test_daily_brief(seeded: MemoryStore) -> None:
    b = admin.daily_brief(seeded, today=date(2026, 11, 15))
    assert [r["text"] for r in b["overdue_followups"]] == ["Send staging link for review"]
    assert b["overdue_followups"][0]["days_overdue"] == 3
    assert [r["text"] for r in b["due_soon"]] == ["Run a restore drill from the latest backup"]
    assert b["blocked_projects"][0]["project"] == "northwind-relaunch"
    later = admin.daily_brief(seeded, today=date(2027, 1, 10))
    assert {r["project"] for r in later["stale_projects"]} == {"northwind-relaunch", "vps-hardening"}
    assert "Overdue follow-ups" in b["markdown"]


def test_ics_export_parses_and_folds(seeded: MemoryStore) -> None:
    board = ProjectBoard(seeded)
    board.add_item(
        "vps-hardening",
        "followup",
        "A very long follow-up title " * 6 + "with commas, semicolons; and more",
        due="2026-12-01",
    )
    text = admin.followups_ics(seeded)
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))
    cal = Calendar.from_ical(text)
    events = [c for c in cal.walk() if c.name == "VEVENT"]
    assert len(events) == 3
    summaries = {str(e["SUMMARY"]) for e in events}
    assert "[Northwind Bikes relaunch] Send staging link for review" in summaries
    assert any("semicolons; and more" in s for s in summaries)
    assert {e["DTSTART"].dt for e in events} == {date(2026, 11, 12), date(2026, 11, 20), date(2026, 12, 1)}


# tokens ------------------------------------------------------------------------------------
def test_tokens_are_stored_hashed_and_scoped() -> None:
    secret, line = new_token("laptop", ["read", "write"])
    assert secret not in line
    table = parse_tokens(line)
    p = authenticate({"authorization": f"Bearer {secret}"}, table)
    assert p.name == "laptop"
    require(p, "write")
    with pytest.raises(AuthError):
        require(p, "forget")
    with pytest.raises(AuthError):
        authenticate({"authorization": "Bearer nope"}, table)
    with pytest.raises(ValueError):
        new_token("x", ["superuser"])
