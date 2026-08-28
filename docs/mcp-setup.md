# MCP Setup

CoderKing can load external [Model Context Protocol](https://modelcontextprotocol.io/)
tools from `.coderking/mcp.json` and expose them to the agent as
`mcp_{server}_{tool}` (default policy: **ask**).

## Config

Create `.coderking/mcp.json`:

```json
{
  "allowlist": ["demo"],
  "mcpServers": {
    "demo": {
      "command": "python",
      "args": ["-m", "coderking.mcp.mock_server"],
      "enabled": true
    }
  }
}
```

- `allowlist`: if non-empty, only listed servers start
- `mcpServers.<name>.command` / `args` / `env`: stdio MCP process
- Disabled servers (`enabled: false`) are skipped

## Behavior

1. On each agent run, `McpHost` starts allowlisted servers (stdio + Content-Length framing)
2. Calls `initialize` → `tools/list` and merges schemas into the tool registry
3. Tool calls route to `tools/call` with a 60s timeout
4. Sessions are closed when the agent run finishes
5. Safety: MCP tools use `requires_approval=True` and `mcp_*` policy default `ask`

## Mock server (CI)

```bash
python -m coderking.mcp.mock_server
```

Provides a single `echo` tool used by `tests/test_mcp_host.py`.

## GitHub MCP (optional live)

Point a server entry at your preferred GitHub MCP binary / `npx` launcher, add it
to `allowlist`, and approve tool calls when prompted. Live network tests are not
required for CI.
