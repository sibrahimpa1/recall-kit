"""Thin git wrapper: every change to the store is a commit, so history is free and auditable.

Commit messages carry only ids and actions, never memory content, so a forgotten memory cannot
survive in a commit message. `purge()` rewrites history to remove a file from every commit.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_ENV = {
    "GIT_AUTHOR_NAME": "recall-kit",
    "GIT_AUTHOR_EMAIL": "recall-kit@localhost",
    "GIT_COMMITTER_NAME": "recall-kit",
    "GIT_COMMITTER_EMAIL": "recall-kit@localhost",
    "FILTER_BRANCH_SQUELCH_WARNING": "1",
    "GIT_CONFIG_NOSYSTEM": "1",
}

GITIGNORE = "index.sqlite\nindex.sqlite-*\n.lock\n*.tmp\n"


class GitRepo:
    def __init__(self, root: Path) -> None:
        self.root = root
        if shutil.which("git") is None:
            raise RuntimeError("git is required (recall-kit versions the store with git)")

    def _run(self, *args: str, check: bool = True) -> str:
        env = {**os.environ, **_ENV}
        fake_now = os.environ.get("RECALL_NOW")  # demo/test clock, see models.utcnow
        if fake_now and args[0] == "commit":  # never while rewriting history
            env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = fake_now
        proc = subprocess.run(
            ["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
        )
        if check and proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
        return proc.stdout.strip()

    def ensure(self) -> None:
        if (self.root / ".git").exists():
            return
        self._run("init", "-q", "-b", "main")
        (self.root / ".gitignore").write_text(GITIGNORE)
        self._run("add", ".gitignore")
        self._run("commit", "-q", "-m", "init recall-kit store")

    def commit(self, message: str) -> str:
        self._run("add", "-A")
        if not self._run("status", "--porcelain"):
            return self.head()
        self._run("commit", "-q", "-m", message)
        return self.head()

    def head(self) -> str:
        return self._run("rev-parse", "HEAD")

    def last_commit(self, relpath: str) -> str | None:
        out = self._run("log", "-1", "--format=%H", "--", relpath, check=False)
        return out or None

    def rev_before(self, iso_moment: str) -> str | None:
        """Last commit made at or before the given moment."""
        return self._run("rev-list", "-1", f"--before={iso_moment}", "HEAD", check=False) or None

    def ls_files(self, rev: str, prefix: str) -> list[str]:
        return self._run("ls-tree", "-r", "--name-only", rev, "--", prefix, check=False).splitlines()

    def read_many(self, rev: str, relpaths: list[str]) -> list[str]:
        """Contents of many files at one revision, in a single git process."""
        if not relpaths:
            return []
        proc = subprocess.run(
            ["git", "cat-file", "--batch"],
            cwd=self.root,
            input="".join(f"{rev}:{p}\n" for p in relpaths).encode(),
            capture_output=True,
        )
        out, pos, texts = proc.stdout, 0, []
        for _ in relpaths:
            end = out.index(b"\n", pos)
            size = int(out[pos:end].split()[-1])
            texts.append(out[end + 1 : end + 1 + size].decode())
            pos = end + 1 + size + 1
        return texts

    def log(self, limit: int = 200) -> list[dict[str, str]]:
        out = self._run("log", f"-{limit}", "--format=%H%x09%cI%x09%s", check=False)
        return [
            dict(zip(("commit", "date", "message"), ln.split("\t", 2), strict=True))
            for ln in out.splitlines()
        ]

    def show(self, rev: str, relpath: str) -> str | None:
        proc = subprocess.run(
            ["git", "show", f"{rev}:{relpath}"], cwd=self.root, capture_output=True, text=True
        )
        return proc.stdout if proc.returncode == 0 else None

    def file_log(self, relpath: str) -> list[dict[str, str]]:
        out = self._run("log", "--format=%H%x09%cI%x09%s", "--", relpath, check=False)
        rows = []
        for line in out.splitlines():
            sha, when, subject = line.split("\t", 2)
            rows.append({"commit": sha, "date": when, "message": subject})
        return rows

    def purge(self, relpaths: list[str]) -> None:
        """Remove files from *every* commit, then drop the old objects for good."""
        if not relpaths:
            return
        quoted = " ".join(f"'{p}'" for p in relpaths)
        self._run(
            "filter-branch",
            "--force",
            "--index-filter",
            f"git rm -q --cached --ignore-unmatch -- {quoted}",
            "--prune-empty",
            "--",
            "--all",
        )
        shutil.rmtree(self.root / ".git" / "refs" / "original", ignore_errors=True)
        self._run("reflog", "expire", "--expire=now", "--all")
        self._run("gc", "-q", "--prune=now", "--aggressive")

    def all_objects_text(self) -> str:
        """Every object in the object database, decompressed (used by tests and `doctor`)."""
        proc = subprocess.run(
            ["git", "cat-file", "--batch-all-objects", "--batch", "--unordered"],
            cwd=self.root,
            capture_output=True,
        )
        return proc.stdout.decode("utf-8", errors="replace")
