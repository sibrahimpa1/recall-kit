"""Project continuity: status, decisions (with rationale), blockers, next steps, follow-ups.

Each project is one markdown file `projects/<slug>.md`: structured YAML frontmatter that tools
read and write, plus a rendered body a human can skim on GitHub or in Obsidian. Decisions are
stored as `decision` memories so they are searchable, citable and correctable like any memory.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any

import yaml

from .models import utcnow
from .store import DATA_NOTICE, MemoryStore, StoreError

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_FM = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)
STATUSES = ("active", "blocked", "paused", "done")


def _today() -> date:
    return datetime.now(UTC).date()


def _parse_day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise StoreError(f"due must be YYYY-MM-DD, got {value!r}") from exc


class ProjectBoard:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    # ---- persistence ----------------------------------------------------------
    def _path(self, slug: str):
        if not _SLUG.match(slug):
            raise StoreError("project slug must be lowercase letters, digits and dashes")
        return self.store.proj_dir / f"{slug}.md"

    def load(self, slug: str) -> dict[str, Any] | None:
        path = self._path(slug)
        if not path.exists():
            return None
        m = _FM.match(path.read_text())
        if not m:
            raise StoreError(f"{path} has no frontmatter")
        return yaml.safe_load(m.group(1))

    def get(self, slug: str) -> dict[str, Any]:
        p = self.load(slug)
        if p is None:
            known = ", ".join(self.slugs()) or "none"
            raise StoreError(f"project {slug!r} not found (known: {known})")
        return p

    def slugs(self) -> list[str]:
        return sorted(p.stem for p in self.store.proj_dir.glob("*.md"))

    def _save(self, p: dict[str, Any], message: str, actor: str) -> None:
        p["updated"] = utcnow()
        fm = yaml.safe_dump(p, sort_keys=False, allow_unicode=True).strip()
        path = self._path(p["slug"])
        tmp = path.with_suffix(".tmp")
        tmp.write_text(f"---\n{fm}\n---\n{self._render(p)}")
        tmp.replace(path)
        self.store.audit("project", [p["slug"]], actor, op=message.split(" ")[0])
        self.store.git.commit(f"{message} [{p['slug']}]")

    @staticmethod
    def _render(p: dict[str, Any]) -> str:
        lines = [f"# {p['name']}", "", f"**Status:** {p['status']}  ", f"**Updated:** {p['updated']}", ""]
        if p.get("summary"):
            lines += [p["summary"], ""]
        sections = [
            ("Open blockers", [b for b in p["blockers"] if not b.get("resolved")], lambda b: b["text"]),
            ("Next steps", [n for n in p["next_steps"] if not n.get("done")], lambda n: n["text"]),
            (
                "Follow-ups",
                [f for f in p["followups"] if not f.get("done")],
                lambda f: f"{f['due']} — {f['text']}" + (f" ({f['owner']})" if f.get("owner") else ""),
            ),
        ]
        for title, items, fmt in sections:
            lines.append(f"## {title}")
            lines += [f"- [{i['id']}] {fmt(i)}" for i in items] or ["- none"]
            lines.append("")
        return "\n".join(lines)

    def _next_id(self, items: list[dict[str, Any]], prefix: str) -> str:
        nums = [int(i["id"][1:]) for i in items if i["id"][1:].isdigit()]
        return f"{prefix}{max(nums, default=0) + 1}"

    # ---- operations -------------------------------------------------------------
    def upsert(
        self,
        slug: str,
        *,
        name: str | None = None,
        status: str | None = None,
        summary: str | None = None,
        note: str | None = None,
        actor: str = "local",
    ) -> dict[str, Any]:
        if status and status not in STATUSES:
            raise StoreError(f"status must be one of {STATUSES}")
        with self.store.lock():
            p = self.load(slug)
            created = p is None
            if p is None:
                p = {
                    "slug": slug,
                    "name": name or slug.replace("-", " ").title(),
                    "status": status or "active",
                    "summary": summary or "",
                    "created": utcnow(),
                    "updated": utcnow(),
                    "status_log": [],
                    "blockers": [],
                    "next_steps": [],
                    "followups": [],
                }
            if name:
                p["name"] = name
            if summary is not None:
                p["summary"] = summary
            if status or note:
                p["status"] = status or p["status"]
                p["status_log"] = (
                    p["status_log"] + [{"at": utcnow(), "status": p["status"], "note": note or ""}]
                )[-20:]
            self._save(p, "create-project" if created else "update-project", actor)
        return {"status": "created" if created else "updated", "project": self.summary(slug)}

    def add_item(
        self,
        slug: str,
        kind: str,
        text: str,
        *,
        due: str | None = None,
        owner: str | None = None,
        actor: str = "local",
    ) -> dict[str, Any]:
        field, prefix = {
            "blocker": ("blockers", "b"),
            "next_step": ("next_steps", "n"),
            "followup": ("followups", "f"),
        }[kind]
        text = text.strip()
        if not text:
            raise StoreError("text is empty")
        with self.store.lock():
            p = self.get(slug)
            item: dict[str, Any] = {"id": self._next_id(p[field], prefix), "text": text, "added": utcnow()}
            if kind == "followup":
                if not due:
                    raise StoreError("a follow-up needs a due date (YYYY-MM-DD)")
                item["due"] = _parse_day(due).isoformat()
                if owner:
                    item["owner"] = owner
            p[field].append(item)
            if kind == "blocker" and p["status"] == "active":
                p["status"] = "blocked"
            self._save(p, f"add-{kind}", actor)
        return {"status": "added", "project": slug, "item": item}

    def close_item(self, slug: str, item_id: str, *, actor: str = "local") -> dict[str, Any]:
        field, flag = {
            "b": ("blockers", "resolved"),
            "n": ("next_steps", "done"),
            "f": ("followups", "done"),
        }.get(item_id[:1], (None, None))
        if field is None or flag is None:
            raise StoreError("item id must start with b (blocker), n (next step) or f (follow-up)")
        with self.store.lock():
            p = self.get(slug)
            item = next((i for i in p[field] if i["id"] == item_id), None)
            if item is None:
                raise StoreError(f"{item_id} not found in {slug}")
            item[flag] = utcnow()
            if (
                field == "blockers"
                and p["status"] == "blocked"
                and not any(not b.get("resolved") for b in p["blockers"])
            ):
                p["status"] = "active"
            self._save(p, f"close-{field}", actor)
        return {"status": "closed", "project": slug, "item": item}

    def record_decision(
        self, slug: str, decision: str, *, rationale: str, source: str, actor: str = "local"
    ) -> dict[str, Any]:
        self.get(slug)
        if not rationale.strip():
            raise StoreError("a decision needs its rationale (the 'why')")
        res = self.store.remember(
            decision, type="decision", source=source, project=slug, rationale=rationale, actor=actor
        )
        with self.store.lock():
            p = self.get(slug)
            self._save(p, "decision", actor)
        return res

    # ---- views ------------------------------------------------------------------
    def summary(self, slug: str) -> dict[str, Any]:
        p = self.get(slug)
        return {
            "slug": slug,
            "name": p["name"],
            "status": p["status"],
            "updated": p["updated"],
            "open_blockers": sum(1 for b in p["blockers"] if not b.get("resolved")),
            "open_next_steps": sum(1 for n in p["next_steps"] if not n.get("done")),
            "open_followups": sum(1 for f in p["followups"] if not f.get("done")),
        }

    def list(self) -> list[dict[str, Any]]:
        return [self.summary(s) for s in self.slugs()]

    def resume(self, slug: str, *, today: date | None = None) -> dict[str, Any]:
        """Compact briefing an agent can read at the start of a fresh session."""
        today = today or _today()
        p = self.get(slug)
        updated = datetime.fromisoformat(p["updated"].replace("Z", "+00:00")).date()
        followups = sorted((f for f in p["followups"] if not f.get("done")), key=lambda f: f["due"])
        for f in followups:
            f["overdue"] = date.fromisoformat(f["due"]) < today
        decisions = [self.store._item(m) for m in self.store.find(type="decision", project=slug)[:5]]
        context = [self.store._item(m) for m in self.store.find(type="project", project=slug)[:5]]
        brief = {
            "notice": DATA_NOTICE,
            "project": p["name"],
            "slug": slug,
            "status": p["status"],
            "summary": p.get("summary", ""),
            "last_update": p["updated"],
            "days_since_update": (today - updated).days,
            "last_status_note": (p["status_log"][-1] if p["status_log"] else None),
            "open_blockers": [b for b in p["blockers"] if not b.get("resolved")],
            "next_steps": [n for n in p["next_steps"] if not n.get("done")],
            "followups": followups,
            "recent_decisions": decisions,
            "context": context,
            "source": {
                "file": f"projects/{slug}.md",
                "commit": self.store.git.last_commit(f"projects/{slug}.md"),
            },
        }
        brief["markdown"] = self.render_brief(brief)
        return brief

    @staticmethod
    def render_brief(b: dict[str, Any]) -> str:
        lines = [f"## Resume: {b['project']} — {b['status']} (updated {b['days_since_update']}d ago)"]
        if b["summary"]:
            lines.append(b["summary"])
        if b["last_status_note"] and b["last_status_note"].get("note"):
            lines.append(f"Last note: {b['last_status_note']['note']}")
        lines.append(
            "Blockers: " + ("; ".join(f"[{x['id']}] {x['text']}" for x in b["open_blockers"]) or "none")
        )
        lines.append("Next steps:")
        lines += [f"  {i}. [{n['id']}] {n['text']}" for i, n in enumerate(b["next_steps"], 1)] or ["  none"]
        lines.append("Follow-ups:")
        lines += [
            f"  - [{f['id']}] {f['due']}{' OVERDUE' if f['overdue'] else ''}: {f['text']}"
            for f in b["followups"]
        ] or ["  none"]
        if b["recent_decisions"]:
            lines.append("Decisions:")
            lines += [
                f"  - {d['content']} — why: {d.get('rationale', '?')} {d['citation']}"
                for d in b["recent_decisions"]
            ]
        lines.append(f"Source: {b['source']['file']} @ {(b['source']['commit'] or '')[:8]}")
        return "\n".join(lines)
