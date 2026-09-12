# MCP Setup

> 当前状态：MCP Client/Host 与独立连接测试已经实现，但 Agent Runtime 尚未合并 MCP
> 工具；生产接线列入 [M1 资源与扩展系统](CoderKing-Implementation-Roadmap.md)。

CoderKing 的 MCP Host 可以从 `.coderking/mcp.json` 加载外部
[Model Context Protocol](https://modelcontextprotocol.io/) 工具，并将其命名为
`mcp_{server}_{tool}`（默认策略：**ask**）。在 M1 完成前，这些工具不会自动出现在 Agent 工具集中。

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
