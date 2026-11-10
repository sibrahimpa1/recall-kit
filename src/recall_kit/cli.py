"""`rk` command line: the same operations as the MCP tools, plus ops commands."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.table import Table

from . import admin, backup
from .auth import new_token
from .projects import ProjectBoard
from .store import MemoryStore, StoreError

app = typer.Typer(
    help="recall-kit: persistent memory + project continuity for AI agents.", no_args_is_help=True
)
project_app = typer.Typer(
    help="Project status, decisions, blockers, next steps, follow-ups.", no_args_is_help=True
)
backup_app = typer.Typer(help="Encrypted backups (RECALL_BACKUP_PASSPHRASE).", no_args_is_help=True)
token_app = typer.Typer(help="Scoped API tokens for the HTTP server.", no_args_is_help=True)
app.add_typer(project_app, name="project")
app.add_typer(backup_app, name="backup")
app.add_typer(token_app, name="token")
console = Console()
ACTOR = os.environ.get("RECALL_ACTOR", "cli")


@app.callback()
def _root(
    home: Annotated[
        Path | None, typer.Option(help="Store directory (default $RECALL_HOME or ~/.recall-kit)")
    ] = None,
) -> None:
    if home:
        os.environ["RECALL_HOME"] = str(home)


def _store() -> MemoryStore:
    return MemoryStore()


def _out(data: Any, as_json: bool = True) -> None:
    if as_json:
        typer.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    else:
        console.print(data)


def _fail(exc: Exception) -> None:
    console.print(f"[red]error:[/red] {exc}")
    raise typer.Exit(1)


@app.command()
def init() -> None:
    """Create (or open) the store and print its location."""
    _out(_store().stats())


@app.command()
def remember(
    content: str,
    source: Annotated[str, typer.Option(help="Where this came from (required)")],
    type: Annotated[str, typer.Option("--type", "-t")] = "fact",
    tag: Annotated[list[str] | None, typer.Option("--tag")] = None,
    project: str | None = None,
    key: str | None = None,
    confidence: float = 0.9,
    force: bool = False,
) -> None:
    """Save a memory."""
    try:
        _out(
            _store().remember(
                content,
                type=type,
                source=source,
                tags=tag,
                project=project,
                key=key,
                confidence=confidence,
                actor=ACTOR,
                force=force,
            )
        )
    except StoreError as exc:
        _fail(exc)


@app.command()
def recall(
    query: str,
    k: Annotated[int, typer.Option("-k", help="Max results")] = 5,
    type: Annotated[str | None, typer.Option("--type", "-t")] = None,
    project: str | None = None,
    all_versions: Annotated[bool, typer.Option("--all-versions")] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Hybrid search; every hit shows its source."""
    res = _store().recall(query, k=k, type=type, project=project, include_superseded=all_versions)
    if as_json:
        return _out(res)
    table = Table(title=f"recall: {query!r}", show_lines=True)
    for col in ("citation", "type", "content", "source"):
        table.add_column(col, overflow="fold")
    for r in res["results"]:
        src = r["source"]
        flag = " [yellow](conflict)[/yellow]" if r.get("conflicts_with") else ""
        table.add_row(
            escape(r["citation"]),
            r["type"],
            escape(r["content"]) + flag,
            escape(f"{src['origin']}\n{src['file']} @ {(src['commit'] or '')[:8]}"),
        )
    console.print(table)


@app.command()
def correct(
    mem_id: str, content: str, source: Annotated[str, typer.Option()], reason: str | None = None
) -> None:
    """Supersede a stale memory with a corrected version."""
    try:
        _out(_store().correct(mem_id, content, source=source, reason=reason, actor=ACTOR))
    except StoreError as exc:
        _fail(exc)


@app.command()
def forget(
    mem_id: str, yes: Annotated[bool, typer.Option("--yes", help="Confirm permanent deletion")] = False
) -> None:
    """Permanently delete a memory (all versions, every layer)."""
    if not yes:
        _fail(StoreError("permanent deletion: re-run with --yes"))
    try:
        _out(_store().forget(mem_id, actor=ACTOR))
    except StoreError as exc:
        _fail(exc)


@app.command()
def history(mem_id: str) -> None:
    """All versions of a memory with git commits."""
    try:
        _out(_store().history(mem_id))
    except StoreError as exc:
        _fail(exc)


@app.command()
def conflicts() -> None:
    """Current memories that appear to disagree."""
    _out(_store().conflicts())


@app.command()
def approve(mem_id: str) -> None:
    """Release a quarantined memory after human review."""
    _out(_store().approve(mem_id, actor=ACTOR))


@app.command("list")
def list_(
    type: Annotated[str | None, typer.Option("--type", "-t")] = None,
    project: str | None = None,
    status: str = "active",
) -> None:
    """List memories (newest first)."""
    rows = _store().find(type=type, project=project, status=status or None)
    _out(
        [
            {
                "id": m.id,
                "type": m.type,
                "content": m.content,
                "source": m.source,
                "updated": m.updated,
                "quarantined": m.quarantined,
            }
            for m in rows
        ]
    )


@app.command()
def stats() -> None:
    _out(_store().stats())


@app.command()
def doctor() -> None:
    """Check files, index, vectors and git agree. Exit code 1 on problems."""
    report = _store().doctor()
    _out(report)
    if not report["ok"]:
        raise typer.Exit(1)


@app.command()
def reindex() -> None:
    """Rebuild the SQLite index (FTS + vectors + conflicts) from the markdown files."""
    _out(_store().reindex())


# ---- projects ----------------------------------------------------------------------------
@project_app.command("update")
def project_update(
    slug: str,
    name: str | None = None,
    status: str | None = None,
    summary: str | None = None,
    note: str | None = None,
) -> None:
    """Create or update a project."""
    try:
        _out(
            ProjectBoard(_store()).upsert(
                slug, name=name, status=status, summary=summary, note=note, actor=ACTOR
            )
        )
    except StoreError as exc:
        _fail(exc)


@project_app.command("add")
def project_add(slug: str, kind: str, text: str, due: str | None = None, owner: str | None = None) -> None:
    """Add a blocker | next_step | followup."""
    try:
        _out(ProjectBoard(_store()).add_item(slug, kind, text, due=due, owner=owner, actor=ACTOR))
    except (StoreError, KeyError) as exc:
        _fail(exc)


@project_app.command("close")
def project_close(slug: str, item_id: str) -> None:
    """Resolve/complete an item (b1, n2, f3)."""
    try:
        _out(ProjectBoard(_store()).close_item(slug, item_id, actor=ACTOR))
    except StoreError as exc:
        _fail(exc)


@project_app.command("decide")
def project_decide(
    slug: str, decision: str, why: Annotated[str, typer.Option()], source: Annotated[str, typer.Option()]
) -> None:
    """Record a decision with its rationale."""
    try:
        _out(
            ProjectBoard(_store()).record_decision(slug, decision, rationale=why, source=source, actor=ACTOR)
        )
    except StoreError as exc:
        _fail(exc)


@project_app.command("list")
def project_list() -> None:
    _out(ProjectBoard(_store()).list())


@app.command()
def resume(slug: str, as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Briefing to resume a project in a fresh session."""
    try:
        b = ProjectBoard(_store()).resume(slug)
    except StoreError as exc:
        return _fail(exc)
    if as_json:
        _out(b)
    else:
        typer.echo(b["markdown"])


@app.command()
def brief(today: str | None = None, as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Daily brief: due follow-ups, stale/blocked projects, memory hygiene."""
    b = admin.daily_brief(_store(), today=date.fromisoformat(today) if today else None)
    if as_json:
        _out(b)
    else:
        console.print(Markdown(b["markdown"]))


@app.command()
def ics(out: Annotated[Path, typer.Option()] = Path("followups.ics"), include_done: bool = False) -> None:
    """Export follow-ups as an iCalendar file (subscribe to it or import it)."""
    out.write_text(admin.followups_ics(_store(), include_done=include_done), newline="")
    _out({"written": str(out)})


# ---- ops ---------------------------------------------------------------------------------
@backup_app.command("create")
def backup_create(out: Annotated[Path, typer.Option()] = Path("backups")) -> None:
    try:
        _out(backup.create(_store().home, out))
    except backup.BackupError as exc:
        _fail(exc)


@backup_app.command("restore")
def backup_restore(file: Path, to: Annotated[Path, typer.Option()], force: bool = False) -> None:
    """Decrypt, extract, verify hashes, rebuild the index, run doctor."""
    try:
        _out(backup.restore(file, to, force=force))
    except backup.BackupError as exc:
        _fail(exc)


@backup_app.command("verify")
def backup_verify(file: Path) -> None:
    """Prove a backup restores (into a temp dir)."""
    try:
        _out(backup.verify(file))
    except backup.BackupError as exc:
        _fail(exc)


@backup_app.command("prune")
def backup_prune(out: Annotated[Path, typer.Option()] = Path("backups"), keep: int = 14) -> None:
    _out({"removed": backup.prune(out, keep)})


@token_app.command("new")
def token_new(
    name: Annotated[str, typer.Option()], scopes: Annotated[str, typer.Option()] = "read,write"
) -> None:
    """Generate a token. Give the secret to the client; add the hash line to RECALL_TOKENS."""
    try:
        secret, line = new_token(name, [s.strip() for s in scopes.split(",")])
    except ValueError as exc:
        return _fail(exc)
    console.print("[bold]Client secret[/bold] (shown once, store it in the client's env):")
    typer.echo(secret)
    console.print("[bold]Server entry[/bold] (append to RECALL_TOKENS, separated by ';'):")
    typer.echo(line)


@app.command()
def serve(http: bool = False, host: str = "127.0.0.1", port: int = 8765) -> None:
    """Run the MCP server (stdio by default, Streamable HTTP with --http)."""
    from . import server

    if http:
        server.run_http(host, port)
    else:
        server.run_stdio()


@app.command()
def demo(reset: bool = False) -> None:
    """Load fictional sample data (made-up clients and projects)."""
    from .seed import seed

    _out(seed(_store(), reset=reset))


if __name__ == "__main__":
    app()
