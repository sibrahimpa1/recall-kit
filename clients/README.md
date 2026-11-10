# Client configs

One store, many clients. Point every client at the same `RECALL_HOME` (local, stdio) or the same
HTTPS endpoint (VPS, per-client token with its own scopes).

| Client | File | Transport |
|---|---|---|
| Claude Code | [claude-code.md](claude-code.md), [mcp.json](mcp.json) (`.mcp.json`) | stdio or HTTP |
| Claude Desktop | [claude-desktop.json](claude-desktop.json) → `~/Library/Application Support/Claude/claude_desktop_config.json` | stdio |
| Codex CLI / IDE | [codex-config.toml](codex-config.toml) → `~/.codex/config.toml` | stdio or HTTP |
| Any MCP client (Cursor, Hermes Agent, custom) | same `command`/`args`/`env` triple, or the `/mcp` URL + `Authorization: Bearer` header | stdio or HTTP |

Claude Desktop needs absolute paths (`which uv`). Give each client its own token so you can revoke one
without touching the others (`rk token new --name codex-laptop --scopes read,write`).
Only the client you use for clean-ups gets the `forget` scope.
