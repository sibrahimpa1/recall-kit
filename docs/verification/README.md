# Real-client verification

`scripts/verify_claude_code.py` drives **four separate headless Claude Code sessions** (`claude -p`).
Each is a new process with no conversation history, connected to `rk serve` over stdio and sharing
one store:

1. remember a payment term and a gate code, set up a project (next steps, blocker, follow-up, decision)
2. recall the payment term with a citation
3. correct the term, delete the gate code, complete a next step
4. ask for the term, the gate code and the project status → expects the corrected term, no gate code, the resumed project

It then dumps the store and runs `rk doctor`. It also counts how often the deleted code appears in
`git log --all -p`. The transcript is written to `claude-code-sessions.md` in this folder.

```bash
claude /login                       # once, if the CLI isn't signed in
uv run python scripts/verify_claude_code.py
```

**Status:** see `claude-code-sessions.md`. If that file is missing, the check has not been run against
a signed-in client yet. The automated suite (`tests/`) already connects through the official MCP
client library over stdio and Streamable HTTP, one fresh server process per session.
