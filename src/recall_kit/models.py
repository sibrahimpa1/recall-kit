"""Data model: one memory = one markdown file with YAML frontmatter."""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import yaml

MemoryType = Literal["fact", "preference", "decision", "project"]
MEMORY_TYPES: tuple[str, ...] = ("fact", "preference", "decision", "project")
Status = Literal["active", "superseded"]

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)


def utcnow() -> str:
    """Current UTC time. RECALL_NOW (ISO, e.g. 2026-10-20T09:00:00Z) overrides the clock so demos
    and tests can build a history spread over weeks; never set it in normal use."""
    fake = os.environ.get("RECALL_NOW")
    if fake:
        return fake
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class Memory:
    id: str
    type: str
    content: str
    source: str
    created: str
    updated: str
    confidence: float = 0.9
    status: str = "active"
    supersedes: list[str] = field(default_factory=list)
    superseded_by: str | None = None
    tags: list[str] = field(default_factory=list)
    project: str | None = None
    key: str | None = None
    rationale: str | None = None
    quarantined: bool = False
    quarantine_reason: str | None = None

    # ---- (de)serialisation -------------------------------------------------
    def frontmatter(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("content")
        # keep files tidy: drop empty optionals
        return {k: v for k, v in data.items() if v not in (None, [], False) or k in ("supersedes", "tags")}

    def to_markdown(self) -> str:
        fm = yaml.safe_dump(self.frontmatter(), sort_keys=False, allow_unicode=True).strip()
        return f"---\n{fm}\n---\n{self.content.strip()}\n"

    @classmethod
    def from_markdown(cls, text: str) -> Memory:
        m = _FRONTMATTER.match(text)
        if not m:
            raise ValueError("memory file has no YAML frontmatter")
        meta = yaml.safe_load(m.group(1)) or {}
        meta["content"] = m.group(2).strip()
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in meta.items() if k in known})

    def public(self) -> dict[str, Any]:
        return asdict(self)
