"""Read-only dashboard: serves data, travels in time, refuses writes and foreign hosts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from recall_kit.seed import seed
from recall_kit.store import MemoryStore

from .conftest import free_port


@pytest.fixture
def dashboard(home: Path) -> Iterator[str]:
    store = MemoryStore(home)
    seed(store)
    store.remember("<img src=x onerror=alert(1)> is a note with markup.", source="xss probe")
    store.close()
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "recall_kit.cli", "ui", "--port", str(port)],
        env={**os.environ, "RECALL_HOME": str(home)},
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(base + "/api/overview", timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        yield base
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def _get(url: str) -> dict:
    return json.loads(urllib.request.urlopen(url, timeout=10).read())


def test_dashboard_api(dashboard: str) -> None:
    over = _get(dashboard + "/api/overview")
    assert over["stats"]["superseded"] == 2 and over["brief"]["memory_conflicts"] == 1
    assert len(over["brief"]["quarantined_memories"]) == 1 and over["history"]["first"] == "2026-10-12"

    q = urllib.parse.quote("Tallow invoice terms")
    now = _get(f"{dashboard}/api/memories?q={q}")["items"]
    assert "net-45" in now[0]["content"]
    then = _get(f"{dashboard}/api/memories?q={q}&as_of=2026-10-25")
    assert "net-30" in then["items"][0]["content"] and then["items"][0]["changed_since"]

    listed = _get(dashboard + "/api/memories")["items"]
    assert all(m["status"] == "active" and not m.get("quarantined") for m in listed)
    assert len(_get(dashboard + "/api/memories?status=quarantined")["items"]) == 1

    hist = _get(f"{dashboard}/api/memory/{now[0]['id']}")
    assert len(hist["versions"]) == 2 and hist["current"] == now[0]["id"]

    review = _get(dashboard + "/api/review")
    assert len(review["conflicts"]) == 1 and review["quarantined"][0]["quarantine_reason"]
    projects = _get(dashboard + "/api/projects")
    assert {p["slug"] for p in projects} == {"northwind-relaunch", "vps-hardening"}
    assert _get(dashboard + "/api/activity")[0]["commit"]


def test_dashboard_is_read_only_local_and_escapes_content(dashboard: str) -> None:
    page = urllib.request.urlopen(dashboard + "/")
    html = page.read().decode()
    assert "script-src" in page.headers["Content-Security-Policy"]
    assert "innerHTML" not in html and "onerror=alert" not in html  # content only via textContent

    with pytest.raises(urllib.error.HTTPError) as post:
        urllib.request.urlopen(urllib.request.Request(dashboard + "/api/memories", data=b"{}", method="POST"))
    assert post.value.code == 405

    with pytest.raises(urllib.error.HTTPError) as rebind:  # DNS-rebinding style request
        urllib.request.urlopen(
            urllib.request.Request(dashboard + "/api/overview", headers={"Host": "evil.example"})
        )
    assert rebind.value.code == 403
