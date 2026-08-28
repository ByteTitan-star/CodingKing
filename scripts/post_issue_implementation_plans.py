#!/usr/bin/env python3
"""Post production-grade implementation plans as GitHub issue comments."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

REPO = "ByteTitan-star/CodingKing"

PI = "https://github.com/earendil-works/pi"
PI_AGENT_LOOP = f"{PI}/blob/main/packages/agent/src/agent-loop.ts"
PI_AGENT = f"{PI}/blob/main/packages/agent/src/agent.ts"

COMMENTS: dict[int, str] = {
    22: """## 生产级实现方案

### Pi 参考
Pi 不在 core loop 内做 E2E，但 `eval/` 与真实 provider 集成是发布门禁。参考 Pi 的 `packages/coding-agent` 在 CI 中对多 provider 的 smoke test 思路：**真实 API 调用 + 固定 fixture repo + 确定性断言**。

### 下一步（按顺序）
1. **Secrets 与 CI 隔离**
   - GitHub Actions 增加 `e2e-live` job，`CODERKING_OPENAI_API_KEY` 来自 repo secret
   - 本地 `.env` 不入库；`eval/reports/` 中不得出现 key
2. **定义 E2E 契约**（`tests/e2e/` 新目录，标记 `@pytest.mark.live`）
   - `test_live_bugfix_add`：对 `eval/tasks/bug_fix/add/repo` 跑 `AgentRuntime`，断言 `TaskStatus.SUCCEEDED` + diff 含修复
   - `test_live_feature_greet` / `test_live_refactor_area`：同上
   - 每 case 超时 10min，失败保存 `.coderking/` 状态到 artifact
3. **CLI 烟雾**
   - `coderking run "fix add in calc.py" --workspace eval/tasks/bug_fix/add/repo` 退出码 0
4. **Eval 报告**
   - `python -m coderking eval --path eval/tasks --report-dir eval/reports` 使用真实 LLM
   - 报告 `extra.llm` 必须记录 model/base_url（非 scripted fixture）
5. **更新验收**
   - 勾选 `docs/phase1-acceptance.md`「真实模型 E2E」

### 代码落点
| 模块 | 路径 |
|------|------|
| E2E tests | `tests/e2e/test_live_agent.py` |
| CI job | `.github/workflows/ci.yml` → `e2e-live` |
| Eval runner | `src/coderking/evalkit/runner.py`（已有，补 live 标记） |

### 验收标准（必须全部满足）
- [ ] CI `e2e-live` 在 secret 配置后 green
- [ ] 3 类 eval task 真实模型 success_rate ≥ 阈值（建议初版 2/3）
- [ ] Token/iteration 写入报告，无 unbounded loop
- [ ] phase1-acceptance 文档更新

### 依赖
- #25 L0 streaming（可选，非阻塞 E2E）
- #24 L1 拆分（不阻塞，但 E2E 应绑定 v2 runtime 入口）

### 禁止做法
- ❌ 用 ScriptedLLM 冒充 live E2E
- ❌ 仅手工点通 Web 无自动化断言
""",
    23: f"""## 生产级实现方案 — v2 四层 Monorepo

### Pi 参考
Pi monorepo 分包：`pi-ai` (L0) → `pi-agent-core` (L1) → `pi-coding-agent` (L2) → `pi-tui`/RPC (L3)。**L1 零领域逻辑**，L2 才注入 Read/Write/Edit/Bash 与会话。

参考：{PI}

### 目标目录结构
```
packages/
  coderking-llm/          # L0: Provider, StreamFn, retry, token accounting
  coderking-agent-core/   # L1: Agent, agentLoop, EventStream, hooks
  coderking-coding-agent/ # L2: tools, SessionRepo, compression, extensions
  coderking-transport/    # L3: CLI TUI, FastAPI/SSE, RPC stdio, Desktop bridge
src/coderking/            # 薄兼容层，re-export，渐进废弃
```

### 下一步（分 4 个 PR，每 PR 可独立 CI green）
**PR-1 脚手架**
- [ ] `pyproject.toml` workspace / uv monorepo 或 hatchling multi-package
- [ ] 各包独立 `pyproject.toml` + 版本 + 公共类型 `Protocol`
- [ ] 文档 `docs/CoderKing-v2-Architecture.md`

**PR-2 提取 L0**
- [ ] 迁移 `llm/provider.py`, `openai_compat.py` → `coderking_llm`
- [ ] 定义 `StreamFn`, `LLMMessage`, `StopReason`, `UsageStats`
- [ ] 现有测试全绿

**PR-3 提取 L1**
- [ ] 新建 `Agent` 类（对标 Pi `Agent`）：subscribe/steer/followUp/abort/waitForIdle
- [ ] `run_agent_loop()` 从 `runtime/loop.py` 抽出，**删除** roles/harness
- [ ] 事件类型对齐 Pi：`agent_start`, `turn_start`, `message_*`, `tool_execution_*`, `agent_end`

**PR-4 提取 L2 + 迁移入口**
- [ ] 现有 5 角色 harness → `coderking_coding_agent.extensions.swe_harness`
- [ ] `AgentRuntime` 变为 L2 对 L1 的 facade
- [ ] CLI/Web 改 import，行为回归测试

### 包边界规则（强制 Code Review）
1. L1 **禁止** import workspace/sandbox/git
2. L2 **禁止** import FastAPI/Electron
3. L3 **禁止** 直接改 messages，只能调用 L1 API

### 验收标准
- [ ] 四层依赖图无环（lint 脚本校验）
- [ ] `pytest` 全通过
- [ ] Epic #4 checklist 中架构项可勾选

### 依赖关系
- 阻塞：#24, #25, #32, #33, #27, #28（均在对应层实现）
""",
    24: f"""## 生产级实现方案 — L1 纯 Agent Loop

### Pi 参考（核心）
- `{PI_AGENT_LOOP}`：`runLoop()` 内外双层循环 + `getSteeringMessages` / `getFollowUpMessages`
- `{PI_AGENT}`：`Agent` 类封装队列、`transformContext`、`beforeToolCall`/`afterToolCall` hooks
- **关键**：`AgentMessage[]` 贯穿全程，仅在 LLM 边界 `convertToLlm()`

### 下一步
**1. 定义类型** (`coderking_agent_core/types.py`)
```python
@dataclass
class AgentContext:
    system_prompt: str
    messages: list[AgentMessage]
    tools: list[AgentTool]

@dataclass
class AgentLoopConfig:
    model: ModelDescriptor
    convert_to_llm: Callable[..., list[dict]]
    transform_context: Callable[..., list[AgentMessage]] | None
    get_steering_messages: Callable[..., list[AgentMessage]]
    get_follow_up_messages: Callable[..., list[AgentMessage]]
    before_tool_call: Callable[..., BeforeToolCallResult] | None
    after_tool_call: Callable[..., AfterToolCallResult] | None
    should_stop_after_turn: Callable[..., bool] | None
    tool_execution: Literal["sequential", "parallel"] = "parallel"
    max_turns: int = 24
```

**2. 实现 `run_agent_loop()`**
- 内层：tool batch → steering poll（每 turn 末 + tool batch 前）
- 外层：agent 将停时 drain follow-up
- `stopReason == "length"` 时 **拒绝执行** 全部 tool calls（Pi 同策略，防 truncated JSON）
- 并行 tool：`asyncio.gather` + 按 source order emit events

**3. 从 `loop.py` 迁出领域逻辑**
- `ROLE_TOOLS`, `_switch_role`, `_try_finish`, harness 测试路由 → L2 extension
- L1 只认识 `AgentTool.execute()` 和 hooks

**4. 事件总线**
- 异步 listener 链，与 Pi 一致：`agent_end` 后 wait all listeners
- 对接现有 `AgentEvent` 或 v2 统一 schema

### 代码落点
| 新建 | 职责 |
|------|------|
| `packages/agent-core/loop.py` | run_agent_loop |
| `packages/agent-core/agent.py` | Agent 有状态包装 |
| `packages/agent-core/events.py` | EventStream |
| `tests/agent_core/test_loop.py` | 纯 loop 单测（mock LLM） |

### 验收标准
- [ ] 无 workspace/sandbox import 的 loop 单测 ≥ 15 cases
- [ ] 覆盖：多 tool 并行、cancel mid-stream、length stop、steering 注入
- [ ] 现有 `test_runtime_loop.py` 通过 L2 harness 适配层

### 依赖
- #25 StreamFn 注入 loop
- #32 #33 steering/follow-up 队列由 Agent 类提供

### 禁止做法
- ❌ 在 L1 保留 `Role.PLANNER` 等枚举
- ❌ 单文件 800 行 loop 不拆分
""",
    25: """## 生产级实现方案 — L0 LLM Streaming + Retry

### Pi 参考
- `packages/ai`：`streamFunction(model, context, options)` 返回 async iterator
- `agent-loop.ts` 中 `streamAssistantResponse` 消费 `start/text_delta/toolcall_delta/done/error`
- `maxRetryDelayMs` + provider 层指数退避

### 下一步
**1. StreamFn 协议** (`coderking_llm/stream.py`)
```python
class StreamEvent(TypedDict): ...
async def stream_chat(...) -> AsyncIterator[StreamEvent]:
    ...
async def complete(...) -> LLMResponse:  # 内部 aggregate stream
```

**2. OpenAI Compatible 流式实现**
- SSE 解析：`data: [DONE]`、delta.tool_calls 增量合并
- 部分 provider 不支持 tools+stream：fallback 非流式（可配置）
- `httpx` async stream + cancel token 关闭 connection

**3. Retry 策略**（独立 `RetryPolicy`）
- 可重试：429, 502, 503, 504, connect timeout
- 指数退避 + jitter，`Retry-After` header 尊重
- 不可重试：401, 400 tool schema 错误
- 每次 retry 产生 telemetry event

**4. Token / Usage 累计**
- 流式过程中累计 prompt/completion/cache tokens
- 对接 `token_event` 实时推送 Web

**5. 集成 L1**
- `streamAssistantResponse` 等价物：emit `message_update` 每个 delta
- CLI/Web 可选 `--stream` / WS `message_delta`

### 代码落点
- `packages/coderking-llm/openai_compat.py`（重写）
- `packages/coderking-llm/retry.py`
- `tests/llm/test_stream_parser.py`（fixture SSE 文件）

### 验收标准
- [ ] 流式单测：text + tool_call 交错 delta 正确合并
- [ ] Retry 单测：mock 429 → 2 次后成功
- [ ] Cancel mid-stream 不泄漏 connection
- [ ] 与 DeepSeek/GLM 兼容（integration 可选 mark live）

### 禁止做法
- ❌ 伪 streaming（等完整响应再 chunk 打印）
- ❌ 无限 retry
""",
    42: """## 生产级实现方案 — 显式五阶段 FSM

### Pi 参考
Pi 不显式命名五阶段，但每 turn 可映射：
1. **Perceive** → `transformContext` + `convertToLlm`
2. **Decide** → `streamAssistantResponse`
3. **Act** → `executeToolCalls`
4. **Observe** → tool results append to messages
5. **Re-perceive** → steering poll + follow-up outer loop

CoderKing 应在 L1 **显式**建模 FSM 以便 observability 与 policy 挂载。

### 下一步
**1. 定义 FSM** (`agent_core/fsm.py`)
```python
class LoopPhase(StrEnum):
    PERCEIVE = "perceive"
    DECIDE = "decide"
    ACT = "act"
    OBSERVE = "observe"
    RE_PERCEIVE = "re_perceive"
    TERMINATED = "terminated"
```

**2. 转移表（确定性）**
| From | Event | To |
|------|-------|-----|
| PERCEIVE | context_ready | DECIDE |
| DECIDE | assistant_message | ACT (if tools) / RE_PERCEIVE (if no tools) |
| ACT | tools_done | OBSERVE |
| OBSERVE | results_appended | RE_PERCEIVE |
| RE_PERCEIVE | continue | PERCEIVE |
| * | cancel/max_turns/policy | TERMINATED |

**3. Phase hooks（扩展点）**
- `on_enter_perceive(ctx)`：L2 注入 AGENTS.md、compression
- `on_enter_act(ctx)`：Safety Policy 批量校验 tool calls
- 每 phase 切换 emit `phase_change` event

**4. 与现有 harness 关系**
- 5 角色逻辑是 L2 `prepareNextTurn` hook，**不是** FSM 状态

### 验收标准
- [ ] 单测验证非法转移 raise
- [ ] Web UI 展示当前 phase（可选）
- [ ] OpenTelemetry span per phase（推荐）

### 依赖
- #24 L1 拆分完成后嵌入 FSM
""",
    26: """## 生产级实现方案 — Edit 工具

### Pi 参考
Pi `edit` 工具：**严格字符串替换**，执行前校验 `old_string` 在文件中**恰好出现 1 次**；0 次或多于 1 次 → 结构化错误，要求模型提供更多上下文行。可选 fuzzy match 仅用于 whitespace 差异。

### 下一步
**1. 工具 schema**
```python
class EditFileTool(Tool):
    name = "edit"
    parameters = {
        "path": str,
        "old_string": str,
        "new_string": str,
        "replace_all": bool = False,  # 默认 False，True 时要求明确 opt-in
    }
```

**2. 核心算法** (`tools/edit.py`)
- 读取 raw bytes → 检测 encoding（charset-normalizer）→ 统一内部 str
- 规范化换行符为 `\\n` 做匹配，写回时恢复原始 eol 风格
- `count = text.count(old_string)`：
  - `count == 0` → 尝试 fuzzy（Levenshtein block / whitespace-normalized window）
  - `count == 1` → apply
  - `count > 1 and not replace_all` → 错误 + 返回所有 match 行号
- 写前 `invalidate_bytecode`（已有）
- 返回 unified diff snippet（≤2KB）供 model 确认

**3. 安全**
- `ensure_inside(workspace, path)` 已有
- 二进制文件拒绝
- 单文件单次 edit `old_string` max 64KB

**4. 测试矩阵**
- 唯一匹配 / 零匹配 / 多匹配 / fuzzy / CRLF / tab 差异 / 中文 UTF-8

### 代码落点
- `packages/coding-agent/tools/edit.py`
- `tests/tools/test_edit.py`（≥20 cases）
- 注册到 L2 default tools，#38 迁移时保留

### 验收标准
- [ ] 对标 Pi 行为：多匹配必须失败
- [ ] eval bug_fix 任务优先用 edit 而非 write_file 全量覆写（token 下降可度量）

### 禁止做法
- ❌ AST rewrite（白皮书明确拒绝）
- ❌ LLM 全量覆写冒充 edit
""",
    27: """## 生产级实现方案 — JSONL 树状会话

### Pi 参考
Pi coding-agent Session v4：`SessionRepo` append-only JSONL，每行一个 node，`id` + `parentId` + `head` pointer，支持 branch/fork 不删历史。

### 下一步
**1. 数据模型**
```python
@dataclass
class SessionNode:
    id: str          # ulid
    parent_id: str | None
    kind: Literal["message","compression","branch_marker","system"]
    payload: dict
    created_at: datetime
```

**2. SessionRepo** (`coding_agent/session/repo.py`)
- 文件：`.coderking/sessions/{session_id}.jsonl`
- `append(node)`：fsync 每行（或 batch + fsync every N ms 可配置）
- `head` 存 `.coderking/sessions/{session_id}.head` 单行 JSON
- `branch_to(node_id)`：移动 head，不删后续行
- `walk_to_head()`：从 root 沿 parent 链到 head，O(depth)
- 崩溃恢复：tail 损坏时 truncate 到最后合法 JSON line

**3. 与 Agent 集成**
- L1 `Agent.state.messages` 由 `SessionRepo.materialize(head)` 生成
- 每条 message/tool result 写入新 node
- compression node（#28）作为 `kind=compression` 插入树

**4. 迁移**
- `registry.py` session.json → import 脚本生成首条 jsonl
- CLI `chat` resume 读 head

### 验收标准
- [ ] 单测：branch 后两条路径共存
- [ ] kill -9 模拟后 recovery
- [ ] 10k nodes walk < 50ms（benchmark test）

### 依赖
- #28 compression 写 compression node
- #24 L1 messages 来源改为 SessionRepo

### 禁止做法
- ❌ SQLite 存全量 messages（失去 append-only 崩溃安全）
- ❌ 仅 flat JSON array
""",
    28: """## 生产级实现方案 — 动态上下文压缩

### Pi 参考
- L1 hook：`transformContext(messages, signal)` 在 **每次 LLM 调用前**执行
- L2 实现：超阈值时用**廉价模型**或规则摘要 early turns，插入 compression node（#27）

### 下一步
**1. TokenBudget** (`coding_agent/context/budget.py`)
- 使用 `tiktoken` 或 provider tokenizer 估算
- 配置：`context_window`, `reserve_completion`, `compress_threshold`（默认 0.75）

**2. CompressionStrategy**
- **Phase A（确定性）**：保留 system + 最近 K turns + 所有 edit 涉及的文件当前内容
- **Phase B（LLM 摘要）**：对 early tool outputs 调用 fast model，输出结构化 JSON：
  ```json
  {"decisions":[],"errors":[],"open_tasks":[],"files_touched":[]}
  ```
- 摘要写入 SessionRepo compression node（#27）
- 后续 `materialize()` 展开为一条 `role=system` 的 compression message

**3. 触发时机**
- `transform_context` hook 内：estimated_tokens > threshold → compress
- 压缩本身 async，带 cancel；失败 fallback Phase A only

**4. 可观测**
- emit `context_compressed` event：before/after tokens

### 验收标准
- [ ] 200 turn 模拟 transcript 压缩后 < threshold
- [ ] 压缩后 eval 任务成功率不下降 >5%（live 对比）
- [ ] 摘要 node 可人工 inspect（jsonl 一行）

### 依赖
- #27 SessionRepo
- #25 摘要用 fast model stream

### 禁止做法
- ❌ 粗暴 truncate 最后 N 条
- ❌ 同步阻塞 loop 30s+ 无 timeout
""",
    29: """## 生产级实现方案 — AGENTS.md / SYSTEM.md

### Pi 参考
Pi 启动加载项目根 `AGENTS.md`，作为 **渐进式披露** 的一部分，不写入 10k system prompt。

### 下一步
**1. ProjectInstructionsLoader** (`coding_agent/context/project_docs.py`)
- 搜索顺序：`AGENTS.md` > `SYSTEM.md` > `.coderking/AGENTS.md`
- max 8KB per file，超出截断 + warning event
- hash 缓存：mtime 不变不重复读

**2. 注入点（L2 hook，非 L1 hardcode）**
- `on_enter_perceive` 或 `prepareNextTurn`：首次 turn 注入 `role=user` 或 system appendix：
  ```
  <project_instructions source="AGENTS.md">...</project_instructions>
  ```
- **不**在每次 turn 重复注入（Pi 缓存友好）

**3. CLI/Web**
- `coderking init` 生成 AGENTS.md 模板
- Web 设置页展示已加载 doc hash

### 验收标准
- [ ] 有/无 AGENTS.md 行为差异单测
- [ ] Token 审计：注入 ≤8KB
- [ ] 文档 `docs/project-instructions.md`

### 依赖
- #31 极简 prompt 策略
- #24 L2 hook 挂载点
""",
    30: """## 生产级实现方案 — Skills 延迟加载

### Pi 参考
Pi extensions/skills：能力打包为模块，**判定需要时**才注入详细指令（见 coding-agent extensions 体系）。

### 下一步
**1. Skill 清单格式** (`.coderking/skills/{name}/SKILL.md`)
```yaml
---
name: swe-repair
description: "Run pytest repair loop"
triggers: ["test failed", "pytest", "repair"]
max_inject_tokens: 2000
---
# 详细指令...
```

**2. SkillRegistry**
- 启动只加载 frontmatter（≤100 tokens/skill）
- `SkillMatcher`：用户 prompt + 最近 tool 输出 keyword/embed 匹配
- 命中后 `inject_skill(name)` → append 一条 system/user message（一次/session 或按 turn 限频）

**3. 与 Cursor Skills 对齐**（可选）
- 支持读取 `~/.cursor/skills/*/SKILL.md`

**4. API**
- L2：`agent.register_skill_trigger(matcher, loader)`

### 验收标准
- [ ] 10 skills 启动 token < 1k
- [ ] 命中/未命中单测
- [ ] 误触发率：benchmark 100 prompts < 5% false positive（人工集）

### 依赖
- #29 渐进式披露
- #28 压缩时保留已激活 skill 摘要
""",
    31: """## 生产级实现方案 — 极简 System Prompt

### Pi 参考
Pi ~150 word system prompt：身份 + 四工具 + 安全约束。**不**预注入 repo 全文。

### 下一步
**1. 拆分 prompt 来源**
| 来源 | 时机 | 上限 |
|------|------|------|
| core_system | 固定 | 800 tokens |
| project_instructions | 首 turn | 2k (#29) |
| skill_inject | 按需 | 2k/skill (#30) |
| repo_context | **禁止**启动全量注入 | 0 |

**2. 移除 loop.py 启动注入**
- 删除 `scan_repository` + BM25 全量塞进首条 system（`loop.py:82-96`）
- 改为 L2 extension `repo_context` skill：模型 **主动** `read`/`bash find`

**3. Token 审计 CI**
- 单测：`assert count_tokens(core_system) < 1000`
- eval 对比首 turn prompt tokens 下降 ≥40%

### 验收标准
- [ ] core system prompt 文件化 `prompts/core.md`，版本化
- [ ] 无 README 2500 字硬注入
- [ ] eval 成功率不回归（live）

### 依赖
- #29 #30
- #38 四工具迁移后 prompt 只描述 4 tools
""",
    38: """## 生产级实现方案 — 四原子工具架构迁移

### Pi 参考
仅 Read / Write / Edit / Bash。Git、Test、Search 通过 Bash + 项目脚本或 extensions 提供。

### 下一步（分阶段，每阶段 CI green）
**Phase A — 工具合并**
- [ ] `create_file` → `write`（同 schema）
- [ ] `read_file` → `read`（#39 增强）
- [ ] 新增 `edit`（#26）
- [ ] `shell` → `bash`

**Phase B — 领域工具降级为 Extension**
- [ ] `run_tests` → `coding_agent.extensions.pytest`：注册 optional tool + harness hook
- [ ] `git_*` → extension 或 bash only
- [ ] `search_code` → bash `rg` 或 read+glob
- [ ] 5 角色 meta tools → `extensions.swe_workflow.SweHarness` 实现 `prepareNextTurn` + `shouldStopAfterTurn`

**Phase C — 默认 Agent 配置**
- 默认 L1 tools = 4
- `coderking run --extension swe` 启用 SWE harness（兼容现有 eval）

### 迁移映射
| 现有 | v2 |
|------|-----|
| `runtime/roles.py` | `extensions/swe/roles.py` |
| `tools/meta.py` | harness hooks |
| `test_harness_guards.py` | extension tests |

### 验收标准
- [ ] 默认模式 tool schema ≤4
- [ ] `--extension swe` 通过全部现有 runtime tests
- [ ] eval 三套任务两种模式均 pass

### 依赖
- #24 #26 #39 #40
""",
    39: """## 生产级实现方案 — Read 工具增强

### Pi 参考
Read 支持：行号输出、offset/limit、glob 批量、图片 base64（vision model）。

### 下一步
**1. Schema 扩展**
```python
{
  "path": str,              # file or directory
  "offset": int = 1,
  "limit": int = 2000,      # lines
  "glob": str | None,       # when path is dir
}
```

**2. 实现** (`tools/read.py`)
- 单文件：返回 `{line_no}|{content}`（1-based，Pi 风格）
- 目录+glob：最多 50 files，每 file 最多 500 lines，总输出 cap 100KB
- 图片：`.png/.jpg/.webp` → base64 + mime，返回 `type=image` content block（对接 L0 multimodal message）
- 二进制非图片：拒绝 + suggest bash `file`

**3. 性能**
- mmap 大文件按 line 迭代，不一次性 read 80k char（现有问题）

### 验收标准
- [ ] 行号与 editor 对齐单测
- [ ] 1MB 文件 offset/limit 内存稳定
- [ ] vision model integration test（mock）

### 依赖
- #38 rename read_file → read
""",
    40: """## 生产级实现方案 — Bash 异步后台 Job

### Pi 参考
Bash 支持 long-running：后台启动 + poll output，防止 dev server 阻塞 loop。

### 下一步
**1. JobManager** (`sandbox/job_manager.py`)
- `start(command) -> job_id`：sandbox 内 `nohup`/detached 或 docker exec -d
- `poll(job_id) -> {status, stdout_tail, stderr_tail, exit_code?}`
- `kill(job_id)`
- TTL：默认 1h 自动 cleanup

**2. Tool schema**
- `bash` 增加 `background: bool`, `job_id` for poll 子命令或独立 tools `bash_poll`/`bash_kill`（Pi 风格单一 bash + params）

**3. Sandbox 抽象**
- `SandboxBackend.start_job()` / `read_job_output()` 接口
- Docker：container 内 pid file + log file mount
- Local：asyncio subprocess + ring buffer（max 1MB）

**4. Loop 集成**
- background job 不 block turn；model 需主动 poll（符合 ReAct）

### 验收标准
- [ ] `npm run dev` background + poll 单测
- [ ] cancel agent 时 kill 所有 sandbox jobs
- [ ] 无 zombie 进程（docker ps 断言）

### 依赖
- #45 CoW 可选（job 日志隔离）
""",
    32: f"""## 生产级实现方案 — Steering 转向控制

### Pi 参考（必读）
`{PI_AGENT}`：
- `steer(message)` → `steeringQueue`
- `getSteeringMessages` 在 **每个 turn 开始** 和 **tool batch 后** drain
- tool 执行中用户 steer → 当前 tool 完成后 **不再执行** 同 assistant message 剩余 tools

`agent-loop.ts` `executeToolCalls` 需在 batch 间检查 steering flag。

### 下一步
**1. Agent API**
```python
agent.steer(AgentMessage(role="user", content="停止改 A，先修 B"))
```

**2. Tool batch 中断**
- sequential/parallel 模式均：每 tool 后 `steering = drain_steering()`
- 若 non-empty：mark remaining tools `cancelled`，inject user messages，break inner loop

**3. Transport 暴露**
- WebSocket：`{{"type":"steer","content":"..."}}`
- RPC stdio（#34）：`steer` method
- CLI：stdin 监听 thread（interactive 模式）

**4. 与 cancel 区别**
- cancel：AbortSignal，整 run 终止
- steer：graceful redirect，session 继续

### 验收标准
- [ ] 单测：3 tool calls，steer after #1 → #2 #3 skipped
- [ ] Web UI steer 按钮 E2E
- [ ] 无 race（steer during parallel tools）

### 依赖
- #24 L1 Agent 类
""",
    33: """## 生产级实现方案 — Follow-up 跟进队列

### Pi 参考
`followUp(message)` → 仅当 agent **would stop**（无 tool、无 steering）时 outer loop drain follow-up，作为新 turn 输入。

### 下一步
**1. Agent API**
```python
agent.follow_up(AgentMessage(...))
```

**2. Outer loop**（`agent-loop.ts:262-268`）
```python
while True:
    run_inner_loop()
    if should_stop():
        fu = drain_follow_up()
        if fu:
            pending = fu
            continue
    break
```

**3. 与 chat 区别**
- 现有 `cli chat` 是 **进程间** 新 prompt
- follow-up 是 **同 run 内** 队列，保证 tool state 一致

**4. Transport**
- Web：用户在 agent 运行完毕前排队「完成后帮我 commit」

### 验收标准
- [ ] agent 完成后自动执行 follow-up 无需新 CLI  invocation
- [ ] follow-up 不 interrupt 当前 tool batch（与 steer 对比单测）

### 依赖
- #24 #32
""",
    34: """## 生产级实现方案 — RPC JSONL over Stdio

### Pi 参考
- `packages/coding-agent/src/rpc-entry.ts`
- `modes/rpc/`：stdin/stdout 逐行 JSON-RPC 2.0
- Desktop spawn 子进程，不经过 HTTP

### 下一步
**1. 协议** (`transport/rpc/protocol.md`)
```jsonl
{"jsonrpc":"2.0","id":1,"method":"agent.prompt","params":{"text":"fix bug"}}
{"jsonrpc":"2.0","method":"agent.event","params":{"type":"tool_execution_start",...}}
```

**2. 方法集**
- `agent.prompt` / `agent.steer` / `agent.follow_up` / `agent.abort` / `agent.wait_idle`
- `session.load` / `session.branch`
- events 为 notification（无 id）

**3. 实现**
- `coderking rpc` 命令：async read stdin line-by-line，write stdout flush per event
- 背压：stdout buffer 满时 pause tool event emit
- 结构化 logging 仅 stderr

**4. Desktop 集成（#49）**
- Electron `spawn('coderking', ['rpc'])` + line protocol

### 验收标准
- [ ] Python client 驱动 rpc 完成 eval bug_fix
- [ ] 1000 events/s 不 deadlock（stress test）
- [ ] 协议文档 + JSON Schema

### 依赖
- #24 L1 Agent
- #49 Desktop
""",
    35: """## 生产级实现方案 — SSE EventStream API

### Pi 参考
Pi Web/server 模式暴露 event stream；CoderKing 可对齐 SSE 便于 Serverless/CDN。

### 下一步
**1. Endpoint**
```
GET /api/v2/tasks/{id}/events
Accept: text/event-stream
Last-Event-ID: {node_id}  # 断线重连
```

**2. 实现** (`transport/http/sse.py`)
- 映射 L1 `AgentEvent` → SSE `event:` + `data:` + `id:`
- Redis/Kafka 可选持久化（多实例）；单实例先用 memory ring + SessionRepo tail

**3. 与 WebSocket 共存**
- v2 推荐 SSE（单向 push）+ REST（control）
- WebSocket 标记 deprecated，保留 1 版本

**4. 断线重连**
- Last-Event-ID 重放 jsonl nodes since id

### 验收标准
- [ ] curl 可消费 stream
- [ ] 断线重连不丢 event（单测）
- [ ] load test 100 concurrent streams

### 依赖
- #24 event schema 稳定
- #27 node id 作 SSE id
""",
    43: """## 生产级实现方案 — Safety Policy Engine

### Pi 参考
Pi `beforeToolCall` hook：返回 `{action: "allow"|"deny"|"ask", reason}` 统一门禁。

### 下一步
**1. PolicyEngine** (`coding_agent/safety/policy.py`)
```yaml
# .coderking/policy.yaml
tools:
  bash:
    deny_patterns: ["rm -rf /", "curl.*|.*sh"]
    ask_patterns: ["git push", "npm publish"]
  write:
    deny_paths: [".env", "**/secrets/**"]
```

**2. 集成 L1 hook**
- 替换散落 `ShellTool.needs_approval`、`delete_file.requires_approval`
- parallel tools：batch validate before execute

**3. 决策记录**
- 每条 deny/ask 写 SessionRepo audit node
- Web 展示 policy violation

**4. 扩展**
- OPA/Rego 可选 backend（企业）

### 验收标准
- [ ] 策略变更无需改 Python 代码
- [ ] 单测覆盖 deny/ask/allow
- [ ] 与 HITL approval UI 打通

### 依赖
- #24 beforeToolCall hook
""",
    45: """## 生产级实现方案 — Copy-on-Write 文件系统

### 下一步（生产级）
**1. SandboxBackend 扩展**
- Docker：每 task 创建 ephemeral volume / overlay2 snapshot
  - 启动：`docker volume create` + mount `/workspace` copy from bind（rsync 或 docker cp 初快照）
  - 结束：diff vs baseline → export patch；rollback = 丢弃 volume
- 可选：Dagger / BuildKit 缓存层

**2. 接口**
```python
class WorkspaceSnapshot(Protocol):
    async def commit(self) -> SnapshotId
    async def rollback(self, id: SnapshotId) -> None
    async def diff(self, id: SnapshotId) -> str
```

**3. 与现有 diffing 关系**
- 保留 git-style unified diff 输出
- 内存 snapshot 仅作 fast path；Docker 任务必须 CoW

### 验收标准
- [ ] 10k file repo rollback < 3s
- [ ] 并发 5 tasks 文件系统隔离
- [ ] interrupt 自动 rollback 可选配置

### 依赖
- Docker sandbox (#7 done)
""",
    46: """## 生产级实现方案 — 沙盒网络域名白名单

### 下一步
**1. NetworkPolicy**
```yaml
sandbox:
  network: restricted  # none | full | restricted
  allow_hosts:
    - pypi.org
    - files.pythonhosted.org
    - registry.npmjs.org
```

**2. 实现路径（按优先级）**
- **Docker + internal proxy**：sidecar `squid`/`mitmproxy` 容器，仅允许 whitelist DNS；agent 容器 `--network container:proxy`
- 禁止：仅 `--network none` 无法 pip install

**3. 审计**
- 拒绝连接 log + agent event

### 验收标准
- [ ] pip install 成功 + curl google.com 失败
- [ ] 误配 whitelist 有 clear error

### 依赖
- Docker (#7)
""",
    47: """## 生产级实现方案 — 凭据与沙盒完全隔离

### 下一步
**1. Mount 策略**
- Docker bind mount **只读** 项目源码子集：
  - exclude: `.env`, `.git/config`, `**/*credentials*`, `.coderking/`
- 使用 `.dockerignore` 风格 manifest

**2. LLM 调用**
- 仅 host 进程持有 `CODERKING_OPENAI_API_KEY`
- Sandbox 内 `env` 白名单，strip 所有 `CODERKING_*` / `OPENAI_*`

**3. 审计 CI**
- 单测：docker inspect 断言 env 无 key pattern
- integration：sandbox 内 `printenv` tool call 不得含 sk-

### 验收标准
- [ ] `tests/sandbox/test_credential_isolation.py` CI 必过
- [ ] 文档 security.md

### 依赖
- #45 volume 隔离增强
""",
    36: """## 生产级实现方案 — SDK 嵌入模式

### Pi 参考
`packages/coding-agent/src/index.ts` 导出 `Agent`、`createAgentSession` 供 programmatic 使用。

### 下一步
**1. 包 `coderking-sdk`**
```python
from coderking_sdk import AgentSession

async with AgentSession(workspace=".", model="...") as session:
    async for event in session.run("fix tests"):
        ...
    await session.steer("also update README")
```

**2. 实现**
- 薄包装 L2 `CodingAgentSession`：组合 L1 Agent + default tools + SessionRepo
- 不启动 HTTP；in-process asyncio
- 线程安全：单 session 单 loop（document）

**3. 发布**
- PyPI `coderking-sdk`，semver 与 monorepo 同步

### 验收标准
- [ ] sdk 文档 + 3 examples（script/jupyter/FastAPI embed）
- [ ] sdk 单测不依赖 CLI subprocess

### 依赖
- #24 #27 #38
""",
    37: """## 生产级实现方案 — MCP 集成

### 规范
Anthropic MCP：JSON-RPC 2.0，Tools/Resources/Prompts 三原语。

### 下一步
**1. McpHost** (`coding_agent/mcp/host.py`)
- 配置 `.coderking/mcp.json` servers list
- 每 server 独立 subprocess（stdio transport）+ lifecycle supervise
- 启动：`initialize` → `tools/list` → merge schema 到 L1 tools（namespace `mcp_{server}_{tool}`）

**2. 路由**
- L1 tool call → `McpHost.call_tool(server, name, args)`
- timeout 60s，cancel  propagates

**3. 安全**
- MCP tools 默认 `ask` policy（#43）
- server allowlist

**4. 依赖库**
- 官方 Python MCP SDK（`mcp` package）而非自研 JSON-RPC

### 验收标准
- [ ] 集成 test：mock MCP server 返回 tool
- [ ] 真实 github MCP（optional live）read issue
- [ ] 文档 mcp-setup.md

### 依赖
- #24 L1 tool dispatch
- #43 policy for external tools
""",
    41: """## 生产级实现方案 — Agent 自扩展工具

### Pi 参考
四工具哲学：Agent 用 Bash 写脚本到 `.pi/tools/` 再执行，无需内置浏览器/DB 框架。

### 下一步
**1. 约定目录**
```
.coderking/tools/{name}/
  tool.yaml      # schema + entry script
  main.py|sh
```

**2. DynamicToolLoader**（L2 extension）
- session 启动扫描目录
- `beforeToolCall`：首次调用时 load schema 注册到 **当前 session** tools（不污染 global）
- 沙盒内执行，path 限制在 `.coderking/tools`

**3. 示例 bundled**
- `browser_smoke/` playwright 脚本生成器（agent 用 bash+write 创建，loader 注册）

**4. 安全**
- dynamic tools 强制 policy `ask`
- 禁止 `..` path escape

### 验收标准
- [ ] agent 自建 tool 并被第二次 turn 调用（e2e test）
- [ ] 恶意 tool.yaml 被拒绝

### 依赖
- #40 bash background 可选
- #43 policy
""",
    44: """## 生产级实现方案 — Micro-VM 沙盒

### 下一步（企业级，Phase 4+）
**1. Backend 抽象**
```python
class SandboxBackend(Protocol):
    async def exec(self, cmd: str) -> ExecResult: ...
    async def close(self) -> None: ...
```
新增 `FirecrackerBackend` / `CloudHypervisorBackend`

**2. 架构**
- Host：LLM + MCP + credentials
- Micro-VM：Bash/Edit/Write 仅访问 virtio-fs 挂载的 workspace snapshot
- vsock 通信 exec（参考 Firecracker containerd）

**3. 落地路径**
- 先集成 **E2B / Daytona API** 作为托管 Micro-VM（快速生产可用）
- 自托管 Firecracker 作为 Phase 4b

### 验收标准
- [ ] VM 内无法读取 host `/etc/passwd`
- [ ] 冷启动 < 5s（托管）或 < 500ms（snapshot，自托管）
- [ ] 与 Docker backend 可配置切换

### 依赖
- #45 CoW
- #47 凭据隔离
""",
    48: """## 生产级实现方案 — Interactive TUI

### Pi 参考
`packages/tui`：retained-mode differential render，不 flicker。

### 下一步
**1. 技术选型**
- Python：`textual` 或 port Pi TUI 思路的自研 diff renderer
- 要求：100ms 内 incremental update，支持 scrollback 10k lines

**2. 模块** (`transport/tui/`)
- `TuiApp` subscribe L1 events
- 面板：Chat / Tool trace / Diff / Status bar（model/tokens/phase）
- 输入：multiline editor + steer（Enter submit steer，Shift+Enter newline）

**3. CLI**
- `coderking tui` 替代 Rich Live 为默认 interactive

### 验收标准
- [ ] 256x80 terminal 无 full redraw flicker（vcr test）
- [ ] stream token 实时显示
- [ ] steer 快捷键

### 依赖
- #25 streaming
- #32 steer
""",
    49: """## 生产级实现方案 — Desktop IPC 全链路

### Pi 参考
Desktop spawn `pi rpc` / rpc-entry，stdio JSONL 双向。

### 下一步
**1. Electron 主进程**
```javascript
const child = spawn('coderking', ['rpc', '--workspace', dir]);
readline.createInterface({input: child.stdout}).on('line', forwardToRenderer);
ipcMain.handle('agent:prompt', (_, text) => rpc.call('agent.prompt', {text}));
```

**2. Preload 安全桥**
- contextBridge 暴露 `agent.prompt/steer/abort/onEvent`
- 禁止 renderer nodeIntegration

**3. UI**
- 复用 Web 组件或独立 React panel：Diff/Terminal/Plan
- 事件流与 #35 SSE 同 schema

**4. 打包**
- electron-builder 捆绑 Python runtime 或要求 PATH 有 coderking
- 代码签名（Win/macOS 发布）

### 验收标准
- [ ] Desktop 完成 eval bug_fix 全流程
- [ ] kill desktop 子进程 clean
- [ ] 无 shell injection in IPC args

### 依赖
- #34 RPC stdio
- #35 或 WS events
""",
}


def main() -> None:
    for num, body in sorted(COMMENTS.items()):
        header = (
            "## 实现路线图（生产级）\n\n> 设计参考 Pi：`https://github.com/earendil-works/pi`\n\n"
        )
        full = header + body
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".md", delete=False
        ) as f:
            f.write(full)
            path = f.name
        try:
            subprocess.run(
                [
                    "gh",
                    "issue",
                    "comment",
                    str(num),
                    "--repo",
                    REPO,
                    "--body-file",
                    path,
                ],
                check=True,
            )
            print(f"Commented on #{num}")
        finally:
            Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
