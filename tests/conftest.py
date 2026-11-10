"""Test harness: every "session" is a brand-new OS process.

`mcp_session(home)` launches `rk serve` (stdio) as a fresh subprocess and talks to it through the
official MCP client, exactly like Claude Code / Claude Desktop / Codex do. The only thing two
sessions share is the store directory on disk — no Python objects, no caches, no process.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

SERVER_CMD = [sys.executable, "-m", "recall_kit.cli", "serve"]


class Session:
    """A connected MCP client; `call()` returns the tool's structured result or raises."""

    def __init__(self, client: Client) -> None:
        self.client = client

    async def call(self, tool: str, **args: Any) -> Any:
        res = await self.client.call_tool(tool, {k: v for k, v in args.items() if v is not None})
        if res.is_error:
            raise ToolError(" ".join(getattr(c, "text", "") for c in res.content))
        data = res.structured_content
        if isinstance(data, dict) and set(data) == {"result"}:
            return data["result"]
        return data


class ToolError(RuntimeError):
    pass


def run_session(
    home: Path, script: Callable[[Session], Awaitable[Any]], env: dict[str, str] | None = None
) -> Any:
    """Run one fresh MCP session (new server process) against the store at `home`."""

    async def main() -> Any:
        params = StdioServerParameters(
            command=SERVER_CMD[0],
            args=SERVER_CMD[1:],
            env={"RECALL_HOME": str(home), **(env or {})},
        )
        async with Client(params) as client:
            return await script(Session(client))

    return asyncio.run(main())


def run_http_session(url: str, token: str | None, script: Callable[[Session], Awaitable[Any]]) -> Any:
    """Fresh MCP session over Streamable HTTP with a bearer token."""
    import httpx2
    from mcp.client.streamable_http import streamable_http_client

    async def main() -> Any:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with (
            httpx2.AsyncClient(headers=headers, timeout=30) as http,
            Client(streamable_http_client(url, http_client=http)) as client,
        ):
            return await script(Session(client))

    return asyncio.run(main())


def one_call(home: Path, tool: str, **args: Any) -> Any:
    async def script(s: Session) -> Any:
        return await s.call(tool, **args)

    return run_session(home, script)


def cli(home: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        [sys.executable, "-m", "recall_kit.cli", *args],
        env={**os.environ, "RECALL_HOME": str(home), "COLUMNS": "200"},
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        raise AssertionError(f"rk {' '.join(args)} failed:\n{proc.stdout}\n{proc.stderr}")
    return proc


def cli_json(home: Path, *args: str) -> Any:
    return json.loads(cli(home, *args).stdout)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def http_server(home: Path, tokens: str) -> Iterator[str]:
    port = free_port()
    proc = subprocess.Popen(
        [*SERVER_CMD, "--http", "--port", str(port)],
        env={**os.environ, "RECALL_HOME": str(home), "RECALL_TOKENS": tokens},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    import urllib.request

    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("HTTP server did not start")
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "store"
