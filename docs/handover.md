# Handover: operating recall-kit yourself

This is the runbook for the person who owns the system after it is set up. Everything here is a
command you can run; nothing depends on the author being around.

## 1. What runs where

| Piece | Where | Notes |
|---|---|---|
| Store | `$RECALL_HOME` (default `~/.recall-kit`, `/data/store` in Docker) | `memories/*.md`, `projects/*.md`, `audit.jsonl`, `.git/`, `index.sqlite` |
| MCP server, local | spawned by each client (`rk serve`, stdio) | no network port, full local trust |
| MCP server, VPS | Docker `recall` service, `:8765` inside the compose network | bearer tokens with scopes |
| TLS | Caddy (`deploy/Caddyfile`) | certificates renew automatically |
| Scheduled jobs | host crontab (`deploy/crontab.example`) | brief, backup + verify, off-site copy, doctor |

The markdown files are the source of truth. `index.sqlite` can always be deleted and rebuilt.

## 2. Install

**Laptop:** `uv sync`, then add the server to each client (`clients/README.md`).

**VPS (Ubuntu, 1–2 GB RAM is plenty):**

```bash
git clone https://github.com/sibrahimpa1/recall-kit /opt/recall-kit && cd /opt/recall-kit
cp .env.example .env && chmod 600 .env          # fill DOMAIN, RECALL_ALLOWED_HOSTS, RECALL_BACKUP_PASSPHRASE
uv run rk token new --name laptop --scopes read,write     # or: docker run --rm recall-kit rk token new ...
#   -> paste the "server entry" into RECALL_TOKENS in .env, keep the secret for the client
mkdir -p deploy/backups && sudo chown 10001 deploy/backups
docker compose -f deploy/docker-compose.yml --env-file .env up -d --build
curl https://memory.example.com/healthz          # {"ok": true}
```

Point DNS at the VPS first, open only 22/80/443 (`ufw allow 22,80,443/tcp`), and use SSH keys only.

## 3. Daily operation

| Task | Command |
|---|---|
| Morning brief | `rk brief` (cron writes it to `/var/log/recall-brief.md`) |
| What does it know about X | `rk recall "X"` |
| Review conflicts | `rk conflicts`, then `rk correct <old-id> "..." --source "..."` or `rk forget <id> --yes` |
| Review quarantined memories | `rk list --status ""` → look for `quarantined: true`, then `rk approve <id>` or `rk forget <id> --yes` |
| Calendar of follow-ups | `rk ics --out followups.ics` (import, or serve the file and subscribe) |
| Browse everything | `rk ui --open` (read-only; on a VPS: `ssh -L 8766:127.0.0.1:8766 you@server`, then run `rk ui` there) |
| What did we know on a date | `rk recall "X" --as-of 2026-10-25` |
| Import existing notes | `rk import notes.txt --origin "ChatGPT saved memories" --dry-run`, then without `--dry-run` |
| Health check | `rk doctor` (exit 1 = drift between files, index, vectors or git) |
| History of a memory | `rk history <id>`, or `git -C $RECALL_HOME log -p memories/<id>.md` |

You can also edit the markdown files by hand (in an editor or Obsidian). Then run
`git -C $RECALL_HOME commit -am "manual edit"` and `rk reindex`.

## 4. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Client shows no `memory_*` tools | wrong path in the client config, or `uv` not on the client's PATH | use absolute paths (`which uv`); run the same command in a terminal and look for errors |
| `401 unauthorized` | token missing, mistyped or revoked | compare `sha256(secret)` with the line in `RECALL_TOKENS`; restart after changing `.env` |
| `lacks the 'write' scope` | token is read-only | issue a token with the right scopes, or keep it read-only on purpose |
| `Invalid Host header` in logs | `RECALL_ALLOWED_HOSTS` misses your domain | add `memory.example.com` (and `:*` variants if you use ports) |
| Recall misses something you know is there | `rk stats` shows `embedder: hashing-v1-384` (the keyword-level fallback) | `uv sync --extra semantic` (Docker: `SEMANTIC=1`); the store re-indexes itself on the next start |
| Recall returns nothing for a vague question | the relevance gate found no real evidence | expected; ask with the client's or project's name, or check `rk list` |
| A bad import | wrong file or too much noise | `rk list` shows the `imported` tag and source; `rk forget <id> --yes` per item, or restore last night's backup |
| `rk doctor` reports `orphan_*` or `missing_from_index` | index out of sync (crash mid-write, a restored old index) | `rk reindex`; recall already ignores and heals orphans |
| `uncommitted_changes` in doctor | manual edit not committed | `git -C $RECALL_HOME add -A && git -C $RECALL_HOME commit -m "manual edit"` |
| Slow `forget` | it rewrites git history (`filter-branch`); this grows with commit count | expected (seconds for thousands of commits); see §7 for `git filter-repo` |

## 5. Back up and restore

Backups are tar.gz archives of the store (files and the full git history), encrypted with
AES-256-GCM. The key is derived from `RECALL_BACKUP_PASSPHRASE` with scrypt. A manifest of SHA-256
hashes inside the archive is checked on every restore.

```bash
rk backup create --out backups                       # nightly via cron
rk backup verify backups/recall-<ts>.rkb             # restores into a temp dir, runs doctor
rk backup prune --out backups --keep 14
```

**Disaster recovery (tested end to end in `tests/test_ops.py::test_backup_cli_disaster_recovery`):**

```bash
# new machine, empty disk
export RECALL_BACKUP_PASSPHRASE=...                  # from your password manager
rk backup restore recall-<ts>.rkb --to ~/.recall-kit # decrypt → extract → verify hashes → rebuild index → doctor
rk doctor && rk resume <project>
```

Keep at least one copy off the VPS (`rclone` line in `deploy/crontab.example`). **If you lose the
passphrase, the backups cannot be read.** That is intended.

**Forget vs. backups:** `forget` removes data from the live store and its git history. Backups taken
*before* the forget still contain it until retention removes them (`--keep 14` means 14 days at most).
If you need faster erasure, shorten retention or re-create backups after a forget.

## 6. Rotate credentials and revoke access

**Revoke one client** (lost laptop, ex-contractor, leaked token):

1. Remove that client's entry from `RECALL_TOKENS` in `.env`. Entries are named, e.g. `laptop:read,write:<hash>`.
2. `docker compose -f deploy/docker-compose.yml --env-file .env up -d` (recreates the container with the new env).
3. Check: `curl -s -o /dev/null -w '%{http_code}' -X POST -H "Authorization: Bearer <old>" https://memory.example.com/mcp` returns `401`.
4. Check what that client did: `grep '"actor": "laptop"' $RECALL_HOME/audit.jsonl`. If it wrote something
   wrong, use `rk history` / `rk forget`.

**Rotate all tokens:** create new ones with `rk token new`, replace `RECALL_TOKENS`, restart, then
update each client's config.

**Rotate the backup passphrase:** set the new value, run `rk backup create`, then `rk backup verify`
the new file. Old backups still need the old passphrase until they rotate out.

**Rotate the API key** (only used by the optional LLM eval): revoke it in the Anthropic console,
then set the new value in `.env` or the repo secret.

**Local stdio clients** have no token. Revoking them means removing the server from that client's
config, or removing filesystem access to `$RECALL_HOME`.

**Suspected compromise of the VPS:** stop the stack, rotate every token and the backup passphrase,
restore from a backup taken before the incident onto a fresh VPS, and diff
`git -C $RECALL_HOME log` against the restored copy to see what changed.

## 7. Extend

| Want | Where |
|---|---|
| A different embedding model (Voyage, OpenAI, a multilingual model) | implement `Embedder` in `src/recall_kit/embed.py` (`embed`, `embed_query`, plus `min_similarity`, `conflict_similarity`, `vector_weight`) and return it from `default_embedder()`. Set the thresholds from `uv run python evals/retrieval_bench.py`, not by guessing. The store re-indexes itself when the model name changes. |
| New memory type | `MEMORY_TYPES` in `models.py` |
| New MCP tool | add a `@tool` function in `server.py`, call `_guard(ctx, "<scope>")` first |
| Stricter injection screening | `INJECTION_PATTERNS` in `safety.py`. Add the new case to `INJECTIONS` / `BENIGN` in `tests/test_failure_modes.py` |
| Faster forget on large histories | swap `GitRepo.purge` to `git filter-repo --invert-paths` when it is installed |
| Notion / calendar sync | read `rk brief --json` or `rk ics`. The store is plain files, so one-way exports are cheap |

`RECALL_NOW` overrides the clock (it backdates the demo data and the time-travel tests). Never set it
in normal use.

Before deploying any change, run `uv run pytest`. The continuity suite takes about a minute and catches
regressions in recall, correction, deletion, citation and resume.
