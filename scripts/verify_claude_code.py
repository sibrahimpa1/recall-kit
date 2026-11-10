"""Real-client verification: four separate headless Claude Code sessions share one store via MCP.

Each `claude -p` call is a new Claude Code process with no conversation history; its only link to
earlier sessions is the recall-kit MCP server (a new `rk serve` process each time) and the store
directory. Writes a transcript (tool calls + final answers) to docs/verification/.

    uv run python scripts/verify_claude_code.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SESSIONS = [
    "Please remember these, all from me today: (1) Harbor Lane Studio pays invoices on net-30 terms. "
    "(2) The storage unit gate code is 4471. Then set up project 'harbor-portal' (Harbor Lane client portal) "
    "with next steps: draft the data model; set up staging on the VPS; write onboarding email copy. "
    "Blocker: waiting for SSO metadata from IT. Follow-up: chase IT for SSO metadata, due 2026-11-14. "
    "Decision: use Postgres, because reporting is relational and the team knows SQL.",
    "What payment terms does Harbor Lane Studio have? Cite the memory you used.",
    "Two changes. Correction: from December Harbor Lane Studio pays on net-45, not net-30. "
    "And please permanently delete the storage unit gate code from memory — I confirm the deletion. "
    "Also mark the data model step of harbor-portal as done.",
    "Three questions: what are Harbor Lane Studio's payment terms, what is the storage unit gate code, "
    "and where are we on harbor-portal (status, blockers, next steps)?",
]
DENY = "Bash Read Write Edit Glob Grep WebFetch WebSearch Task NotebookEdit TodoWrite"
SYSTEM = "Use only the recall-kit memory tools. Each conversation starts with no history."


def run(prompt: str, config: Path) -> tuple[list[dict], str]:
    proc = subprocess.run(
        [
            "claude",
            "-p",
            prompt,
            "--strict-mcp-config",
            "--mcp-config",
            str(config),
            "--allowedTools",
            "mcp__recall",
            "--disallowedTools",
            DENY,
            "--append-system-prompt",
            SYSTEM,
            "--output-format",
            "stream-json",
            "--verbose",
        ],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=tempfile.gettempdir(),
    )
    calls, answer = [], ""
    for line in proc.stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "assistant":
            for block in ev["message"]["content"]:
                if block.get("type") == "tool_use":
                    calls.append({"tool": block["name"], "input": block["input"]})
        if ev.get("type") == "result":
            answer = ev.get("result", "")
    if proc.returncode != 0:
        answer += f"\n[exit {proc.returncode}] {proc.stderr[-400:]}"
    return calls, answer


def main() -> int:
    if not shutil.which("claude"):
        print("claude CLI not found")
        return 1
    work = Path(tempfile.mkdtemp(prefix="rk-claude-verify-"))
    home = work / "store"
    config = work / "mcp.json"
    config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "recall": {
                        "command": shutil.which("uv"),
                        "args": ["run", "--quiet", "--directory", str(ROOT), "rk", "serve"],
                        "env": {"RECALL_HOME": str(home)},
                    }
                }
            }
        )
    )
    version = subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip()
    lines = [
        f"# Claude Code ↔ recall-kit verification ({datetime.now(UTC):%Y-%m-%d %H:%M} UTC)",
        "",
        f"Client: Claude Code {version}, headless (`claude -p`), MCP over stdio. "
        "Four separate processes; no shared conversation history.",
        "",
    ]
    for i, prompt in enumerate(SESSIONS, 1):
        calls, answer = run(prompt, config)
        lines += [f"## Session {i}", "", f"**User:** {prompt}", "", "**Tool calls:**", ""]
        lines += [
            f"- `{c['tool'].removeprefix('mcp__recall__')}` {json.dumps(c['input'], ensure_ascii=False)}"
            for c in calls
        ] or ["- none"]
        lines += ["", "**Answer:**", "", *("> " + a for a in answer.strip().splitlines()), ""]
        print(f"session {i}: {len(calls)} tool calls")
    rk = [sys.executable, "-m", "recall_kit.cli", "--home", str(home)]
    doctor = subprocess.run([*rk, "doctor"], capture_output=True, text=True).stdout
    listing = subprocess.run([*rk, "list", "--status", ""], capture_output=True, text=True).stdout
    leaked = subprocess.run(
        ["git", "log", "--all", "-p"], cwd=home, capture_output=True, text=True
    ).stdout.count("4471")
    lines += [
        "## Store state after session 4",
        "",
        "```json",
        listing.strip(),
        "```",
        "",
        f"`git log --all -p` occurrences of the deleted code: **{leaked}**",
        "",
        "`rk doctor`:",
        "",
        "```json",
        doctor.strip(),
        "```",
        "",
    ]
    out = ROOT / "docs" / "verification" / "claude-code-sessions.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
