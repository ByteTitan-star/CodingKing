# MCP Setup

> 当前状态：MCP 已通过统一 `ResourceLoader` 接入 Agent Runtime。默认关闭，只有显式启用且
> server 位于 `allowlist` 时才会启动。

CoderKing 的 MCP Host 可以从 `.coderking/mcp.json` 加载外部
[Model Context Protocol](https://modelcontextprotocol.io/) 工具，并将其命名为
`mcp_{server}_{tool}`（默认策略：**ask**）。

启用方式任选其一：

```bash
codeking run --mcp "使用已配置的 MCP 工具完成任务"
# 或在 .coderking/config.yaml 中设置 mcp_enabled: true
# 或设置 CODERKING_MCP_ENABLED=true
```

可先运行 `codeking mcp list` 静态检查配置，再用 `codeking mcp check` 实际连接并执行
`initialize` / `tools/list` 探测。

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

1. MCP 显式启用后，`McpHost` 在每次 Agent run 启动 allowlisted servers（stdio + Content-Length framing）
2. Calls `initialize` → `tools/list` and merges schemas into the tool registry
3. Tool calls route to `tools/call` with a 60s timeout
4. Sessions are closed when the agent run finishes
5. Safety: MCP tools use `requires_approval=True` and `mcp_*` policy default `ask`
6. 某个可选资源启动失败会产生 `resource_diagnostic` 事件，四个原子工具仍保持可用

## Mock server (CI)

```bash
python -m coderking.mcp.mock_server
```

Provides a single `echo` tool used by `tests/test_mcp_host.py`.

## GitHub MCP (optional live)

Point a server entry at your preferred GitHub MCP binary / `npx` launcher, add it
to `allowlist`, and approve tool calls when prompted. Live network tests are not
required for CI.
