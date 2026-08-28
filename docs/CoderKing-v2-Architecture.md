# CoderKing v2 Architecture

对齐白皮书与 [Pi](https://github.com/earendil-works/pi) 四层分包。本文件是 v2 重构的契约；实现按 Issue #23–#49 分 PR 落地。

## 分层

| Layer | Package | 职责 | 禁止依赖 |
|-------|---------|------|----------|
| L0 | `coderking_llm` | 多厂商 LLM 适配、流式、重试、Token 统计 | `coderking_agent_core`、`coderking_coding_agent`、`coderking_transport`、workspace/sandbox/tools |
| L1 | `coderking_agent_core` | 纯 Agent Loop、Steering/Follow-up、EventStream、hooks | `coderking_coding_agent`、`coderking_transport`、sandbox/git/workspace |
| L2 | `coderking_coding_agent` | Read/Write/Edit/Bash、SessionRepo、压缩、Extensions、SWE harness | FastAPI、Electron、CLI TUI 渲染 |
| L3 | `coderking_transport` | CLI/TUI、HTTP/SSE、RPC stdio、Desktop bridge | 直接改写 messages；只能调用 L1/L2 API |
| Facade | `coderking` (`src/coderking`) | 兼容层与 CLI 入口，渐进 re-export | 新业务逻辑禁止落在此处 |

依赖方向（仅允许向下）：

```text
transport (L3)
    → coding_agent (L2)
        → agent_core (L1)
            → llm (L0)
```

## 目录

```text
packages/
  coderking_llm/src/coderking_llm/
  coderking_agent_core/src/coderking_agent_core/
  coderking_coding_agent/src/coderking_coding_agent/
  coderking_transport/src/coderking_transport/
src/coderking/          # 兼容 facade（现有 Phase 1 代码暂留，按 PR 迁出）
scripts/check_layer_deps.py
```

## 迁移映射（现有 → v2）

| 现有模块 | 目标层 | 目标包 |
|----------|--------|--------|
| `coderking.llm.*` | L0 | `coderking_llm` |
| `coderking.runtime.cancel`（取消原语） | L1 | `coderking_agent_core.cancel` |
| `coderking.runtime.loop` 中纯循环 | L1 | `coderking_agent_core.loop` |
| `coderking.runtime.roles` / harness | L2 | `coderking_coding_agent.extensions.swe` |
| `coderking.tools.*` / `sandbox.*` / `context.*` | L2 | `coderking_coding_agent` |
| `coderking.cli` / `api` / `desktop` | L3 | `coderking_transport` |

## 边界强制

`scripts/check_layer_deps.py` 用 AST 扫描 `packages/*/src` 的 import，违反即失败。CI 在 Ruff 之后执行。

## PR 拆分

1. **PR-1（本 Issue 首 PR）**：脚手架 + 架构文档 + 边界检查 — ✅
2. **PR-2（#25 / #23 续）**：L0 streaming + retry + `OpenAICompatProvider` 迁入 `coderking_llm`；`src/coderking/llm` 仅 facade — ✅
3. **PR-3（#24）**：L1 纯 Loop + Agent 类 — ✅（包内落地；`AgentRuntime` harness 仍在 facade）
4. **PR-4（#38 等）**：L2 四原子工具 + SWE extension；L3 传输层 — 部分完成；`AgentRuntime` harness 仍在 facade

## 验收

- [x] 四层包可被 `pip install -e ".[dev]"` 导入
- [x] `python scripts/check_layer_deps.py` 退出码 0
- [x] 现有 pytest（非 docker）全绿
- [x] 无环依赖（边界脚本覆盖）
- [x] Facade `workspace` + file/read/edit tools 迁入 L2（薄 re-export）
- [x] Facade `sandbox` / shell / `diffing` + cancel → L1/L2（薄 re-export；manager 适配 Settings）
- [x] Facade `runtime/*` SWE harness → L2（`HarnessConfig` + `HarnessBindings`；`AgentRuntime` facade 接线）
