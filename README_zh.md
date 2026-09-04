<h1 align="center">💻 CoderKing</h1>

<p align="center">
  <a href="https://github.com/ByteTitan-star/CodingKing/releases/tag/v1.0.9"><img src="https://img.shields.io/badge/CoderKing-v1.0.9-2563eb" alt="CoderKing v1.0.9" /></a>
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

### 修复循环实战

![CoderKing 工作台 — bug 修复与 Repair 循环](docs/showcase/assets/product-workspace.png)

单测失败后，Agent 走纯循环（改文件 → 跑测试 → 再修）。工作台在同一视图展示工具调用、改动文件与 pytest 输出。

### 统一 Diff

![CoderKing Diff 视图 — 修复后对比](docs/showcase/assets/product-diff.png)

在接受或回滚前精确查看改动内容。

## 产品界面

| 工程工作台 | Diff 与运行时 |
| --- | --- |
| ![CoderKing 工程工作台](docs/showcase/assets/product-workspace.png) | ![CoderKing Diff 与运行时面板](docs/showcase/assets/product-diff.png) |
| 描述任务、查看 Agent 活动、浏览改动文件。 | 并排查看统一 diff、终端输出与测试结果。 |

截图资源位于 [`docs/showcase/`](docs/showcase/)。可用 `python scripts/capture_showcase.py` 从静态 demo 页重拍，或在真实任务跑通后替换素材。

## 核心能力

| 能力 | 说明 |
| --- | --- |
| 统一 Runtime | CLI 与 Web 共用 Agent Runtime，避免重复编排。 |
| 纯 Agent 循环 | 对齐 Pi 的 ReAct 式循环；无 LangChain / LangGraph，无固定角色阶段。 |
| 四原子工具 | 仅 `read` / `write` / `edit` / `bash`，步骤顺序由模型决定。 |
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

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env
```

编辑 `.env`：

```env
CODERKING_OPENAI_BASE_URL=https://api.deepseek.com/v1
CODERKING_OPENAI_API_KEY=sk-...
CODERKING_MODEL=deepseek-chat
CODERKING_DISABLE_THINKING=true
CODERKING_SANDBOX_MODE=auto
```

### CLI

```bash
coderking init
coderking config model --base-url https://api.deepseek.com/v1 --model deepseek-chat
coderking run "修复当前仓库里失败的单元测试" --workspace .
coderking run "修复失败测试" --workspace . --test "python -m pytest -q"
coderking chat --workspace .
coderking status
coderking stop <task_id>
coderking eval --path eval/tasks --report-dir eval/reports
```

配置优先级：CLI 参数 > 环境变量 / `.env` > `.coderking/config.yaml` > 默认值。API Key 只走环境变量，勿写入 yaml 或提交 Git。

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

- [技术方案](docs/CoderKing-Technical-Design.md)
- [Web UI 与 CLI 设计](docs/CoderKing-WebUI-CLI-Design.md)
- [第一期验收](docs/phase1-acceptance.md)

## License

MIT © CodeTitan, 2026 — 详见 [LICENSE](LICENSE)。
