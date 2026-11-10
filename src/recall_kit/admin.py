"""Admin workflows: the daily brief and an ICS calendar feed of follow-ups."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from typing import Any

from .projects import ProjectBoard
from .store import MemoryStore

STALE_DAYS = 14


def daily_brief(
    store: MemoryStore, *, today: date | None = None, stale_days: int = STALE_DAYS, horizon_days: int = 7
) -> dict[str, Any]:
    today = today or datetime.now(UTC).date()
    board = ProjectBoard(store)
    overdue, due_soon, stale, blocked = [], [], [], []
    for slug in board.slugs():
        p = board.get(slug)
        for f in p["followups"]:
            if f.get("done"):
                continue
            due = date.fromisoformat(f["due"])
            row = {
                "project": slug,
                "id": f["id"],
                "text": f["text"],
                "due": f["due"],
                "owner": f.get("owner"),
            }
            if due < today:
                overdue.append({**row, "days_overdue": (today - due).days})
            elif due <= today + timedelta(days=horizon_days):
                due_soon.append(row)
        if p["status"] in ("active", "blocked"):
            updated = datetime.fromisoformat(p["updated"].replace("Z", "+00:00")).date()
            age = (today - updated).days
            if age >= stale_days:
                stale.append({"project": slug, "days_since_update": age, "status": p["status"]})
        open_blockers = [b for b in p["blockers"] if not b.get("resolved")]
        if open_blockers:
            blocked.append({"project": slug, "blockers": [b["text"] for b in open_blockers]})
    conflicts = store.conflicts()
    quarantined = [m.id for m in store.all() if m.quarantined]
    brief = {
        "date": today.isoformat(),
        "overdue_followups": sorted(overdue, key=lambda r: r["due"]),
        "due_soon": sorted(due_soon, key=lambda r: r["due"]),
        "stale_projects": stale,
        "blocked_projects": blocked,
        "memory_conflicts": len(conflicts),
        "quarantined_memories": quarantined,
    }
    brief["markdown"] = render_brief(brief)
    return brief


def render_brief(b: dict[str, Any]) -> str:
    out = [f"# Daily brief — {b['date']}", ""]
    out.append(f"## Overdue follow-ups ({len(b['overdue_followups'])})")
    out += [
        f"- {r['due']} ({r['days_overdue']}d late) {r['project']}: {r['text']}"
        for r in b["overdue_followups"]
    ] or ["- none"]
    out.append(f"\n## Due in the next 7 days ({len(b['due_soon'])})")
    out += [f"- {r['due']} {r['project']}: {r['text']}" for r in b["due_soon"]] or ["- none"]
    out.append(f"\n## Stale projects ({len(b['stale_projects'])})")
    out += [
        f"- {r['project']}: no update for {r['days_since_update']} days" for r in b["stale_projects"]
    ] or ["- none"]
    out.append(f"\n## Blocked ({len(b['blocked_projects'])})")
    out += [f"- {r['project']}: {'; '.join(r['blockers'])}" for r in b["blocked_projects"]] or ["- none"]
    out.append("\n## Memory hygiene")
    out.append(f"- unresolved conflicts: {b['memory_conflicts']}")
    out.append(f"- quarantined (needs review): {len(b['quarantined_memories'])}")
    return "\n".join(out) + "\n"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """RFC 5545: lines longer than 75 octets are folded with CRLF + space."""
    raw = line.encode()
    if len(raw) <= 75:
        return line
    parts: list[str] = []
    cur = b""
    for ch in line:
        b = ch.encode()
        if len(cur) + len(b) > (75 if not parts else 74):
            parts.append(cur.decode())
            cur = b""
        cur += b
    parts.append(cur.decode())
    return "\r\n ".join(parts)


def followups_ics(store: MemoryStore, *, include_done: bool = False) -> str:
    board = ProjectBoard(store)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//recall-kit//follow-ups//EN",
        "CALSCALE:GREGORIAN",
        "X-WR-CALNAME:recall-kit follow-ups",
    ]
    for slug in board.slugs():
        p = board.get(slug)
        for f in p["followups"]:
            if f.get("done") and not include_done:
                continue
            due = date.fromisoformat(f["due"])
            uid = hashlib.sha1(f"{slug}/{f['id']}".encode()).hexdigest()[:16]
            lines += [
                "BEGIN:VEVENT",
                f"UID:{uid}@recall-kit",
                f"DTSTAMP:{stamp}",
                f"DTSTART;VALUE=DATE:{due.strftime('%Y%m%d')}",
                f"DTEND;VALUE=DATE:{(due + timedelta(days=1)).strftime('%Y%m%d')}",
                f"SUMMARY:{_escape(f'[{p["name"]}] {f["text"]}')}",
                f"DESCRIPTION:{_escape(f'Follow-up {f["id"]} in project {slug}' + (f' — owner: {f["owner"]}' if f.get('owner') else ''))}",
                f"STATUS:{'COMPLETED' if f.get('done') else 'CONFIRMED'}",
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                "DESCRIPTION:Follow-up due",
                "TRIGGER:-PT15H",
                "END:VALARM",
                "END:VEVENT",
            ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
