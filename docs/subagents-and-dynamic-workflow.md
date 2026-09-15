# Subagents & Dynamic Workflow（Claude Code 风格编排）

日期：2026-09-15
状态：已实现（L1 运行时 + CLI/Web 渲染 + 门控配置 + 测试）

## 1. 目标

在保持"小而稳定的单 agent 内核"原则的前提下，引入两类编排能力：

1. **Subagent**：主 agent 通过 `agent` 工具派生嵌套的单用途 agent，受限工具面 +
   全新上下文，最终回复作为工具结果返回（对应 Claude Code / ZCode 的 Agent tool）。
2. **Dynamic workflow**：模型用 `plan` 工具维护工作计划（TodoWrite 等价），并把
   自包含子任务动态委派给子代理；同轮多个 `agent` 调用并行执行。

## 2. 门控（fail-closed）

沿用资源系统的 fail-closed 原则：**默认关闭**，四原子工具面不变。

| 配置 | 默认 | 说明 |
|------|------|------|
| `dynamic_workflow` | `false` | 开启后注入 `plan` + `agent` 工具、编排提示词段，并把该 run 的工具执行切到 `parallel` |
| `subagent_max_turns` | `16` | 单个子代理的最大轮数 |

配置入口：yaml key / 环境变量 `CODERKING_DYNAMIC_WORKFLOW`、
`CODERKING_SUBAGENT_MAX_TURNS`。

## 3. 子代理类型

| agent_type | 工具面 | 系统提示词要点 |
|-----------|--------|---------------|
| `general-purpose` | read/write/edit/bash/shell/run_tests/git | 自主完成多步改动并自验证；不能再派生子代理 |
| `explore` | read/bash/shell | 只读调查（grep/find/git log），禁止创建/编辑/删除，输出带文件路径与行号的结论 |

## 4. 运行时语义（`runtime/subagent.py`）

- 子代理与父 run 共享：LLM provider、workspace、sandbox、policy engine、
  checkpoint store、审批回调（子代理的写操作照样走 HITL 与检查点）。
- 子代理独有：全新 AgentContext、角色系统提示词、独立 max_turns。
- **状态归属**：子代理写文件的 `changed_files`/检查点计入父任务 —— accept/rollback
  对整个编排一致生效。token 用量累加到父任务。
- **事件转发**：子代理的工具调用以 `tool_call` 事件进入父事件流，payload 带
  `subagent: <description>` 标记；内部 policy/checkpoint/approval 事件同样带标记
  转发（子代理写操作的审批卡片照常出现在 UI）。生命周期事件：
  - `subagent_start {description, agent_type, prompt}`
  - `subagent_end {description, agent_type, ok, summary, tool_calls}`
- **取消**：父取消令牌在每个子代理 turn 前检查。
- **不能嵌套**：子代理的工具池不含 `agent` 工具。
- **并行**：`dynamic_workflow` 开启时父 run 的 `tool_execution` 切为 `parallel`，
  同轮多个 `agent` 调用并发执行（写冲突风险由编排提示词约束：独立子任务才并行）。

## 5. 编排提示词（DYNAMIC_WORKFLOW_PROMPT）

要点：plan 一条 in_progress；子任务 prompt 必须自包含；explore 用于只读扫描、
general-purpose 用于多步修改；独立子任务同轮并行；子代理不能再派生；
子代理完成后必须验证其结论再宣布任务完成。

## 6. UI 渲染

- **Web/Desktop**：带 `subagent` 标记的 tool_call 折叠成"子代理 · 描述"分组
  （左侧强调色边条 + 徽标）；`subagent_start/end` 渲染为状态行；`plan` 工具
  更新走既有 plan_update → 计划卡片。
- **CLI**：`⏺ 派发子代理 desc（type）` / `⏺ 子代理完成[✓] desc · N 次工具调用`；
  子代理内部工具行加 `└ ` 前缀；`⏺ 计划 1/3: …`。

## 7. 测试（tests/test_subagents.py）

1. 工具面门控：默认无 agent/plan；开启后注入且四原子保留。
2. 端到端：父派发 explore → 子代理 read → 返回 summary → 作为工具结果进入父
   上下文；校验子代理工具面受限（无 write/agent）。
3. 未知 agent_type → 工具结果报错，父 run 不失败。
4. plan 工具更新 state.plan 并发 plan_update 事件（首个未完成项标 in_progress）。
5. plan 非法 status → 工具结果报错。

## 8. 后续（B4 候选）

- `run_in_background` 子代理 + 完成通知（当前并行限于同一轮内等待全部完成）。
- 子代理类型注册表开放为配置（自定义角色/工具面）。
- Explore 子代理接入 BM25 检索模块（能力在库、链路未通）。
