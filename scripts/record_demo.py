"""Record real terminal output to SVG for the README (nothing here is mocked).

Every `rk ...` line is a separate process against a fresh temporary store, i.e. a fresh session.
    uv run python scripts/record_demo.py
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from rich.console import Console
from rich.text import Text

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "img"


def record(title: str, commands: list[str], filename: str, env: dict[str, str], width: int = 110) -> None:
    console = Console(record=True, width=width, force_terminal=True, color_system="truecolor")
    ids: dict[str, str] = {}
    for cmd in commands:
        for name, value in ids.items():
            cmd = cmd.replace(f"${name}", value)
        console.print(Text("$ ", style="bold green") + Text(cmd, style="bold"))
        args = shlex.split(cmd)
        if args[0] == "rk":
            args = [sys.executable, "-m", "recall_kit.cli", *args[1:]]
        proc = subprocess.run(
            args, capture_output=True, text=True, env={**os.environ, **env, "COLUMNS": str(width)}, cwd=ROOT
        )
        out = (proc.stdout + proc.stderr).rstrip()
        out = out.replace(env["RECALL_HOME"], "~/.recall-kit-demo")
        console.print(Text.from_ansi(out))
        console.print()
        found = re.findall(r'"id": "(mem_[0-9a-f]{10})"', out)
        if found:
            ids[f"ID{len(ids) + 1}"] = found[0]
    OUT.mkdir(parents=True, exist_ok=True)
    console.save_svg(str(OUT / filename), title=title)
    print(f"wrote {OUT / filename}")


def main() -> None:
    home = Path(tempfile.mkdtemp(prefix="rk-demo-")) / "store"
    env = {"RECALL_HOME": str(home), "RECALL_ACTOR": "demo"}
    record(
        "recall-kit: memory lifecycle across fresh sessions",
        [
            'rk remember "Harbor Lane Studio pays invoices on net-30 terms." --source "user, call 2026-11-03" --key client.harbor-lane.terms',
            'rk recall "what are Harbor Lane payment terms"',
            'rk correct $ID1 "Harbor Lane Studio pays on net-45 from December." --source "user, email 2026-11-09"',
            'rk recall "Harbor Lane payment terms"',
            'rk remember "Storage unit gate code is 4471." --source "user, 2026-11-03"',
            "rk forget $ID3 --yes",
            'rk recall "storage unit gate code"',
        ],
        "lifecycle.svg",
        env,
    )
    record(
        "recall-kit: resume a project in a new session",
        [
            "rk demo",
            "rk resume northwind-relaunch",
            "rk brief --today 2026-11-15",
        ],
        "resume.svg",
        env,
    )
    console = Console(record=True, width=120, force_terminal=True)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-m", "continuity", "-v", "-p", "no:cacheprovider", "--color=yes"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    lines = [ln for ln in proc.stdout.splitlines() if "PASSED" in ln or "FAILED" in ln or " passed" in ln]
    console.print(Text("$ ", style="bold green") + Text("uv run pytest -m continuity -v", style="bold"))
    console.print(Text.from_ansi("\n".join(ln.replace(str(ROOT) + "/", "") for ln in lines)))
    console.save_svg(str(OUT / "continuity-suite.svg"), title="recall-kit: continuity suite")
    print(f"wrote {OUT / 'continuity-suite.svg'}")


if __name__ == "__main__":
    main()
