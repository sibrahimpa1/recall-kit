"""Streamable HTTP transport: scoped bearer tokens, revocation, and stdio↔HTTP continuity."""

from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path

import pytest

from recall_kit.auth import new_token

from .conftest import Session, ToolError, http_server, one_call, run_http_session

pytestmark = pytest.mark.continuity


@pytest.fixture
def tokens() -> dict[str, tuple[str, str]]:
    return {
        "reader": new_token("reader", ["read"]),
        "writer": new_token("writer", ["read", "write"]),
        "owner": new_token("owner", ["read", "write", "forget", "admin"]),
    }


def _spec(tokens: dict[str, tuple[str, str]], *names: str) -> str:
    return ";".join(tokens[n][1] for n in names)


def test_scopes_are_enforced_per_tool(home: Path, tokens: dict) -> None:
    secret = {n: t[0] for n, t in tokens.items()}
    with http_server(home, _spec(tokens, "reader", "writer", "owner")) as url:

        async def as_writer(s: Session) -> dict:
            return await s.call(
                "memory_remember", content="Weekly report goes out on Mondays.", source="http test"
            )

        mem = run_http_session(url, secret["writer"], as_writer)
        assert mem["status"] == "created"

        async def as_reader(s: Session) -> list[str]:
            hits = await s.call("memory_recall", query="weekly report")
            errors = []
            for tool, args in (
                ("memory_remember", {"content": "x y z", "source": "r"}),
                ("memory_forget", {"id": mem["id"], "confirm": True}),
            ):
                try:
                    await s.call(tool, **args)
                except ToolError as exc:
                    errors.append(str(exc))
            assert hits["results"][0]["id"] == mem["id"]
            return errors

        errors = run_http_session(url, secret["reader"], as_reader)
        assert len(errors) == 2 and "lacks the 'write' scope" in errors[0] and "'forget'" in errors[1]

        async def writer_forget(s: Session) -> str:
            try:
                await s.call("memory_forget", id=mem["id"], confirm=True)
            except ToolError as exc:
                return str(exc)
            return "deleted"

        assert "lacks the 'forget' scope" in run_http_session(url, secret["writer"], writer_forget)

        async def owner_forget(s: Session) -> dict:
            return await s.call("memory_forget", id=mem["id"], confirm=True)

        assert run_http_session(url, secret["owner"], owner_forget)["status"] == "forgotten"


def _post(url: str, token: str | None) -> int:
    req = urllib.request.Request(
        url,
        data=b"{}",
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        return urllib.request.urlopen(req, timeout=5).status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_missing_wrong_and_revoked_tokens_get_401(home: Path, tokens: dict) -> None:
    with http_server(home, _spec(tokens, "reader", "writer")) as url:
        assert _post(url, None) == 401
        assert _post(url, "rk_not-a-real-token") == 401
        assert _post(url, tokens["writer"][0]) != 401
    # revoke "writer" = drop its line and restart the server
    with http_server(home, _spec(tokens, "reader")) as url:
        assert _post(url, tokens["writer"][0]) == 401
        assert _post(url, tokens["reader"][0]) != 401


def test_http_refuses_to_start_without_tokens(home: Path) -> None:
    with pytest.raises(RuntimeError, match="did not start"), http_server(home, ""):
        pass


def test_memory_written_over_stdio_is_recalled_over_http(home: Path, tokens: dict) -> None:
    """Claude Code on the laptop (stdio) and a remote agent (HTTP) share one memory."""
    mem = one_call(
        home, "memory_remember", content="Harbor Lane's brand colour is teal #0F766E.", source="stdio session"
    )
    with http_server(home, _spec(tokens, "reader")) as url:

        async def recall(s: Session) -> dict:
            return await s.call("memory_recall", query="Harbor Lane brand colour")

        res = run_http_session(url, tokens["reader"][0], recall)
    assert res["results"][0]["id"] == mem["id"]
