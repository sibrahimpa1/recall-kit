"""Retrieval benchmark: how often does recall find the right memory, and how often does it
return something for a question the store cannot answer?

Three query sets over 36 fictional memories:
  keyword     the question shares its main words with the memory
  paraphrase  the question is reworded so that it shares (almost) no content words
  unrelated   nothing in the store answers it; the right result is an empty list

Modes: keyword (BM25 only), hashing hybrid (default, zero dependencies), semantic hybrid
(local ONNX model, `uv sync --extra semantic`).

    uv run python evals/retrieval_bench.py            # prints a markdown table
    uv run python evals/retrieval_bench.py --json out.json
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from recall_kit.embed import Embedder, HashingEmbedder
from recall_kit.store import MemoryStore

MEMORIES: dict[str, str] = {
    "terms": "Tallow & Tide Candles pays invoices on net-30 terms.",
    "contact": "The main contact at Tallow & Tide Candles is Ines Marlow, operations lead.",
    "sync": "The weekly sync with Northwind Bikes is on Thursday at 14:00.",
    "shopify": "The Northwind Bikes store runs on Shopify; theme edits go through a staging theme first.",
    "vps": "The agent VPS has 2 vCPU and 4 GB RAM at a budget host in Frankfurt.",
    "ssh": "SSH password login is disabled on the VPS; only key authentication is allowed.",
    "backup": "Encrypted backups run nightly at 02:15 and are copied to an off-site bucket.",
    "style": "Preferred reply style: short answer first, details after, no emojis.",
    "hours": "Working hours are 09:00 to 17:00 CET, and Fridays have no meetings.",
    "pdf": "Harbor Lane Studio wants invoices as PDF attachments, never as links.",
    "fiscal": "Harbor Lane Studio's fiscal year starts in April.",
    "report": "Harbor Lane Studio expects a monthly report on the first Monday.",
    "postgres": "We decided to use Postgres instead of MongoDB for the Harbor Lane portal.",
    "caddy": "We chose Caddy over nginx because it renews TLS certificates automatically.",
    "search": "Northwind uses the platform's native search instead of a paid third-party search app.",
    "colour": "Harbor Lane's brand colour is teal, hex 0F766E.",
    "retainer": "The retainer with Tallow & Tide covers 30 hours per month.",
    "rate": "The hourly rate for new clients is 85 euros.",
    "vat": "Invoices to German clients must show the reverse-charge VAT note.",
    "laptop": "The work laptop is a 14-inch MacBook Pro with 36 GB of memory.",
    "editor": "Code is written in VS Code with the Vim keybindings extension.",
    "python": "New backend services are written in Python 3.12 and managed with uv.",
    "tests": "Every pull request must pass the test suite and the linter before merging.",
    "deploy": "Deployments to production happen on Tuesday mornings only.",
    "domain": "The agency domain is registered at a Swiss registrar and renews every March.",
    "newsletter": "The client newsletter goes out on the last Wednesday of each month.",
    "photos": "Product photos for Northwind are shot on a white background at 2000 pixels wide.",
    "returns": "Northwind accepts returns within 45 days of delivery.",
    "shipping": "Tallow & Tide ships orders with a carbon-neutral courier, flat fee 4.90.",
    "allergy": "Ines Marlow is allergic to peanuts; keep that in mind for team lunches.",
    "timezone": "The Northwind team works in Pacific time, nine hours behind us.",
    "password": "Passwords and API keys are kept in the password manager, never in notes.",
    "llm": "For coding agents we default to the largest model and use the small one for classification.",
    "notion": "Team-facing project pages live in Notion; agent memory lives in recall-kit.",
    "holiday": "The office is closed from 24 December to 2 January.",
    "sso": "The Harbor Lane portal is blocked until IT sends the SSO metadata.",
}

QUERIES: list[tuple[str, str, str | None]] = [
    # keyword
    ("keyword", "Tallow & Tide invoice terms", "terms"),
    ("keyword", "main contact at Tallow & Tide", "contact"),
    ("keyword", "weekly sync with Northwind", "sync"),
    ("keyword", "VPS RAM and vCPU", "vps"),
    ("keyword", "is SSH password login disabled", "ssh"),
    ("keyword", "when do encrypted backups run", "backup"),
    ("keyword", "preferred reply style", "style"),
    ("keyword", "working hours", "hours"),
    ("keyword", "Harbor Lane fiscal year", "fiscal"),
    ("keyword", "Postgres or MongoDB for the portal", "postgres"),
    ("keyword", "why Caddy over nginx", "caddy"),
    ("keyword", "Harbor Lane brand colour", "colour"),
    ("keyword", "retainer hours per month", "retainer"),
    ("keyword", "hourly rate for new clients", "rate"),
    ("keyword", "reverse-charge VAT note", "vat"),
    ("keyword", "which day are production deployments", "deploy"),
    ("keyword", "Northwind returns policy days", "returns"),
    ("keyword", "office closed in December", "holiday"),
    ("keyword", "SSO metadata blocker", "sso"),
    ("keyword", "client newsletter schedule", "newsletter"),
    # paraphrase
    ("paraphrase", "how long does the candle company have to settle a bill?", "terms"),
    ("paraphrase", "who should I email at the candle maker?", "contact"),
    ("paraphrase", "when do we meet the bicycle shop each week?", "sync"),
    ("paraphrase", "how big is our server?", "vps"),
    ("paraphrase", "can someone log in to the server by typing a secret phrase?", "ssh"),
    ("paraphrase", "how is our data protected against disk failure?", "backup"),
    ("paraphrase", "how should answers to me be formatted?", "style"),
    ("paraphrase", "am I available for a call on Friday afternoon?", "hours"),
    ("paraphrase", "in what file format should bills be sent to the design studio?", "pdf"),
    ("paraphrase", "which database did we pick?", "postgres"),
    ("paraphrase", "what handles HTTPS in front of our service?", "caddy"),
    ("paraphrase", "what shade should the studio's buttons be?", "colour"),
    ("paraphrase", "how much time each month is the candle client paying for?", "retainer"),
    ("paraphrase", "what do we charge per hour?", "rate"),
    ("paraphrase", "what tax wording is needed on bills to Germany?", "vat"),
    ("paraphrase", "what computer do I use?", "laptop"),
    ("paraphrase", "which programming language for a new API?", "python"),
    ("paraphrase", "when is it safe to ship a release?", "deploy"),
    ("paraphrase", "how long can a bike customer send an item back?", "returns"),
    ("paraphrase", "what food must we avoid when Ines joins for lunch?", "allergy"),
    ("paraphrase", "what is the time difference with the bicycle shop?", "timezone"),
    ("paraphrase", "where do credentials belong?", "password"),
    ("paraphrase", "when are we off over Christmas?", "holiday"),
    ("paraphrase", "what is holding up the studio's client portal?", "sso"),
    # unrelated: the store has no answer
    ("unrelated", "what is the capital of Mongolia?", None),
    ("unrelated", "recipe for sourdough bread", None),
    ("unrelated", "who won the football match last night?", None),
    ("unrelated", "how tall is Mount Kilimanjaro?", None),
    ("unrelated", "my dentist appointment", None),
    ("unrelated", "lyrics of a lullaby", None),
    ("unrelated", "quantum entanglement explained", None),
    ("unrelated", "best hiking boots for winter", None),
    ("unrelated", "what is the gate code for the storage unit?", None),
    ("unrelated", "which airline flies to Lisbon?", None),
]


# Written before any threshold was tuned and never used for tuning: the honest check.
HOLDOUT: list[tuple[str, str, str | None]] = [
    ("keyword", "Northwind product photos background", "photos"),
    ("keyword", "Tallow & Tide shipping fee", "shipping"),
    ("keyword", "where is the agency domain registered", "domain"),
    ("keyword", "VS Code keybindings", "editor"),
    ("paraphrase", "when does the studio's accounting year begin?", "fiscal"),
    ("paraphrase", "how often does the design studio want a status update?", "report"),
    ("paraphrase", "what must happen before code gets merged?", "tests"),
    ("paraphrase", "which AI model do we pick for sorting tickets into categories?", "llm"),
    ("paraphrase", "where does the team look up project status?", "notion"),
    ("paraphrase", "what does delivery cost for candle orders?", "shipping"),
    ("paraphrase", "how do we find products on the bike store?", "search"),
    ("paraphrase", "which text editor setup do I use?", "editor"),
    ("unrelated", "how do I renew my passport?", None),
    ("unrelated", "symptoms of the flu", None),
    ("unrelated", "price of gold today", None),
    ("unrelated", "who painted the ceiling of the chapel?", None),
]


def evaluate(
    embedder: Embedder, mode: str, queries: list[tuple[str, str, str | None]] | None = None
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        store = MemoryStore(Path(tmp) / "store", embedder=embedder)
        ids = {
            store.remember(text, source="benchmark (fictional)")["id"]: key for key, text in MEMORIES.items()
        }
        stats: dict[str, dict[str, float]] = {}
        misses: list[str] = []
        for kind, query, expected in queries or QUERIES:
            got = [ids[r["id"]] for r in store.recall(query, k=3, mode=mode)["results"]]
            s = stats.setdefault(kind, {"n": 0, "hit1": 0, "hit3": 0, "rr": 0.0, "empty": 0})
            s["n"] += 1
            if expected is None:
                s["empty"] += not got
                if got:
                    misses.append(f"[unrelated] {query!r} -> {got[0]}")
                continue
            if expected in got:
                rank = got.index(expected) + 1
                s["hit3"] += 1
                s["hit1"] += rank == 1
                s["rr"] += 1 / rank
            else:
                misses.append(f"[{kind}] {query!r} -> {got[:1] or 'nothing'} (wanted {expected})")
        store.close()
    out: dict[str, Any] = {"misses": misses}
    for kind, s in stats.items():
        if kind == "unrelated":
            out[kind] = {"n": s["n"], "correctly_empty": s["empty"] / s["n"]}
        else:
            out[kind] = {
                "n": s["n"],
                "hit@1": s["hit1"] / s["n"],
                "hit@3": s["hit3"] / s["n"],
                "mrr": s["rr"] / s["n"],
            }
    return out


def run_all(queries: list[tuple[str, str, str | None]] | None = None) -> dict[str, dict[str, Any]]:
    results = {
        "keyword only (raw BM25 baseline)": evaluate(HashingEmbedder(), "keyword", queries),
        "hybrid, hashing embedder (zero-dependency fallback)": evaluate(HashingEmbedder(), "hybrid", queries),
    }
    try:
        from recall_kit.embed import FastEmbedEmbedder

        semantic = FastEmbedEmbedder()
    except RuntimeError:
        print("semantic extra not installed: skipping (uv sync --extra semantic)", file=sys.stderr)
    else:
        results["vector only, semantic model"] = evaluate(semantic, "vector", queries)
        results["hybrid, semantic model (MiniLM, local, no API key)"] = evaluate(semantic, "hybrid", queries)
    return results


def table(results: dict[str, dict[str, Any]]) -> str:
    def pct(x: float) -> str:
        return f"{x * 100:.0f}%"

    n = {k: results[next(iter(results))][k]["n"] for k in ("keyword", "paraphrase", "unrelated")}
    rows = [
        f"| Mode | Keyword hit@1 (n={n['keyword']}) | Paraphrase hit@1 (n={n['paraphrase']}) | Paraphrase hit@3 "
        f"| Unrelated → empty (n={n['unrelated']}) |",
        "|---|---|---|---|---|",
    ]
    for name, r in results.items():
        rows.append(
            f"| {name} | {pct(r['keyword']['hit@1'])} | {pct(r['paraphrase']['hit@1'])} | "
            f"{pct(r['paraphrase']['hit@3'])} | {pct(r['unrelated']['correctly_empty'])} |"
        )
    return "\n".join(rows)


def main() -> None:
    results = run_all()
    print("Tuning set\n")
    print(table(results))
    holdout = run_all(HOLDOUT)
    print("\nHoldout set (never used for tuning)\n")
    print(table(holdout))
    for name, r in holdout.items():
        print(f"\n[holdout] {name}: {len(r['misses'])} misses")
        for m in r["misses"]:
            print("  ", m)
    if "--json" in sys.argv:
        out = {"tuning": results, "holdout": holdout}
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
