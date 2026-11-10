"""Runs evals/llm_eval.py when ANTHROPIC_API_KEY is set; skipped otherwise (CI default)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.llm


@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set")
def test_llm_in_the_loop_eval() -> None:
    script = Path(__file__).resolve().parents[1] / "evals" / "llm_eval.py"
    proc = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=1800)
    print(proc.stdout)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_eval_skips_cleanly_without_a_key() -> None:
    script = Path(__file__).resolve().parents[1] / "evals" / "llm_eval.py"
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    proc = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, env=env)
    assert proc.returncode == 0 and "SKIPPED" in proc.stdout
