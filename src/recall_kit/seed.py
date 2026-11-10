"""Fictional sample data. Every name, company and date here is made up."""

from __future__ import annotations

import shutil
from typing import Any

from .projects import ProjectBoard
from .store import MemoryStore

SRC = "demo seed (fictional)"

MEMORIES: list[dict[str, Any]] = [
    {
        "content": "Preferred reply style: short answers first, details after, no emojis.",
        "type": "preference",
        "key": "user.reply-style",
    },
    {
        "content": "Working hours are 09:00-17:00 CET; no meetings on Fridays.",
        "type": "preference",
        "key": "user.hours",
    },
    {
        "content": "Client Tallow & Tide Candles pays invoices on net-30 terms.",
        "type": "fact",
        "key": "client.tallow-tide.terms",
        "tags": ["client", "billing"],
    },
    {
        "content": "Client Tallow & Tide Candles' main contact is Ines Marlow (operations lead).",
        "type": "fact",
        "tags": ["client"],
    },
    {
        "content": "Northwind Bikes store runs on Shopify; theme edits go through a staging theme first.",
        "type": "project",
        "project": "northwind-relaunch",
    },
    {
        "content": "VPS is a 2 vCPU / 4 GB box at a budget host; daily snapshots are not enabled yet.",
        "type": "fact",
        "project": "vps-hardening",
        "tags": ["infra"],
    },
]


def seed(store: MemoryStore, *, reset: bool = False) -> dict[str, Any]:
    if reset:
        home = store.home
        store.close()
        shutil.rmtree(home)
        store = MemoryStore(home)
    board = ProjectBoard(store)
    board.upsert(
        "northwind-relaunch",
        name="Northwind Bikes relaunch",
        status="active",
        summary="Rebuild the (fictional) Northwind Bikes storefront with a faster theme and new product filters.",
        note="kick-off done",
        actor="demo",
    )
    board.add_item(
        "northwind-relaunch", "next_step", "Port product filter UI to the staging theme", actor="demo"
    )
    board.add_item("northwind-relaunch", "next_step", "Load-test the collection pages", actor="demo")
    board.add_item(
        "northwind-relaunch", "blocker", "Waiting for product photo export from the client", actor="demo"
    )
    board.add_item(
        "northwind-relaunch",
        "followup",
        "Send staging link for review",
        due="2026-11-12",
        owner="me",
        actor="demo",
    )
    board.upsert(
        "vps-hardening",
        name="VPS hardening",
        status="active",
        summary="Lock down the agent VPS: SSH keys only, firewall, encrypted off-site backups.",
        actor="demo",
    )
    board.add_item("vps-hardening", "next_step", "Disable SSH password login", actor="demo")
    board.add_item(
        "vps-hardening",
        "followup",
        "Run a restore drill from the latest backup",
        due="2026-11-20",
        actor="demo",
    )
    ids = []
    for m in MEMORIES:
        ids.append(
            store.remember(
                m["content"],
                type=m["type"],
                source=SRC,
                tags=m.get("tags"),
                project=m.get("project"),
                key=m.get("key"),
                actor="demo",
            )["id"]
        )
    board.record_decision(
        "northwind-relaunch",
        "Use the platform's native search instead of a third-party search app.",
        rationale="Saves a monthly app fee and the catalogue is under 400 products.",
        source=SRC,
        actor="demo",
    )
    board.record_decision(
        "vps-hardening",
        "Use Caddy for TLS instead of nginx + certbot.",
        rationale="Automatic certificates and a 5-line config; fewer moving parts.",
        source=SRC,
        actor="demo",
    )
    return {"memories": len(ids), "projects": board.slugs(), "home": str(store.home)}
