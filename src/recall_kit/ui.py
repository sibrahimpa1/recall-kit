"""Read-only web dashboard: browse memories with their version history, travel back in time,
review conflicts and quarantined items, and see every project's resume briefing.

Local only. It binds to 127.0.0.1, rejects other Host headers (DNS rebinding) and has no write
endpoints: changes go through the CLI or the MCP tools, where they are scoped and audited.
On a VPS, reach it through an SSH tunnel:  ssh -L 8766:127.0.0.1:8766 you@server
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from . import admin
from .projects import ProjectBoard
from .store import MemoryStore, StoreError

PAGE = Path(__file__).with_name("dashboard.html")


def create_app(store: MemoryStore | None = None) -> Starlette:
    store = store or MemoryStore()
    lock = threading.RLock()

    def overview(_: Request) -> JSONResponse:
        with lock:
            brief = admin.daily_brief(store)
            brief.pop("markdown")
            dates = [c["date"][:10] for c in store.git.log(1000)]
            return JSONResponse(
                {
                    "stats": store.stats(),
                    "brief": brief,
                    "history": {"first": min(dates, default=None), "last": max(dates, default=None)},
                }
            )

    def memories(request: Request) -> JSONResponse:
        q = request.query_params.get("q", "").strip()
        as_of = request.query_params.get("as_of") or None
        kind = request.query_params.get("type") or None
        status = request.query_params.get("status", "active")
        with lock:
            try:
                meta: dict[str, Any] = {}
                if q or as_of:
                    res = store.recall(
                        q,
                        k=50,
                        type=kind,
                        as_of=as_of,
                        include_superseded=status == "all",
                        include_quarantined=status != "active",
                    )
                    items = res["results"]
                    meta = {k: res[k] for k in ("as_of", "snapshot_commit", "message") if k in res}
                else:
                    items = [
                        store._item(m)
                        for m in store.find(type=kind, status="active" if status == "active" else None)
                    ]
                    if status == "active":
                        items = [i for i in items if not i.get("quarantined")]
                if status == "quarantined":
                    items = [i for i in items if i.get("quarantined")]
            except StoreError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse({"items": items, **meta})

    def memory(request: Request) -> JSONResponse:
        with lock:
            try:
                return JSONResponse(store.history(request.path_params["mem_id"]))
            except StoreError as exc:
                return JSONResponse({"error": str(exc)}, status_code=404)

    def review(_: Request) -> JSONResponse:
        with lock:
            quarantined = [store._item(m) for m in store.all() if m.quarantined]
            return JSONResponse({"conflicts": store.conflicts(), "quarantined": quarantined})

    def projects(_: Request) -> JSONResponse:
        with lock:
            board = ProjectBoard(store)
            return JSONResponse([board.resume(slug) for slug in board.slugs()])

    def activity(_: Request) -> JSONResponse:
        with lock:
            return JSONResponse(store.git.log(150))

    def index(_: Request) -> HTMLResponse:
        return HTMLResponse(
            PAGE.read_text(),
            headers={
                "Content-Security-Policy": "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            },
        )

    app = Starlette(
        routes=[
            Route("/", index),
            Route("/api/overview", overview),
            Route("/api/memories", memories),
            Route("/api/memory/{mem_id}", memory),
            Route("/api/review", review),
            Route("/api/projects", projects),
            Route("/api/activity", activity),
        ]
    )
    return _LocalOnly(app)  # type: ignore[return-value]


class _LocalOnly:
    """GET-only, and only for Host headers that name this machine."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            host = dict(scope["headers"]).get(b"host", b"").decode().rsplit(":", 1)[0]
            if host not in ("127.0.0.1", "localhost", "[::1]"):
                return await Response("forbidden host", status_code=403)(scope, receive, send)
            if scope["method"] not in ("GET", "HEAD"):
                return await Response("read-only", status_code=405)(scope, receive, send)
        await self.app(scope, receive, send)


def run(port: int = 8766, *, open_browser: bool = False) -> None:
    import uvicorn

    if open_browser:
        import webbrowser

        threading.Timer(0.8, webbrowser.open, [f"http://127.0.0.1:{port}"]).start()
    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="warning")
