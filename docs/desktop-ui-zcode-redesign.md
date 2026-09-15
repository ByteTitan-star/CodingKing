# Desktop UI 重设计 — 系统参考 ZCode 交互模式

日期：2026-09-15（B1+ 批次更新同日）
状态：已评审，B1 与 B1+（桌面端对齐）已落地，见 §6/§8

## 1. 文档目标

对 Desktop（Electron + `web/` React UI）做一次以 **ZCode**（终端编码代理，本项目的交互标杆）为参照系的系统性重设计：

- 布局（信息架构、三栏结构、折叠行为）
- 按钮（主/次/幽灵层级、状态化动作、键盘等价物）
- 具体功能（会话恢复、流式输出、工具轨迹、审批、重试、检查点）

范围：`web/src/*`、`desktop/main.mjs`、`desktop/preload.cjs`、`src/coderking/rpc.py`（仅补 `session.list`）。

---

## 2. 现状问题审计

### 2.1 真实使用断点（P0 — 影响基本可用性）

| # | 问题 | 证据 |
|---|------|------|
| 1 | **无流式输出**。后端 `content_delta` 事件已存在（token streaming，CLI 已用），UI 完全未消费；用户在整个任务期间看不到模型在想什么 | `App.tsx` 的 `replies` 只取 `done`/`error` |
| 2 | **回复截断 800 字符且无 Markdown**。`{text.slice(0, 800)}` 直接进 div；CLI 专门修过 markdown 渲染（`fix/markdown-reply-rendering`），desktop 未跟进 | `App.tsx:498` |
| 3 | **跟进消息发送后从对话中消失**。`steer`/`follow_up` 事件既不进 `replies` 也不进 `toolTrace`，用户输入完没有任何回显，像丢进了黑洞 | `App.tsx:145-156` |
| 4 | **工具轨迹不可折叠**。长任务几百行 `tool-line` 平铺，把对话挤没；参数 `JSON.stringify` 截断 90 字符，preview 截断 70 字符 | `App.tsx:446-476` |
| 5 | **审批卡片信息不足**。`JSON.stringify(arguments).slice(0, 160)` — 一条 shell 命令被拦腰截断，用户在批准一个看不全的东西 | `App.tsx:482` |
| 6 | **失败后没有重试入口**。RPC/HTTP 都有 `agent.retry`，desktop IPC 未暴露，UI 无按钮 | `desktop/main.mjs` handler 清单 |
| 7 | **Enter 不能发送**。textarea 内 Enter 只换行，无 Cmd/Ctrl+Enter 绑定、无任何键盘提示，鼠标是唯一路径 | composer 无 onKeyDown |

### 2.2 功能缺口（P1 — ZCode 有而 desktop 缺）

| # | 缺口 | ZCode 对应做法 | 后端能力 |
|---|------|---------------|----------|
| 8 | 无会话历史/恢复 | session listing、resume picker、新会话命令 | `registry.list_sessions` 存在但 RPC 未暴露 |
| 9 | 计划（todo）不显示 | TodoList 渲染为工作计划，实时勾选 | `plan_update` 事件 + `task.plan` 均在，UI 未渲染 |
| 10 | context/token 状态不可见 | 状态面板显示 compaction 事件与 token 用量 | `context_compressed`、`context_micro_compacted`、`task.context` 均在 |
| 11 | 检查点不可见不可回滚 | （CLI 对应 durable checkpoints 分支方向） | `agent.checkpoints`、`agent.rollback_checkpoint` 已在 RPC |
| 12 | 单任务模型 | 后台任务 + 完成通知 | controller 支持多 task |

### 2.3 设计与打磨（P2）

| # | 问题 |
|---|------|
| 13 | 文件列表是平铺 `string[]`，大仓库不可用；无树形/分组 |
| 14 | "终端" tab 实际是 terminal+test 事件拼接，命名误导 |
| 15 | 无深色模式（`prefers-color-scheme` 未处理） |
| 16 | `agent_status` 事件混入工具轨迹，role 显示在 tool 列里语义错位 |
| 17 | empty state 默认仓库 `.`，指向 Electron 进程 cwd，易在错误目录跑任务；不记忆上次工作区 |
| 18 | Diff 无文件级过滤与统计 |

---

## 3. ZCode 交互模式解析（参照基准）

ZCode 是终端编码代理，其交互经 CLI 打磨，核心模式如下，逐条映射到 desktop：

| ZCode 模式 | 终端形态 | Desktop 映射 |
|-----------|---------|--------------|
| **对话优先** | 主视图是流式对话，token 逐字流出 | 中央对话列，`content_delta` 实时渲染为正在生成的 Markdown 气泡 |
| **工具轨迹折叠** | 默认一行摘要，`/trace` 展开；回复宽度封顶 | 工具调用聚合成可折叠分组（默认折叠），头部显示 "工具调用 · N"，逐条可展开参数与结果 |
| **工作计划** | TodoList 渲染为清单，in_progress 高亮 | `plan_update` → 对话内的计划卡片：☐/◐/☑ 三态，当前项高亮 |
| **结构化审批** | AskUserQuestion：header/label/description/preview，选项而非自由文本 | 审批卡片完整展示工具+参数（不截断），允许/拒绝为主次按钮；参数按 k=v 分行 |
| **turn-based steering** | 运行中可发消息改变方向，非阻塞 | composer 常驻；running 时 placeholder/按钮语义切换为"转向"，否则"跟进" |
| **会话恢复** | `--resume` picker、sessions 列表 | 左侧会话侧栏：历史会话（时间/首句/token），点击恢复，"+ 新会话"置顶 |
| **状态面板** | compaction 事件、token 用量、任务状态 surfaced | header 右侧：context 用量微条 + 压缩事件以状态行进入对话流 |
| **键盘驱动** | 全键盘操作 | Cmd/Ctrl+Enter 发送、Esc 中断运行中任务、`⌘N` 新会话 |
| **失败恢复** | 重试友好 | 失败横幅带"重试"按钮 → `agent.retry`（自动接续 session） |
| **回复宽度约束** | 100 cols 封顶 | 对话列 `max-w-3xl` 居中，长行不撑破 |

**设计原则提炼**（从 ZCode 迁移）：

1. **流式优先**：一切让用户等待的地方都要有增量反馈。
2. **噪音折叠**：过程细节默认收起，结构化摘要常显，细节一键展开。
3. **动作贴近上下文**：重试放失败横幅、回滚放检查点旁、审批放轨迹发生处。
4. **状态常显**：任务状态、token、context 健康度永远可见，不需要切换 tab。
5. **键盘是一等公民**：高频动作都有快捷键并在 UI 上标注。

---

## 4. 新信息架构（布局）

```
┌────────────────────────────────────────────────────────────────────────┐
│ header: [logo CoderKing] [状态 pill] [模型] …… [context 微条] [⌘N 新会话] │
├──────────┬──────────────────────────────────────────┬──────────────────┤
│ 会话侧栏   │  对话列（max-w-3xl 居中，流式）              │ 工作区面板（可折叠） │
│          │  ┌ 用户消息（含跟进/转向，右对齐标头）           │ ┌Tab: 文件│Diff│检查点┐│
│ + 新会话  │  ├ 计划卡片（☐ ◐ ☑ 实时勾选）                │ │                  ││
│ ──────── │  ├ ▸ 工具调用 · 7（折叠，展开见参数/结果）      │ │ 文件: 分组树+改动标记││
│ 会话 A ▣  │  ├ ▸ 工具调用 · 3                            │ │ Diff: 文件过滤+统计 ││
│ 会话 B    │  ├ 审批卡片（完整参数，允许/拒绝）              │ │ 检查点: 列表+回滚   ││
│ 会话 C    │  ├ CoderKing 流式回复（Markdown，不截断）      │ └──────────────────┘│
│          │  ├ 失败横幅（错误详情 + [重试]）                │                    │
│ 工作区:   │  └ 完成摘要（测试/tokens/文件数 + 采纳/回滚）    │                    │
│ /path/…  │ ┌──────────────────────────────────────────┐ │                    │
│          │ │ composer（自动增高，⌘⏎ 发送 / 运行中→转向）    │ │                    │
│          │ └──────────────────────────────────────────┘ │                    │
└──────────┴──────────────────────────────────────────┴──────────────────┘
```

- **侧栏 220px**：可折叠；empty state 时合并进 hero（避免三栏空荡）。
- **工作区面板 minmax(400px, 38%)**：任务开始自动展开；无任务时隐藏 — 延续"Chat 优先 + 按需工作区"的既定产品决策。
- **对话列**：唯一滚动容器，`max-w-3xl`。

## 5. 组件与按钮规格

### 5.1 按钮层级（沿用现有 .btn 体系，补状态语义）

| 按钮 | 样式 | 出现位置 | 快捷键 |
|------|------|---------|--------|
| 运行任务 / 发送 / 转向 | `btn-primary` | empty state 表单 / composer | ⌘⏎ |
| 允许 | `btn-primary` | 审批卡片 | ⌘⏎（审批态时 composer 上方） |
| 拒绝 | `btn-secondary` | 审批卡片 | Esc |
| 停止 | `btn-secondary`（含 IconStop） | composer 右侧，仅 running | Esc |
| 重试 | `btn-primary` | 失败横幅 | — |
| 采纳 / 回滚 | `btn-primary` / `btn-secondary` | 完成摘要卡 | — |
| 回滚到此 | `btn-secondary sm` | 检查点行 | — |
| + 新会话 | `btn-ghost` + 快捷键提示 | 侧栏顶部 | ⌘N |
| 浏览… | `btn-ghost` | empty state 仓库行 | — |

### 5.2 新组件

- `Markdown`：零依赖渲染器（标题/粗斜/行内码/围栏代码/列表/链接），围栏代码复用 `.code-block`。
- `ToolGroup`：折叠分组。头部 `▸ 工具调用 · N`；展开后每条含工具名、参数（k=v 分行、超长折叠全文可展开）、状态点（ok/error）。
- `PlanCard`：三态清单（pending ○ / in_progress ◐ 高亮 / done ☑），数据源 `plan_update` 事件与 `task.plan`。
- `ApprovalCard`：完整参数渲染（禁止截断），主次动作。
- `StatusLine`：进入对话流的系统事件（压缩、沙箱、恢复），弱化灰字 — 对应 ZCode 状态面板事件。
- `ContextMeter`：header 上的 token 估算微条 + `compression_count` 徽标，悬停出明细。

### 5.3 键盘

| 键 | 动作 |
|----|------|
| ⌘/Ctrl+Enter | 发送 / 允许（审批态） |
| Esc | 停止运行中任务 / 拒绝（审批态） |
| ⌘/Ctrl+N | 新会话（清空回到 empty state） |

## 6. 实施批次

| 批次 | 内容 | 状态 |
|------|------|------|
| B1 | 流式输出、Markdown 渲染、折叠工具轨迹、计划卡片、审批卡片完整化、跟进消息回显、失败横幅+重试、⌘⏎/Esc、会话侧栏（RPC 补 `session.list`，IPC 补 `listSessions`/`retryTask`）、检查点 tab、context 微条、工作区记忆（localStorage）、done 事件状态重查（修竞态） | ✅ 已落地 |
| B1+ | ZCode 桌面端对齐（见 §8）：会话标题栏、运行时长条（可折叠工作轨迹）、内联 Diff 摘要条（统计+撤销）、输入区工具行（权限选择器/模型选择器/推理等级选择器/圆形发送）、会话列表增强（相对时间/进行中蓝点/今天-更早分组/⌘K 搜索）、工具中文名、`config.get`/`config.set`（模型 + 推理等级切换）、`session.list` running 标记、工作区自动回填、完成/失败横幅按钮缩小并支持换行（修窄窗溢出） | ✅ 已落地 |
| B2 | 文件树分组、Diff 文件过滤与统计、深色模式、附件上传、模型列表接口（替代前端预设） | 待办 |
| B3 | 多任务并发（侧栏任务 tab）、完成通知（Electron Notification）、按项目分组的多工作区（需多 bridge 架构）、内嵌浏览器预览面板 | 待办 |

## 7. 兼容性约束

- HTTP 模式（`coderking serve` + 浏览器）继续可用：重试走 REST（`/api/tasks/{id}/retry` 已有）；会话侧栏与模型选择器为 RPC 专属，HTTP 下优雅降级隐藏。
- web 保持零运行时依赖（react/react-dom 之外不新增），Markdown 渲染器自实现。
- `desktop/rpc-bridge.test.mjs`（node --test）必须保持绿。
- `web/__visual.html` 是开发专用视觉验收 harness（mock 桥接 + 脚本化事件流，自动发现 dist bundle），`cd web && python3 -m http.server 8787` 后访问 `http://localhost:8787/__visual.html` 使用；不参与构建产物。

## 8. ZCode 桌面端对比（2026-09-15 实机截图）

参照 ZCode 桌面客户端（三栏：任务侧栏 / 对话列 / 内嵌浏览器预览）逐项对齐：

| ZCode 桌面端元素 | 对齐情况 |
|------------------|---------|
| 侧栏：相对时间（"刚刚"/"27分"/"2天"） | ✅ `relTime()` |
| 侧栏：进行中任务蓝点 | ✅ `session.list` 返回 running 标记 |
| 侧栏：搜索 ⌘K | ✅ 会话过滤输入（⌘K 唤起，Esc 关闭） |
| 侧栏：按项目分组 | ⏸ 架构限制（单 bridge 单工作区），先以"今天/更早"时间分组替代，多工作区列 B3 |
| 对话：会话标题 + 项目面包屑 | ✅ conv-header；空仓库输入时任务启动后从 `config.get` 回填实际路径 |
| 对话："已工作 X 分 X 秒 ›" 可折叠 | ✅ work-summary 条（运行中每秒跳动，点击折叠全部工具轨迹与状态行） |
| 对话：内联 Diff 摘要（N 个文件 + +/- 统计 + 撤销） | ✅ diff-inline 条，前端从 diff 文本统计 |
| 对话：工具行 = 图标 + 中文名 + 参数摘要 | ✅ TOOL_META 中文名映射（终端/读文件/写文件/编辑/搜索/Git） |
| 输入区：权限模式选择器（🛡 完全访问 ▾） | ✅ 每次审批/自动批准 → `agent.prompt(auto_approve)` |
| 输入区：模型选择器 | ✅ `config.get`/`config.set`（对后续任务生效）；预设列表暂在前端，B2 改接口下发 |
| 输入区：推理等级选择器（🧠 最高 ▾） | ✅ 端到端贯通：`Settings.reasoning_effort`（off/low/medium/high/ultra，env `CODERKING_REASONING_EFFORT`）→ L0 `OpenAICompatConfig.reasoning_effort` → payload `reasoning_effort` + `thinking:{type:enabled}`；`off` 走原 `disabled` 路径；显式等级优先于旧 `disable_thinking` 标志；后端 400 时自动摘除推理参数重试一次。UI 为 🧠 选择器（关闭/低/中/高/最高） |
| 输入区：+ 附件 | ⏸ B2 |
| 输入区：黑色圆形 ↑ 发送 | ✅ send-round |
| 右栏：内嵌浏览器预览面板 | ⏸ B3（对应 web 预览/截图能力） |
