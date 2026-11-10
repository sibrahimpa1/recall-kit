"""SQLite index: FTS5 (BM25) + vectors. Derived data only — `rk reindex` rebuilds it from files."""

from __future__ import annotations

import contextlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from .embed import Embedder, cosine, pack, unpack
from .models import Memory
from .safety import content_hash

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY, type TEXT, status TEXT, project TEXT, key TEXT, content TEXT,
    source TEXT, created TEXT, updated TEXT, confidence REAL, tags TEXT, quarantined INTEGER,
    chash TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    id UNINDEXED, content, tags, project, tokenize='porter unicode61'
);
CREATE TABLE IF NOT EXISTS vectors (id TEXT PRIMARY KEY, model TEXT, vec BLOB);
CREATE TABLE IF NOT EXISTS conflicts (
    a TEXT, b TEXT, detected TEXT, PRIMARY KEY (a, b)
);
"""

_TOKEN = re.compile(r"\w+", re.UNICODE)


class Index:
    def __init__(self, path: Path, embedder: Embedder) -> None:
        self.path = path
        self.embedder = embedder
        self.db = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA secure_delete=ON")
        self.db.executescript(SCHEMA)
        # SQLite >= 3.42: deleted FTS rows are scrubbed from the inverted index immediately
        with contextlib.suppress(sqlite3.OperationalError):
            self.db.execute("INSERT INTO memories_fts(memories_fts, rank) VALUES('secure-delete', 1)")

    def close(self) -> None:
        self.db.close()

    # ---- writes -------------------------------------------------------------
    def upsert(self, m: Memory) -> None:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self._delete_rows(m.id)
            self.db.execute(
                "INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    m.id,
                    m.type,
                    m.status,
                    m.project,
                    m.key,
                    m.content,
                    m.source,
                    m.created,
                    m.updated,
                    m.confidence,
                    json.dumps(m.tags),
                    int(m.quarantined),
                    content_hash(m.content),
                ),
            )
            self.db.execute(
                "INSERT INTO memories_fts(id, content, tags, project) VALUES (?,?,?,?)",
                (m.id, m.content, " ".join(m.tags), m.project or ""),
            )
            self.db.execute(
                "INSERT INTO vectors VALUES (?,?,?)",
                (m.id, self.embedder.name, pack(self.embedder.embed(m.content))),
            )
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def _delete_rows(self, mem_id: str) -> None:
        self.db.execute("DELETE FROM memories WHERE id=?", (mem_id,))
        self.db.execute("DELETE FROM memories_fts WHERE id=?", (mem_id,))
        self.db.execute("DELETE FROM vectors WHERE id=?", (mem_id,))

    def delete(self, ids: list[str]) -> None:
        self.db.execute("BEGIN IMMEDIATE")
        for mem_id in ids:
            self._delete_rows(mem_id)
            self.db.execute("DELETE FROM conflicts WHERE a=? OR b=?", (mem_id, mem_id))
        self.db.execute("COMMIT")

    def scrub(self) -> None:
        """Make deletions physical: merge FTS segments, checkpoint WAL, rewrite the file."""
        self.db.execute("INSERT INTO memories_fts(memories_fts) VALUES('optimize')")
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.db.execute("VACUUM")
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def clear(self) -> None:
        self.db.executescript(
            "DELETE FROM memories; DELETE FROM memories_fts; DELETE FROM vectors; DELETE FROM conflicts;"
        )

    def add_conflict(self, a: str, b: str, when: str) -> None:
        a, b = sorted((a, b))
        self.db.execute("INSERT OR IGNORE INTO conflicts VALUES (?,?,?)", (a, b, when))

    def drop_conflicts(self, mem_id: str) -> None:
        self.db.execute("DELETE FROM conflicts WHERE a=? OR b=?", (mem_id, mem_id))

    # ---- reads --------------------------------------------------------------
    def rows(self, where: str = "1=1", params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        return list(self.db.execute(f"SELECT * FROM memories WHERE {where}", params))

    def by_hash(self, chash: str) -> list[sqlite3.Row]:
        return self.rows("chash=?", (chash,))

    def conflicts(self) -> list[tuple[str, str, str]]:
        return [(r["a"], r["b"], r["detected"]) for r in self.db.execute("SELECT * FROM conflicts")]

    def conflicts_for(self, mem_id: str) -> list[str]:
        out = self.db.execute("SELECT a, b FROM conflicts WHERE a=? OR b=?", (mem_id, mem_id))
        return [r["b"] if r["a"] == mem_id else r["a"] for r in out]

    def fts(self, query: str, limit: int = 50) -> list[tuple[str, float]]:
        tokens = _TOKEN.findall(query)
        if not tokens:
            return []
        match = " OR ".join('"' + t.replace('"', "") + '"' for t in tokens)
        sql = "SELECT id, bm25(memories_fts) AS s FROM memories_fts WHERE memories_fts MATCH ? ORDER BY s LIMIT ?"
        return [(r["id"], -r["s"]) for r in self.db.execute(sql, (match, limit))]

    def vector_search(self, query: str, limit: int = 50) -> list[tuple[str, float]]:
        q = self.embedder.embed(query)
        scored = [
            (r["id"], cosine(q, unpack(r["vec"])))
            for r in self.db.execute("SELECT id, vec FROM vectors WHERE model=?", (self.embedder.name,))
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    def vector(self, mem_id: str) -> list[float] | None:
        row = self.db.execute("SELECT vec FROM vectors WHERE id=?", (mem_id,)).fetchone()
        return unpack(row["vec"]) if row else None

    def all_ids(self, table: str) -> set[str]:
        return {r[0] for r in self.db.execute(f"SELECT id FROM {table}")}
