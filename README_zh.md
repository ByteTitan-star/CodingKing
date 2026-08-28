<h1 align="center">💻 CoderKing</h1>

<p align="center">
  <a href="https://github.com/ByteTitan-star/CodingKing/releases/tag/v1.0.6"><img src="https://img.shields.io/badge/CoderKing-v1.0.6-2563eb" alt="CoderKing v1.0.6" /></a>
  <img src="https://img.shields.io/badge/python-3.12-3776AB" alt="Python 3.12" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT" /></a>
  <a href="https://github.com/ByteTitan-star/CodingKing/actions/workflows/ci.yml?query=branch%3Amain"><img src="https://github.com/ByteTitan-star/CodingKing/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI" /></a>
  <a href="./README.md"><img src="https://img.shields.io/badge/English-0A66C2" alt="English" /></a>
  <img src="https://img.shields.io/badge/%E4%B8%AD%E6%96%87-555555" alt="Chinese" />
</p>

> 用自然语言描述工程任务 —�?自动规划、改代码、在沙箱里跑测试，失败则进入修复循环，直到验证通过。CLI �?Web 共用同一�?Agent Runtime�?

<p align="center">
  <a href="./docs/showcase/demo.html"><strong>打开工作�?Demo</strong></a>
  &nbsp;·&nbsp;
  <a href="./docs/CoderKing-Technical-Design.md"><strong>阅读技术方�?/strong></a>
</p>

## CoderKing 是什么？

CoderKing 是一个面向软件工程场景的自主 Coding Agent 运行时。你用自然语言描述任务，Agent 会规划步骤、修改仓库、在隔离沙箱中执行命令与测试；验证失败时自动进入 Repair 循环 —�?CLI �?Web 工作台调用的是同一�?Runtime，而不是两套重复逻辑�?

第一期是可运行的 MVP（Python Runtime + React 工作台单仓），不是多租户 SaaS�?

## Agent 工作�?

| 阶段 | 关键动作 | 阶段产出 |
| --- | --- | --- |
| 任务输入 | �?CLI �?Web 中描�?bug 修复、功能或重构需求�?| 清晰的工程任务说�?|
| 规划 | 将任务拆成可审查的步骤�?| 结构化任务计�?|
| 编码 | 在仓库中读取、搜索、编辑文件�?| 补丁后的源码 |
| 执行 | 在沙箱中运行 shell 与测试�?| 命令与测试输�?|
| 审查 | 对照计划�?diff 验证结果�?| 通过 / 失败判定 |
| 修复 | 测试失败时诊断并再次修改�?| 修正后的实现 |
| 交付 | 输出 diff 摘要；可选经批准�?git commit�?| 完成的任�?|

## 产品展示

### 修复循环实战

![CoderKing 工作�?�?bug 修复�?Repair 循环](docs/showcase/assets/product-workspace.png)

单测失败后，Agent 依次经过 Planner �?Coding �?Execution �?Repair。工作台在同一视图展示计划、工具调用、改动文件与 pytest 输出�?

### 统一 Diff

![CoderKing Diff 视图 �?修复后对比](docs/showcase/assets/product-diff.png)

在接受或回滚前精确查看改动内�?—�?�?Reviewer 角色用于验收的是同一�?diff�?

## 产品界面

| 工程工作�?| Diff 与运行时 |
| --- | --- |
| ![CoderKing 工程工作台](docs/showcase/assets/product-workspace.png) | ![CoderKing Diff 与运行时面板](docs/showcase/assets/product-diff.png) |
| 描述任务、查看计划与 Agent 活动、浏览改动文件�?| 并排查看统一 diff、终端输出与测试结果�?|

截图资源位于 [`docs/showcase/`](docs/showcase/)。可�?`python scripts/capture_showcase.py` 从静�?demo 页重拍，或在真实任务跑通后替换素材�?

## 核心能力

| 能力 | 说明 |
| --- | --- |
| 统一 Runtime | CLI �?Web 共用 Agent Runtime，避免重复编排�?|
| ReAct + Reflection | 自研 Agent 循环，不依赖 LangChain / LangGraph�?|
| 角色化工具权�?| Planner / Coding / Execution / Reviewer / Repair，各角色工具集隔离�?|
| 沙箱执行 | Docker 为主；无 Docker �?local 进程仅作开�?fallback，事件流会标明�?|
| 多模型兼�?| OpenAI Compatible 网关 —�?DeepSeek、GLM、Qwen、Ollama 等换 `base_url` 即可�?|
| 人机协同 | 删文件、危�?shell、`git commit` 等默认需确认；`--yes` 可自动批准�?|
| 评测体系 | `eval/tasks` 覆盖 `bug_fix`、`feature_add`、`refactor`�?|
| 可观�?| Web 展示计划、Tool Trace、终端输出、Diff �?Sandbox 状态�?|

<p align="center">
  <a href="./docs/showcase/demo.html"><strong>体验工作�?Demo</strong></a>
  &nbsp;·&nbsp;
  <a href="./docs/phase1-acceptance.md"><strong>第一期验收清�?/strong></a>
</p>

## 架构

```text
User �?CLI / Web UI �?FastAPI + WebSocket
                         �?
                   Agent Runtime
                         �?
              Planner �?Coding �?Execution �?Reviewer
                         �?Repair �?
                         �?
              Tools �?Sandbox �?Workspace
```

`coderking run` 默认进程内直接调�?Runtime，无需先起 HTTP 服务；`coderking serve` 将同一 Runtime 暴露�?Web�?

## 快速开�?

**环境要求�?* Python 3.12+，Node 22+（仅 Web），Docker 可选�?

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env
```

编辑 `.env`�?

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
coderking chat --workspace .
coderking status
coderking stop <task_id>
coderking eval --path eval/tasks --report-dir eval/reports
```

配置优先级：CLI 参数 > 环境变量 / `.env` > `.coderking/config.yaml` > 默认值。API Key 只走环境变量，勿写入 yaml 或提�?Git�?

### Web

```bash
coderking serve --port 8000
```

另开终端�?

```bash
cd web && npm install && npm run dev
```

浏览器打开 `http://127.0.0.1:5173`。生产环境执�?`npm run build` 后，FastAPI 会托�?`web/dist`�?

## 配置

| 变量 | 含义 |
| --- | --- |
| `CODERKING_OPENAI_BASE_URL` | OpenAI Compatible 网关 |
| `CODERKING_OPENAI_API_KEY` | API Key，勿提交�?Git |
| `CODERKING_MODEL` | 模型�?|
| `CODERKING_DISABLE_THINKING` | 关闭推理模型 thinking 字段（默�?true�?|
| `CODERKING_SANDBOX_MODE` | `auto` / `docker` / `local` |
| `CODERKING_ALLOW_COMMIT` | 是否允许 `git_commit` 工具 |

若上�?API 不支�?`thinking` 字段，客户端会自动去掉该字段并重试一次�?

## 开发与 CI

```bash
pre-commit install
pre-commit run --all-files
pytest -q -m "not docker"
ruff check src tests
cd web && npm run lint && npm run build
```

本机�?Docker 时再跑：`pytest tests/test_docker.py`�?

贡献约定�?[CONTRIBUTING.md](CONTRIBUTING.md)。CI 配置�?[`.github/workflows/ci.yml`](.github/workflows/ci.yml)（默�?job 跳过 Docker；另�?`docker-sandbox` job）�?

## 仓库布局

```text
src/coderking/     Python Runtime、CLI、API
web/               React + Vite 工作�?
eval/tasks/        评测场景
tests/             单测
docs/              设计文档、展示素材与验收清单
```

## 文档

- [技术方案](docs/CoderKing-Technical-Design.md)
- [Web UI �?CLI 设计](docs/CoderKing-WebUI-CLI-Design.md)
- [第一期验收](docs/phase1-acceptance.md)

## License

MIT © CodeTitan, 2026 �?详见 [LICENSE](LICENSE)�?
