# recall-kit

**Persistent memory and project continuity for AI agents, shared across Claude Code, Claude Desktop,
Codex and any MCP client, with a test suite that proves it works across fresh sessions.**

[![CI](https://github.com/sibrahimpa1/recall-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/sibrahimpa1/recall-kit/actions/workflows/ci.yml)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue) ![MCP](https://img.shields.io/badge/MCP-stdio%20%2B%20Streamable%20HTTP-6b4fbb) ![License: MIT](https://img.shields.io/badge/license-MIT-green)

## The problem

People who work with several AI tools hit the same wall. ChatGPT remembers one thing, Claude another,
Codex nothing. Project status lives in a Notion page that no agent reads. When a fact changes, the old
version keeps coming back. When you ask an assistant to "forget that", you can't verify it did. And
nobody can say *where* a remembered "fact" came from.

recall-kit is a small, self-hostable memory layer that fixes this with boring, inspectable parts:

- **Markdown files** are the source of truth: one file per memory, with YAML frontmatter
  (type, source, created/updated, confidence, supersedes, tags).
- **git** versions every change, so history, diffs and restore come free.
- **SQLite FTS5 + vectors** give hybrid (BM25 + embedding) retrieval with a local semantic model
  (no API key). Retrieval quality is [measured](#retrieval-quality-measured), not assumed. The index
  is derived data and can be rebuilt.
- **Time travel:** ask what the memory said on any past date. Deleted items stay deleted there too.
- **A read-only dashboard** to browse memories, version history, conflicts and projects.
- **Import** what you already have: a memory list pasted from ChatGPT or Claude, or a Notion export.
- **MCP** (stdio and Streamable HTTP) lets every client share the same memory and project state.
- A **continuity test suite** runs each "session" as a brand-new process and checks recall,
  correction, deletion, citation and project resume, plus the ways agent memory typically fails.

All names, clients and data in this repo are fictional.

## Demo (real terminal output)

Each `rk` line below is a separate process, so a fresh session every time. The only thing they share
is the store on disk.

![memory lifecycle: remember, recall with source, correct, forget](docs/img/lifecycle.svg)

![resume a project and the daily brief](docs/img/resume.svg)

A reworded question finds the right memory, the same question "as of" an earlier date returns the old
value and flags that it changed, and a question the store can't answer returns nothing:

![paraphrase, time travel, unanswerable question](docs/img/time-travel.svg)

### Dashboard (`rk ui`)

Search with version history and git commits on the right:

![dashboard: search and version history](docs/img/dashboard-memories.png)

The same search as of 25 October:

![dashboard: time travel](docs/img/dashboard-time-travel.png)

Conflicts and quarantined (prompt-injection) items waiting for a person:

![dashboard: review](docs/img/dashboard-review.png)

Projects with blockers, next steps, follow-ups and decisions: [screenshot](docs/img/dashboard-projects.png).

## Architecture

```mermaid
flowchart LR
    subgraph Clients
        CC[Claude Code]
        CD[Claude Desktop]
        CX[Codex]
        VA[VPS agent / any MCP client]
    end
    CC & CD & CX -- stdio --> S1[rk serve]
    VA -- "HTTPS + Bearer token (scoped)" --> CA[Caddy TLS] --> S2[rk serve --http]
    S1 & S2 --> API[MemoryStore + ProjectBoard]
    API -->|write| MD[(memories/*.md\nprojects/*.md)]
    API -->|commit| GIT[(.git history)]
    API -->|index| IDX[(index.sqlite\nFTS5 + vectors + conflicts)]
    API -->|append| AUD[(audit.jsonl\nids only)]
    IDX -. rank .-> API
    MD -. "serve + verify each hit" .-> API
    BK[rk backup] -->|AES-256-GCM| OFF[(encrypted .rkb\noff-site)]
    MD & GIT --> BK
```

Three rules hold everything together:

1. **Files are the truth, the index only ranks.** Recall re-reads every hit from its markdown file,
   so a stale, rolled-back or tampered index cannot serve deleted, superseded or altered text. It
   heals itself instead.
2. **Nothing is overwritten.** `correct` creates a new version that `supersedes` the old one. The old
   version stays in history but is never returned as current.
3. **Deletion is physical.** `forget` removes the file, rewrites git history, deletes the FTS rows and
   vectors, then runs FTS `optimize` + `VACUUM` with `secure_delete`. The audit log records *that*
   something was deleted, never *what*.

### How memory flows between sessions

```mermaid
sequenceDiagram
    participant S1 as Session 1 (Claude Code)
    participant St as Store (files + git + index)
    participant S2 as Session 2 (Codex, days later)
    S1->>St: memory_remember("Harbor Lane pays net-30", source="user, call 11-03", key=client.harbor-lane.terms)
    St-->>S1: created mem_a1 (file + commit + index)
    Note over S1: session ends, process exits
    S2->>St: memory_recall("Harbor Lane payment terms")
    St-->>S2: mem_a1 + source {origin, file, commit}
    S2->>St: memory_correct(mem_a1, "net-45 from December", source="email 11-09")
    St-->>S2: mem_b2 supersedes mem_a1
    S2->>St: project_resume("harbor-portal")
    St-->>S2: status, blockers, next steps, follow-ups, decisions (cited)
```

## Retrieval quality (measured)

`evals/retrieval_bench.py` stores 36 fictional memories and asks three kinds of questions: ones that
share words with the memory, ones reworded to share almost none, and ones the store cannot answer
(the right result is an empty list). Run on 2026-11-10, macOS arm64:

| Mode | Keyword hit@1 (n=20) | Paraphrase hit@1 (n=24) | Paraphrase hit@3 | Unanswerable → empty (n=10) |
|---|---|---|---|---|
| keyword only (raw BM25 baseline) | 95% | 25% | 38% | 80% |
| hybrid, hashing embedder (zero-dependency fallback) | 95% | 4% | 4% | 90% |
| **hybrid, local semantic model (MiniLM, no API key)** | **100%** | **67%** | **79%** | **100%** |

Thresholds were tuned on that set, so here is a second set of 16 questions written before tuning and
never used for it. It is small, so treat it as a sanity check:

| Mode (holdout) | Keyword hit@1 (n=4) | Paraphrase hit@1 (n=8) | Paraphrase hit@3 | Unanswerable → empty (n=4) |
|---|---|---|---|---|
| keyword only (raw BM25 baseline) | 100% | 50% | 75% | 75% |
| hybrid, hashing embedder | 100% | 25% | 25% | 50% |
| **hybrid, local semantic model** | **100%** | **75%** | **88%** | **75%** |

What the numbers changed in the design:

- **The embedding model was picked by measurement.** all-MiniLM-L6-v2 ranked the right memory first
  for 20 of 24 reworded questions before any tuning; bge-small managed 15, and its similarity scores
  for related and unrelated text overlapped too much to set a cut-off.
- **A relevance gate.** A result needs real evidence from at least one side: vector similarity above
  the model's floor, or most of the question's topic words (IDF-weighted). Without it, an unanswerable
  question returns "the nearest thing in the store", which an agent may then state as fact.
- **The hashing embedder is a fallback, not a semantic model.** With it, recall behaves like precise
  keyword search: it rarely answers a reworded question, and the gate removes the lucky single-word
  hits that raw BM25 gets. Install the semantic extra (`uv sync --extra semantic`) for real use;
  recall-kit then uses it automatically and re-indexes itself.

## Test matrix (real results)

Run on macOS arm64 / Python 3.12, `uv run pytest`, 2026-11-10: **54 passed, 1 skipped** (the LLM eval,
because no API key is set). CI runs the same suite on Ubuntu.

| Area | What it proves | Result |
|---|---|---|
| **Continuity: fresh sessions** (each step is a new `rk serve` process + MCP client) | | |
| | two sessions really are different processes (different server PIDs) | ✅ |
| | a fact agreed in session 1 is recalled in session 2 from a *differently worded* question, with its source | ✅ |
| | correcting stale info: new version supersedes the old; old never returned as current; history keeps both; same `key` auto-supersedes | ✅ |
| | delete on request: all versions gone from markdown, index table, FTS, raw SQLite bytes, `git log --all -p`, git object store; survives `reindex`; audit log has the id, not the content; `confirm=false` deletes nothing | ✅ |
| | every recalled item cites a source that matches: file exists, id + content match, cited git commit contains the content, origin attributed to the right memory | ✅ |
| | resume a project: status, open blockers, ordered next steps, follow-up due date, decision + rationale, last note; identical via the CLI (another tool); unblocking flips status | ✅ |
| **Failure modes** (each one reproduced, then detected or prevented) | | |
| | stale wins over fresh: stale text is a far better keyword match → still not returned | ✅ |
| | stale resurrected by index corruption (`status` flipped to `active` in SQLite) → still hidden | ✅ |
| | stale re-asserted from an old chat export → `rejected_stale`, points to the current value | ✅ |
| | duplicates across sessions (case/whitespace variants) → merged, 1 memory | ✅ |
| | deleted item resurfacing from an **old index file** restored after deletion → detected by `doctor`, not served, healed | ✅ |
| | deleted item resurfacing from **orphan embeddings** → detected, not served | ✅ |
| | wrong source: index content tampered → file content + correct source served, `doctor` flags it | ✅ |
| | memory without a source → refused | ✅ |
| | prompt-injected memory content: 6 attack variants (override, fake `SYSTEM:`, exfiltration, tool coercion, `<system>` tags, API key) → quarantined, never recalled | ✅ |
| | …and 4 benign look-alikes ("Ignore the AC noise", "System requirements…") → not quarantined | ✅ |
| | an approved risky memory still arrives inside a "data, not instructions" envelope; quarantine shows up in the daily brief | ✅ |
| | contradicting memories (15th vs 28th) → flagged, newer ranked first, cleared after resolution | ✅ |
| | two clients writing concurrently (Claude Code + Codex simulation) → no lost writes, `doctor` clean | ✅ |
| | unrelated query → empty result, not "nearest noise" | ✅ |
| **Time travel** (sessions weeks apart, via the demo clock) | | |
| | `as_of` returns the value that was current on that date, marks it `changed_since`, cites the snapshot commit; a date before any history returns nothing | ✅ |
| | a forgotten memory is gone from past snapshots too (history is rewritten, dates preserved) | ✅ |
| | a question that matches only the *old* wording returns the *current* version, marked `matched_earlier_version` | ✅ |
| **HTTP + security** | scopes enforced per tool (read/write/forget); missing, wrong and revoked tokens → 401; server refuses to start without tokens; stdio-written memory recalled over HTTP | ✅ |
| **Ops** | encrypted backup → restore (git history intact, same commit SHAs); wrong passphrase and tampered file rejected; restore refuses to overwrite; full disaster-recovery runbook via CLI; prune; daily brief (overdue / due soon / stale / blocked); ICS parses with `icalendar`, RFC 5545 line folding | ✅ |
| **Import** | memory list: dry run writes nothing; real run keeps file + heading as source, tags `imported`, quarantines the injected line, second run creates no duplicates; Notion folder: id suffixes stripped, code/tables/frontmatter skipped | ✅ |
| **Dashboard** | API serves overview, search, time travel, history, review, projects, activity; POST → 405; foreign Host header → 403; page has a CSP and never uses `innerHTML` | ✅ |
| **Semantic model** | reworded question with no shared words finds the memory; unanswerable → empty; switching embedder re-indexes automatically; benchmark floor as a regression guard | ✅ |
| **LLM-in-the-loop** (`evals/llm_eval.py`) | same scenarios driven by a real Claude agent (`claude-opus-5-5`), graded on the answer *and* the store | ⏭ not run: no key set (skips cleanly, tested) |

Full per-test list: CI writes it to the job summary (`scripts/test_matrix.py`).

![continuity suite output](docs/img/continuity-suite.svg)

### What was verified outside the test suite

- **Docker:** image built; container run read-only; `/healthz` OK; `POST /mcp` without a token → 401;
  `memory_remember` + `memory_recall` over Streamable HTTP with a scoped token → stored at `/data/store`.
- **Docker with the semantic model baked in** (`--build-arg SEMANTIC=1`, 898 MB vs 477 MB): a reworded
  question was answered inside a read-only container with no network download at runtime.
- **Dashboard in a real browser:** search, version history, time travel, review and projects tabs
  exercised; no console errors; no horizontal scroll at phone width (375 px).
- **Compose:** `docker compose config` validates. Caddy/TLS needs a real domain, so it was not run here.
- **Real agent client:** see [docs/verification/](docs/verification/) for the status of the Claude Code session check.

## Quick start

```bash
git clone https://github.com/sibrahimpa1/recall-kit && cd recall-kit
uv sync --extra semantic             # local embedding model, ~90 MB download on first use, no API key
                                     # (plain `uv sync` works too: keyword-level recall, zero downloads)
uv run rk demo                       # fictional sample data with a four-week history in ~/.recall-kit
uv run rk recall "how long does the candle company have to settle a bill?"
uv run rk recall "Tallow invoice terms" --as-of 2026-10-25
uv run rk resume northwind-relaunch
uv run rk brief
uv run rk ui --open                  # read-only dashboard on http://127.0.0.1:8766
uv run rk import examples/chatgpt-saved-memories.txt --origin "ChatGPT saved memories" --dry-run
uv run pytest                        # ~2 minutes; the continuity suite is `-m continuity`
```

Core CLI:

```text
rk remember TEXT --source S [--type fact|preference|decision|project] [--key K] [--project P] [--tag T]
rk recall QUERY [-k 5] [--type] [--project] [--all-versions] [--as-of DATE] [--json]
rk correct ID TEXT --source S [--reason R]        rk forget ID --yes        rk history ID
rk conflicts | approve ID | list | doctor | reindex | stats
rk project update|add|close|decide|list ...       rk resume SLUG             rk brief
rk ics --out followups.ics                        rk backup create|verify|restore|prune
rk token new --name N --scopes read,write         rk serve [--http --port 8765]
rk import FILE_OR_FOLDER --origin "where from" [--dry-run]       rk ui [--port 8766] [--open]
```

## MCP tools

| Tool | Scope | Purpose |
|---|---|---|
| `memory_remember` | write | save a fact / preference / decision / project memory (source required; optional `key` for single-valued facts) |
| `memory_recall` | read | hybrid search; every result has `citation`, `source.origin`, `source.file`, `source.commit`. `as_of` answers from a past date |
| `memory_correct` | write | supersede a stale memory |
| `memory_forget` | forget | hard delete across every layer (`confirm=true` required) |
| `memory_history`, `memory_conflicts`, `memory_stats` | read | versions with commits, disagreeing pairs, store info |
| `project_update`, `project_add`, `project_close`, `project_decide` | write | status, blockers, next steps, follow-ups (due dates), decisions with rationale |
| `project_resume`, `project_list`, `daily_brief` | read | the briefing a fresh session needs |

## Connect your clients

Ready-to-paste configs are in [`clients/`](clients/): Claude Code (`claude mcp add …` or `.mcp.json`),
Claude Desktop (`claude_desktop_config.json`), Codex (`~/.codex/config.toml`), and the remote HTTPS
variant with a bearer token. [`integrations/claude-code/`](integrations/claude-code/) adds a
`memory-protocol` skill (when to recall, remember, correct, forget) and a permissions file that
auto-allows reads but asks before `correct` and `forget`. [`integrations/AGENTS.md`](integrations/AGENTS.md)
is the same protocol for Codex and other agents.

## Security and operations

- **Tokens:** per-client, scoped (`read`, `write`, `forget`, `admin`), stored on the server only as
  SHA-256 hashes in `RECALL_TOKENS`. Revoke = delete the line + restart. HTTP mode won't start without
  tokens. Host-header allow-list against DNS rebinding.
- **Dashboard:** read-only, bound to 127.0.0.1, rejects other Host headers. On a VPS, use an SSH tunnel.
- **Secrets only in env:** `.env` (git-ignored), see [`.env.example`](.env.example).
- **Backups:** `rk backup create` = tar of files + full git history, scrypt-derived key, AES-256-GCM,
  hash manifest checked on restore. `rk backup verify` proves a backup restores. Cron example in
  [`deploy/crontab.example`](deploy/crontab.example).
- **Deploy:** [`deploy/docker-compose.yml`](deploy/docker-compose.yml): read-only container,
  non-root, no published port, Caddy in front with automatic TLS.
- **Runbooks:** [docs/handover.md](docs/handover.md) covers operate, troubleshoot, back up/restore,
  rotate credentials, **revoke access**, and extend.
- **When is this worth it vs. built-in memory?** See [docs/tool-comparison.md](docs/tool-comparison.md),
  including rough costs and an honest list of limits.

## LLM-in-the-loop eval (optional)

```bash
export ANTHROPIC_API_KEY=...        # your own key; never committed
uv run --extra eval python evals/llm_eval.py
```

Five scenarios (recall, correction, deletion, resume, injected content). Each session is a new MCP
server process *and* a new conversation with no history. Model: `claude-opus-5-5` (adaptive thinking,
`effort: medium`, server-side refusal fallback). A deterministic grader checks the final answer **and**
the store on disk. For example, after "update the sync to Thursday" there must be exactly one current
sync memory and one superseded one. Results go to `evals/results/`. Without a key it prints `SKIPPED`
and exits 0. In CI it runs only if the repo has an `ANTHROPIC_API_KEY` secret.

## Project layout

```text
src/recall_kit/   store.py (lifecycle, recall, time travel) · index.py (FTS5/vectors) · gitrepo.py · projects.py
                  admin.py (brief, ICS) · backup.py · auth.py · safety.py · embed.py · importer.py
                  server.py (MCP) · ui.py + dashboard.html · cli.py
tests/            continuity, failure modes, time travel, HTTP auth, ops, import, dashboard, semantic
evals/            retrieval benchmark · LLM-in-the-loop eval          examples/   sample imports
clients/          Claude Code / Desktop / Codex configs        integrations/   skill, permissions, AGENTS.md
deploy/           Docker Compose + Caddy + cron                docs/           handover, tool comparison, verification
```

## Author

**Senka Ibrahimpašić**
GitHub [@sibrahimpa1](https://github.com/sibrahimpa1)

Licensed under the [MIT License](LICENSE).
