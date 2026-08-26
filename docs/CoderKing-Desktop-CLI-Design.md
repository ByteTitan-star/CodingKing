# CoderKing Desktop & CLI Design Document

日期：2026-08-25

## 1. 文档目标

本文档定义 CoderKing **主交互产品**形态，覆盖：

- Desktop App（Electron + React）交互与信息架构
- CLI 交互（保持不变）
- 与 FastAPI / WebSocket Runtime 的统一接入
- Agent 执行过程可视化（Chat 优先 + 按需工作区）

**本文档覆盖并取代**原「三栏 Web IDE Workspace」设计。`web/` 目录可保留作浏览器调试兼容层，**不再作为产品主形态**。

核心原则：

> Coding Agent 不是普通聊天机器人，也不是传统 IDE 仪表盘。  
> 主体验应接近 ChatGPT Desktop / DeepSeek 桌面端：对话优先；Diff、Terminal、Test 在任务进行时按需展开。

------------------------------------------------------------------------

# 2. 已确认的产品决策

| 决策项 | 选择 |
| --- | --- |
| 壳 | Electron + 现有 React（Vite + Tailwind） |
| 布局 | 混合 C：默认极简聊天；任务运行时自动展开右侧工作区 |
| 后端启动 | 开发：连接本机 `coderking serve`；发布安装包再内嵌 Runtime（二期） |
| 旧 Web 三栏 UI | 文档层面废弃；代码可暂留，与 Desktop 冲突时以 Desktop 为准 |
| Agent Runtime | 不重写；复用现有 Planner → Coding → Execution → Reviewer → Repair |

------------------------------------------------------------------------

# 3. 产品交互目标

用户输入自然语言任务，例如：

```text
实现 FastAPI 用户认证系统
```

Agent 自动完成：需求理解 → 仓库分析 → 规划 → 改代码 → 沙箱执行 → 测试 → 修复 → 交付。

用户在 Desktop 中需要看到：

- 会话式对话流（需求、阶段、摘要）
- 当前角色与状态（Planner / Coding / …）
- Task Plan
- Tool Trace（可折叠气泡或侧栏）
- 修改文件列表与 Task-level Diff（+/-）
- Terminal / Test 输出
- Stop / HITL Approve / Accept / Rollback

------------------------------------------------------------------------

# 4. Desktop 总体设计

## 4.1 窗口布局

```text
+----------+---------------------------+------------------+
| Sessions |      Main Chat            | Workspace Panel  |
|          |                           | (collapsible)    |
| New Chat |  messages / plan chips    | Diff             |
| history  |  tool trace cards         | Terminal / Test  |
|          |                           | Files / Status   |
|          |  composer: repo + prompt  |                  |
+----------+---------------------------+------------------+
| Toolbar: Model · Status · Role · Stop · HITL · Accept   |
+---------------------------------------------------------+
```

### 状态行为

| 状态 | Sessions | Chat | Workspace |
| --- | --- | --- | --- |
| 空闲 / 无任务 | 可见 | 占满主区 | **收起** |
| 任务 running | 可见 | 主区 | **自动展开** |
| 有 Diff / 测试结果 | 可见 | 主区 | 保持展开（可手动关） |
| 已中断 / 已完成 | 可见 | 主区 | 保持展开直到用户收起 |

空闲时视觉目标：像 ChatGPT Desktop——大对话区 + 底栏输入，而不是三栏工程后台。

## 4.2 视觉方向（约束）

- 深色桌面客户端气质；避免「后台管理系统」卡片堆叠
- 品牌名 **CoderKing** 在标题栏 / 左上角可读，不压过对话
- 主 CTA：发送 / 新建任务；Stop 次级但始终可达
- Diff：等宽字体，`+` / `-` 着色
- 不在首屏堆统计条、多枚 pills、仪表盘 KPI

## 4.3 与 ChatGPT Desktop 的对应关系

| ChatGPT Desktop | CoderKing Desktop |
| --- | --- |
| 左侧会话 | 本地 task / session 列表 |
| 中间消息流 | 用户消息 + Agent 状态/摘要 + Plan + 折叠 Trace |
| 底栏输入 | 仓库路径 + 测试命令 + 任务描述 + 发送 |
| （无） | 右侧工程工作区：Diff / Terminal / Test |

------------------------------------------------------------------------

# 5. 模块设计

## 5.1 Sessions（左栏）

- 「新对话」创建空会话
- 列表项：截断 prompt、status、相对时间
- 点击切换；切换时重连对应 task WebSocket 或拉取快照
- 第一期可仅内存 / 本地 `.coderking` 已有 task 状态，不做云同步

## 5.2 Chat（中栏）

消息类型（渲染，非新协议）：

- `user`：用户任务文本
- `status`：角色切换（planner → coding → …）
- `plan`：计划条目与完成勾选
- `tool`：工具名 + 简短 preview（默认可折叠）
- `test`：测试摘要
- `done` / `error`：终态摘要

Composer：

- 仓库路径（可调系统目录选择：Electron `dialog.showOpenDialog`）
- 测试命令（默认 `python -m pytest -q`）
- 自动批准危险操作
- 发送 → `POST /api/tasks`

工具条：

- Stop → `POST /api/tasks/{id}/interrupt`
- Approve / Reject（HITL）
- Accept Changes / Rollback Changes

## 5.3 Workspace Panel（右栏）

Tab 或分段：

1. **Diff** — `GET /api/tasks/{id}/diff`，+/- 着色
2. **Terminal** — `terminal` / `test_result` 事件流
3. **Test** — `state.test_results` 摘要 + 原文
4. **Files** — 树 + 预览（复用现有 tree/file API）
5. **Runtime** — model、iteration、tokens、sandbox

## 5.4 Electron Shell

```text
desktop/
  package.json          # electron + electron-builder（二期可加深）
  main.js / main.ts     # BrowserWindow、可选 spawn serve（二期）
  preload.js            # 安全暴露 openDirectory 等
web/                    # React UI（Desktop 与浏览器调试共用源码）
```

开发模式：

1. `coderking serve --port 8000`
2. `cd web && npm run dev`
3. `cd desktop && npm run dev` → 加载 `http://localhost:5188`

生产（本阶段目标）：

- `web` build 后由 Electron `loadFile(dist/index.html)` 或 `loadURL`
- API 仍指向本机 `127.0.0.1:8000`（需用户或脚本先起 serve）
- **内嵌 Python Runtime 打包** 明确列为二期，不在本设计 P0

------------------------------------------------------------------------

# 6. API / 事件（不变，仅消费方式变）

Desktop 与旧 Web 共用：

| 能力 | 接口 |
| --- | --- |
| 健康检查 | `GET /api/health` |
| 创建任务 | `POST /api/tasks` |
| 任务快照 | `GET /api/tasks/{id}` |
| Diff | `GET /api/tasks/{id}/diff` |
| 文件树 / 内容 | `GET .../tree`、`GET .../file` |
| Stop | `POST .../interrupt` |
| HITL | `POST .../approve`、`.../reject` |
| Accept / Rollback | `POST .../accept`、`.../rollback` |
| 实时事件 | `WS /ws/tasks/{id}` |

事件类型：`agent_status`、`tool_call`、`plan_update`、`terminal`、`test_result`、`file_change`、`token_usage`、`approval_required`、`done`、`error`。

不新增业务协议；若 Desktop 需要「会话列表持久化」，优先读 `.coderking` 已有状态或本地轻量 JSON，避免先上 PostgreSQL。

------------------------------------------------------------------------

# 7. CLI（保持）

```bash
coderking init
coderking run "..." --workspace .
coderking chat --workspace .
coderking status
coderking stop <task_id>
coderking serve --port 8000
coderking eval --path eval/tasks
```

CLI **进程内**调 Runtime；Desktop / 浏览器调试走 `serve`。统一 Runtime，不统一进程模型。

------------------------------------------------------------------------

# 8. P0 / P1 范围

## P0（本阶段必须）

- [x] Electron 窗口加载 React UI（`desktop/`）
- [x] ChatGPT 式布局（左会话 + 中聊天 + 右可折叠工作区）
- [x] 任务运行时自动展开工作区
- [x] 复用现有 API/WS（`apiBase.ts` + preload `apiBase`）
- [x] 仓库目录选择（Electron dialog）
- [ ] Desktop 浏览器级 E2E / 安装包验收（待你本机点通）
- [x] README / 设计文档以 Desktop 为主路径

## P1（不做或延后）

- 安装包内嵌 Python / 自动 spawn `serve`
- 多窗口、账号体系、云同步
- 完整重做设计系统 / 动画大片
- 删除 `web/` 目录（可留兼容）
- Chroma / Milvus / PostgreSQL / Redis / Daytona

------------------------------------------------------------------------

# 9. 验收标准（Desktop）

在真实模型 + `coderking serve` 下：

1. 打开 Desktop，空闲态为聊天主界面（右侧收起）
2. 发送 Coding Task 后出现 Plan / Trace，右侧自动展开
3. Diff 显示 +/-，Test/Terminal 有输出
4. Stop 后状态为已中断，且不再继续写文件
5. 浏览器打开旧 `web` 调试页可不保证视觉一致，但 API 仍可用

证据写入 `docs/` 或 `eval/reports/` 的 Desktop 验收小节（另开，不回滚 Phase 1 CLI 验收结论）。

------------------------------------------------------------------------

# 10. 仓库布局（目标）

```text
src/coderking/     Runtime、CLI、API
web/               React UI（Desktop 与浏览器共用）
desktop/           Electron shell
eval/              评测
docs/              设计与验收（本文档为主交互说明）
```

------------------------------------------------------------------------

# 11. 明确不做什么

- 不把产品重新做成 SaaS 多租户
- 不重写 Agent Loop / Tool Protocol
- 不做「为了好看」的无交互装饰仪表盘
- 第一期 Desktop 不要求单文件离线安装包内嵌模型或 Python

------------------------------------------------------------------------

# 12. 与历史文档关系

| 文档 | 状态 |
| --- | --- |
| 本文档（原 WebUI-CLI，现 Desktop-CLI） | **现行主交互设计** |
| `CoderKing-Technical-Design.md` | Runtime 仍有效；交互层改为 CLI + Desktop |
| `phase1-acceptance.md` | Phase 1（CLI + 可用 Web E2E）结论保留；Desktop 为后续 UI 升级验收 |

原三栏 Web Workspace 线框与 P0「仅浏览器工作台」表述 **作废**。
