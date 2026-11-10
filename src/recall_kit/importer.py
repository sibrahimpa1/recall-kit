"""Import what you already have: a memory list pasted out of ChatGPT or Claude, or a folder of
markdown notes (a Notion or Obsidian export).

Every bullet or paragraph becomes one memory. Each keeps a precise source ("<origin>: file › heading"),
goes through the same duplicate, stale-text and prompt-injection checks as any other write, and is
tagged `imported` so a bad import is easy to review or undo. Use --dry-run first.

There is no official export file for ChatGPT's saved memories: copy the list from
Settings › Personalization › Manage memories (or ask the assistant to list what it remembers)
into a text file and import that.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .safety import screen
from .store import MemoryStore, StoreError

_BULLET = re.compile(r"^\s*(?:[-*•–]|\d+[.)])\s+(?:\[[ xX]\]\s+)?(.*)$")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*$")
_NOTION_ID = re.compile(r"\s+[0-9a-f]{32}$")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_PREFERENCE = re.compile(r"\b(prefers?|likes?|dislikes?|always|never|wants?|favou?rite|style|tone)\b", re.I)
_DECISION = re.compile(
    r"\b(decided|decision|we chose|chose|agreed to|will use|going with|settled on)\b", re.I
)
MIN_CHARS = 12
MAX_CHARS = 600
TEXT_SUFFIXES = {".md", ".markdown", ".txt"}


@dataclass
class Item:
    content: str
    source: str
    type: str


def guess_type(text: str) -> str:
    if _DECISION.search(text):
        return "decision"
    if _PREFERENCE.search(text):
        return "preference"
    return "fact"


def _clean(text: str) -> str:
    text = _MD_LINK.sub(r"\1", text)
    return re.sub(r"\s+", " ", text.replace("**", "").replace("__", "").replace("`", "")).strip()


def parse_text(text: str, source: str) -> list[Item]:
    """Bullets and paragraphs become items; headings become part of the source."""
    items: list[Item] = []
    heading = ""
    paragraph: list[str] = []
    in_frontmatter = text.startswith("---\n")
    in_code = False

    def emit(raw: str) -> None:
        content = _clean(raw)
        if MIN_CHARS <= len(content) <= MAX_CHARS:
            items.append(Item(content, f"{source} › {heading}" if heading else source, guess_type(content)))

    def flush() -> None:
        if paragraph:
            emit(" ".join(paragraph))
            paragraph.clear()

    for i, line in enumerate(text.splitlines()):
        if in_frontmatter:
            in_frontmatter = not (i > 0 and line.strip() == "---")
            continue
        if line.strip().startswith("```"):
            in_code = not in_code
            flush()
            continue
        if in_code:
            continue
        if m := _HEADING.match(line):
            flush()
            heading = _clean(m.group(1))
        elif m := _BULLET.match(line):
            flush()
            emit(m.group(1))
        elif not line.strip():
            flush()
        elif re.match(r"^\s*[|>]", line) or set(line.strip()) <= set("-=*_ "):
            flush()  # tables, quotes and rules are not memories
        else:
            paragraph.append(line.strip())
    flush()
    return items


def collect(path: Path, origin: str) -> list[Item]:
    if not origin.strip():
        raise StoreError("origin is required: say where this import comes from")
    if path.is_file():
        return parse_text(path.read_text(errors="replace"), f"{origin}: {path.name}")
    if not path.is_dir():
        raise StoreError(f"{path} is not a file or a folder")
    items: list[Item] = []
    for f in sorted(path.rglob("*")):
        if f.is_file() and f.suffix.lower() in TEXT_SUFFIXES and not any(p.startswith(".") for p in f.parts):
            rel = f.relative_to(path)
            name = "/".join([*(_NOTION_ID.sub("", p) for p in rel.parts[:-1]), _NOTION_ID.sub("", rel.stem)])
            items += parse_text(f.read_text(errors="replace"), f"{origin}: {name}")
    return items


def import_items(
    store: MemoryStore,
    items: list[Item],
    *,
    project: str | None = None,
    dry_run: bool = False,
    actor: str = "import",
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    rows: list[dict[str, Any]] = []
    for item in items:
        if dry_run:
            status = "would_quarantine" if screen(item.content) else "would_import"
            row: dict[str, Any] = {"status": status}
        else:
            res = store.remember(
                item.content,
                type=item.type,
                source=item.source,
                tags=["imported"],
                project=project,
                confidence=0.7,
                actor=actor,
            )
            row = {"status": res["status"], "id": res["id"]}
            if res.get("conflicts"):
                row["conflicts_with"] = [c["id"] for c in res["conflicts"]]
        counts[row["status"]] = counts.get(row["status"], 0) + 1
        rows.append({**row, "type": item.type, "content": item.content, "source": item.source})
    return {"dry_run": dry_run, "found": len(items), "counts": counts, "items": rows}
