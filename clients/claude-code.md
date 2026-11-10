# Claude Code

**Local (stdio, recommended on your own machine):**

```bash
claude mcp add recall --scope user -e RECALL_HOME=$HOME/.recall-kit -- uv run --quiet --directory /path/to/recall-kit rk serve
```

**Remote (your VPS over HTTPS, scoped token):**

```bash
claude mcp add --transport http recall https://memory.example.com/mcp --header "Authorization: Bearer $RECALL_TOKEN"
```

Project-scoped alternative: copy `clients/mcp.json` to `.mcp.json` in a repo.
Recommended permissions and the memory skill: see `integrations/claude-code/`.
