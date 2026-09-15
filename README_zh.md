<h1 align="center">💻 CoderKing</h1>

<p align="center">
  <a href="https://github.com/ByteTitan-star/CodingKing/releases/tag/v1.2.0"><img src="https://img.shields.io/badge/CoderKing-v1.2.0-2563eb" alt="CoderKing v1.2.0" /></a>
  <img src="https://img.shields.io/badge/python-3.12-3776AB" alt="Python 3.12" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT" /></a>
  <a href="https://github.com/ByteTitan-star/CodingKing/actions/workflows/ci.yml?query=branch%3Amain"><img src="https://github.com/ByteTitan-star/CodingKing/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI" /></a>
  <a href="./README.md"><img src="https://img.shields.io/badge/English-0A66C2" alt="English" /></a>
  <img src="https://img.shields.io/badge/%E4%B8%AD%E6%96%87-555555" alt="Chinese" />
</p>

> 用自然语言描述工程任务 —— Coding Agent 用 read/write/edit/bash 改代码，在沙箱里跑测试，失败则继续迭代直到验证通过。CLI 与 Web 共用同一套 Agent Runtime。

<p align="center">
  <a href="./docs/showcase/demo.html"><strong>打开工作台 Demo</strong></a>
  &nbsp;·&nbsp;
  <a href="./docs/CoderKing-Technical-Design.md"><strong>阅读技术方案</strong></a>
</p>

## CoderKing 是什么？

CoderKing 是面向软件工程的自主 **Coding Agent** 运行时（对齐 Pi）。你用自然语言描述任务；单一 Agent 循环使用四个工具（`read` / `write` / `edit` / `bash`）修改仓库、在隔离沙箱中跑检查，并持续迭代直到验证通过。CLI 与 Web 共用同一 Runtime —— **没有固定多角色 workflow**。

第一期是可运行的 MVP（Python Runtime + React 工作台单仓），不是多租户 SaaS。

## Agent 如何工作

| 步骤 | 发生什么 |
| --- | --- |
| 任务 | 在 CLI 或 Web 中描述 bug 修复、功能或重构。 |
| 循环 | 模型每轮自行选择工具（探索 → 修改 → 跑检查）。 |
| 验证 | 改完后用 `bash` 跑测试/lint（提示词引导；可选 `--test` 软提示）。 |
| 迭代 | 失败则根据工具输出诊断并再改。 |
| 交付 | 任务完成且验证通过后停止；人工审查 diff。 |

## 产品展示

以下截图来自 **v1.2.0 产品形态**——CLI 与 Web/Desktop 共用同一代理循环，任务为修复失败测试（`a - b` → `a + b`）。

### CLI（主形态）

![CodeKing CLI：横幅、任务执行、折叠工具轨迹、Markdown 回复](docs/showcase/assets/product-cli.png)

裸命令 `codeking` 直接进入 REPL：横幅 → 描述任务 → 代理自主探索、修改、验证（`⏺ 工具 ×5` 折叠摘要，`/trace` 展开）→ 回复按 Markdown 渲染 → 结果摘要。

### 桌面 / Web 工作台

![CoderKing 桌面工作台：会话侧栏、流式 Markdown 回复、计划卡片、子代理轨迹](docs/showcase/assets/product-workspace.png)

重设计后的对话优先工作台：可恢复的会话侧栏、流式 Markdown 回复、工作计划、可折叠的工具与子代理轨迹、内联 Diff 摘要，输入区带审批模式 / 模型 / 推理等级选择器；右侧面板跟踪文件、Diff、检查点与测试输出。

### 统一 Diff

![CoderKing Diff 视图 — 增删高亮与文件统计](docs/showcase/assets/product-diff.png)

逐行查看带增删高亮与 +/- 统计的改动；也可直接使用对话内的内联摘要一键撤销，再决定采纳或回滚。

## 产品界面

| CLI | 桌面 / Web 工作台 | Diff 与运行时 |
| --- | --- | --- |
| ![CodeKing CLI REPL](docs/showcase/assets/product-cli.png) | ![CoderKing 工程工作台](docs/showcase/assets/product-workspace.png) | ![CoderKing Diff 与运行时面板](docs/showcase/assets/product-diff.png) |
| 流式 REPL + 会话管理 + 斜杠命令补全。 | 描述任务、查看编排式代理工作、浏览改动文件。 | 并排查看统一 diff、检查点与测试结果。 |

截图资源位于 [`docs/showcase/`](docs/showcase/)；桌面截图渲染自 v1.2.0 UI。

## 核心能力

| 能力 | 说明 |
| --- | --- |
| 统一 Runtime | CLI 与 Web 共用 Agent Runtime，避免重复编排。 |
| 纯 Agent 循环 | 对齐 Pi 的 ReAct 式循环；无 LangChain / LangGraph，无固定角色阶段。 |
| 四原子工具 | 仅 `read` / `write` / `edit` / `bash`，步骤顺序由模型决定。 |
| 子代理与动态工作流 | 可选 `agent` + `plan` 工具：委派只读 `explore` 或 `general-purpose` 子代理，同轮委派并行执行（`dynamic_workflow` 门控，默认关闭）。 |
| 推理等级 | `off` / `low` / `medium` / `high` / `ultra` 运行时可切，后端不支持时自动降级。 |
| 持久化任务 | 会话树支持分支/恢复、重试索引、文件检查点可逐点回滚。 |
| 提示词验收 | 改完用 bash 跑检查；可选 `--test` 软提示（非硬门禁）。 |
| 沙箱执行 | Docker 为主；无 Docker 时 local 进程仅作开发 fallback，事件流会标明。 |
| 多模型兼容 | OpenAI Compatible 网关 —— DeepSeek、GLM、Qwen、Ollama 等换 `base_url` 即可。 |
| 人机协同 | 危险操作默认需确认；`--yes` 可自动批准。 |
| 评测体系 | `eval/tasks` 覆盖 `bug_fix`、`feature_add`、`refactor`。 |
| 可观测 | Web 展示 Tool Trace、终端输出、Diff 与 Sandbox 状态。 |

<p align="center">
  <a href="./docs/showcase/demo.html"><strong>体验工作台 Demo</strong></a>
  &nbsp;·&nbsp;
  <a href="./docs/phase1-acceptance.md"><strong>第一期验收清单</strong></a>
</p>

## 架构

```text
User → CLI / Web UI → FastAPI + WebSocket
                         ↓
                   Agent Runtime
                         ↓
              L1 纯 Loop：Perceive → Decide → Act → Observe
                         ↓
              Tools（read/write/edit/bash）→ Sandbox → Workspace
```

`coderking run` 默认进程内直接调用 Runtime，无需先起 HTTP 服务；`coderking serve` 将同一 Runtime 暴露给 Web。

## 快速开始

**环境要求：** Python 3.12+，Node 22+（仅 Web），Docker 可选。

> 📖 新手上路？先看 **[CLI 使用指南](docs/cli/README.md)** —— 覆盖全部命令的完整教程（含示例与常见问题）。

### 安装（三选一）

```bash
# 一行脚本，无需任何账号
curl -fsSL https://raw.githubusercontent.com/ByteTitan-star/CodingKing/main/install.sh | sh

# npm
npm install -g codeking

# 源码安装
python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
```

三种方式都会装出全局 `codeking` 命令。模型配置写在 `~/.coderking/.env`（全局）或 `<项目>/.env`（项目覆盖），任意 OpenAI 兼容接口均可：

```env
CODERKING_OPENAI_BASE_URL=https://api.deepseek.com   # 或 open.bigmodel.cn/api/paas/v4 等
CODERKING_OPENAI_API_KEY=sk-...
CODERKING_MODEL=deepseek-chat
```

### CLI

```bash
codeking                    # 裸命令直接进交互会话（入场动画 + 流式回复）
codeking new                # 开一条新会话（旧的保留）
codeking -r                 # 交互式选择历史会话恢复（claude 同款）
codeking sessions           # 会话列表：ID / 任务 / tokens / 消息数
codeking session tree       # 查看当前会话的追加式节点树
codeking session fork --from <id> --name <new-id>
codeking run "修复失败的单元测试" -w .    # 一次性任务
codeking status && codeking diff && codeking test
codeking tasks --status failed && codeking retry <task-id>
codeking checkpoint list <task-id>
codeking checkpoint rollback <checkpoint-id> --task <task-id> --yes
codeking skills list
codeking run --skill code-review "审查当前改动"
codeking tools check && codeking run --dynamic-tools "调用项目自定义工具"
codeking mcp check && codeking run --mcp "调用 allowlisted MCP 工具"
codeking eval --path eval/tasks --report-dir eval/reports
```

会话内：`/new` 新会话 · `/trace` 展开折叠的工具轨迹 · `/skills` 查看技能 ·
`/context`/`/compact` 管理长上下文 · `/reload` 重扫资源 · `/exit` 退出；斜杠命令带描述自动补全；模型回复逐 token 流式输出并按 Markdown 渲染，工具过程折叠为一行摘要。

任务 JSON 与追加式会话 JSONL 仍是可移植事实源；`.coderking/state.db` 是可重建的
SQLite 状态索引，用于查询、事件游标和执行租约。直接文件写工具在变更前还会把二进制安全
checkpoint 写入 `.coderking/checkpoints/`。

配置优先级：shell 环境变量 > 项目 `.env` > `~/.coderking/.env` > `.coderking/config.yaml` > 默认值。API Key 只走环境变量，勿写入 yaml 或提交 Git。

### Web

```bash
coderking serve --port 8000
```

另开终端：

```bash
cd web && npm install && npm run dev
```

浏览器打开 `http://127.0.0.1:5173`。生产环境执行 `npm run build` 后，FastAPI 会托管 `web/dist`。

## 配置

| 变量 | 含义 |
| --- | --- |
| `CODERKING_OPENAI_BASE_URL` | OpenAI Compatible 网关 |
| `CODERKING_OPENAI_API_KEY` | API Key，勿提交进 Git |
| `CODERKING_MODEL` | 模型名 |
| `CODERKING_DISABLE_THINKING` | 关闭推理模型 thinking 字段（默认 true） |
| `CODERKING_SANDBOX_MODE` | `auto` / `docker` / `local` |
| `CODERKING_ALLOW_COMMIT` | 是否允许 `git_commit` 工具 |
| `CODERKING_CONTEXT_WINDOW` | 当前模型上下文窗口（默认 128000） |
| `CODERKING_COMPRESSION_ENABLED` | 是否自动压缩长会话（默认 true） |
| `CODERKING_COMPRESSION_THRESHOLD` | 触发压缩的窗口比例（默认 0.75） |
| `CODERKING_COMPRESSION_RESERVE_TOKENS` | 为模型回复预留的 token（默认 4096） |
| `CODERKING_COMPRESSION_KEEP_RECENT_MESSAGES` | 压缩时至少保留的最近消息数（默认 20） |
| `CODERKING_MICRO_COMPACTION_ENABLED` | 完整压缩前先收缩旧的大型工具输出（默认 true） |
| `CODERKING_MICRO_COMPACTION_THRESHOLD` | 微压缩相对完整压缩预算的触发比例（默认 0.5） |
| `CODERKING_MICRO_COMPACTION_KEEP_RECENT_TOOL_RESULTS` | 不参与微压缩的最近工具结果数（默认 4） |
| `CODERKING_MICRO_COMPACTION_MIN_OUTPUT_CHARS` | 可微压缩工具输出的最小字符数（默认 2000） |
| `CODERKING_DYNAMIC_TOOLS_ENABLED` | 显式启用项目动态工具（默认 false） |
| `CODERKING_MCP_ENABLED` | 显式启用 allowlisted MCP 工具（默认 false） |
| `CODERKING_MCP_TIMEOUT_SEC` | MCP 初始化/调用超时（默认 60 秒） |

若上游 API 不支持 `thinking` 字段，客户端会自动去掉该字段并重试一次。

## 开发与 CI

```bash
pre-commit install
pre-commit run --all-files
pytest -q -m "not docker"
ruff check src tests
cd web && npm run lint && npm run build
```

本机有 Docker 时再跑：`pytest tests/test_docker.py`。

贡献约定见 [CONTRIBUTING.md](CONTRIBUTING.md)。CI 配置见 [`.github/workflows/ci.yml`](.github/workflows/ci.yml)（默认 job 跳过 Docker；另有 `docker-sandbox` job）。

## 仓库布局

```text
src/coderking/     Python Runtime、CLI、API
web/               React + Vite 工作台
eval/tasks/        评测场景
tests/             单测
docs/              设计文档、展示素材与验收清单
```

## 文档

- [能力审计与实现路线图](docs/CoderKing-Implementation-Roadmap.md)
- [技术方案](docs/CoderKing-Technical-Design.md)
- [Web UI 与 CLI 设计](docs/CoderKing-WebUI-CLI-Design.md)
- [第一期验收](docs/phase1-acceptance.md)

## License

MIT © CodeTitan, 2026 — 详见 [LICENSE](LICENSE)。
