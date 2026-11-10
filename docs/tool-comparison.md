# When built-in memory is enough, and when it isn't

Short version: if you use **one** assistant and mostly want it to remember preferences, the built-in
memory is enough and costs nothing extra. Build or run something like recall-kit when memory has to be
**shared across tools**, **provably correctable and deletable**, **cited**, or **owned by you**.

## What each option gives you

| | ChatGPT memory | Claude (projects + memory) | Notion (+ Notion AI) | recall-kit (self-hosted) |
|---|---|---|---|---|
| Works across vendors (ChatGPT ↔ Claude ↔ Codex) | no | no | via copy-paste or connectors | yes, any MCP client |
| Human-readable source of truth | partly (memory list in settings) | partly (project knowledge, memory summary) | yes (pages) | yes (markdown files) |
| Full version history | no | no | page history (paid plans) | git, every change |
| Correction semantics (old value never served as current) | best-effort, model-driven | best-effort, model-driven | manual editing | enforced: `correct` supersedes, tested |
| Provable deletion | delete in settings; no proof of what was removed from derived data | same | trash, then permanent delete | file + git history + FTS + vectors scrubbed, with a test that checks every layer |
| Every answer cites its memory | no | partly (project files) | partly (Q&A citations) | yes: `[mem:id]`, file, commit |
| Project status / blockers / next steps / follow-ups | free-form | free-form | yes (databases), strong UI | yes (structured, plus `resume` and `brief`) |
| Prompt-injection handling for stored text | vendor-side | vendor-side | n/a | quarantine on write, data envelope on read |
| Data location / control | vendor | vendor | vendor | your laptop or VPS, encrypted backups |
| Effort to run | none | none | low | you own a small server or a local folder |

## Rough monthly cost (one person)

Approximate list prices as I understand them in late 2026. They change often, so check before quoting
them to anyone.

| Setup | Approx. cost / month | Notes |
|---|---|---|
| ChatGPT Plus with memory | ~$20 | memory included |
| Claude Pro with memory/projects | ~$20 | memory included |
| Notion Plus/Business with AI | ~$10–25 per member | AI included on the higher tiers |
| recall-kit on your laptop only | $0 | stdio, no server; backups to your own disk/cloud |
| recall-kit on a small VPS | ~$5–10 | 1–2 vCPU / 2–4 GB, e.g. budget EU hosts or Hostinger KVM 1–2 |
| + off-site backup storage | <$1 | a few MB of encrypted archives in any S3-compatible bucket |
| + semantic embeddings via an API (optional) | cents | a few thousand short memories cost very little to embed |
| + LLM eval runs (optional) | cents per run | 5 scenarios, ~15 short agent sessions |

The assistants' own subscriptions don't change. recall-kit adds a shared memory next to them.

## Decision guide

- **Stay with built-in memory** if you live in one assistant, you don't need an audit trail, and
  "it mostly remembers my preferences" is the goal.
- **Use Notion as the system of record** if the work is mainly people-facing project tracking with
  a team UI, and AI only needs read access. You can still point agents at it through an MCP connector.
- **Use recall-kit** (or the same design) when:
  - two or more tools (Claude Code, Claude Desktop, Codex, a VPS agent) must share the **same**
    facts and project state;
  - you need to **prove** a correction or a deletion happened (clients, GDPR-style requests);
  - answers must say **where** a fact came from;
  - you want to own the data in plain files you can read, grep, diff and back up.
- **Hybrid (common):** Notion for team-facing project pages, recall-kit for agent memory, and a
  one-way export (`rk brief --json`) into Notion if people want to see it there.

## Known limits of recall-kit (honest list)

- The default embedder is lexical feature hashing: no download, works offline, but it is not semantic.
  A paraphrase with no shared words or word stems can miss. A real embedding model is a one-class
  plug-in (`docs/handover.md` §7).
- Conflict detection is heuristic (similar text plus different numbers or negation). It flags likely
  contradictions, not all of them. Single-valued facts should use a `key`, which is exact.
- Prompt-injection screening is pattern-based. It is defence in depth together with the data envelope
  and tool scopes, not a guarantee.
- `forget` rewrites git history with `filter-branch`. That is fine for thousands of commits, slow for
  millions.
- Backups taken before a `forget` still contain the item until they rotate out.
