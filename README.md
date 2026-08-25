# CoderKing

自主 Coding Agent 运行时：用自然语言描述工程任务，在仓库里完成规划、改代码、沙箱执行、测试与修复。CLI 与 Web 共用同一套 Agent Runtime，对标 Codex / OpenHands 的工程闭环，而不是「再包一层聊天框」。

第一期是可运行的 MVP（方案 A：单仓 + Python Runtime + 独立 React 工作台），不是完整 SaaS。

## 命名约定（请按这个用）

产品名是 **CoderKing**。命令行、Python 包、环境变量一律用小写 `coderking`，避免 Windows / Linux 大小写不一致。

| 用途 | 正确写法 | 不要写成 |
| --- | --- | --- |
| 产品名 | CoderKing | AgentForge-Coder |
| PyPI / import | `coderking` | `agentforge_coder` |
| CLI | `coderking run "..."` | `CoderKing run` |
| 本地配置目录 | `.coderking/` | `.CoderKing/` |
| 环境变量前缀 | `CODERKING_` | `AGENTFORGE_` |

设计文档里的 `CoderKing run` 是产品文案；安装后的可执行文件是 `coderking`。若要上 PyPI，请先确认 `coderking` 是否已被占用，占用则改发布名为 `coderking-agent`（import 仍可保持 `coderking`）。

## 能力

- 自研 ReAct + Reflection Loop（不依赖 LangChain / LangGraph）
- 同一 Runtime 下的角色：Planner / Coding / Execution / Reviewer / Repair（prompt + 工具权限，不是多进程）
- Tool Protocol：File / Shell / Git / Test + 计划/收尾元工具
- Sandbox：Docker 为主；无 Docker 时 **local process 仅作 development fallback**，文档与事件里会标明，不当作强隔离
- 多模型：统一 OpenAI Compatible（DeepSeek / GLM / Qwen / Ollama 换 `base_url` + 模型名即可）
- CLI 与 Web 调同一 Runtime；Web 提供 Chat、Task Plan、Tool Trace、文件树、Terminal / Test / Sandbox 状态
- `eval/tasks` 覆盖 `bug_fix`、`feature_add`、`refactor`

## 架构

```text
User → CLI / Web UI → FastAPI + WebSocket
                         ↓
                   Agent Runtime
                         ↓
              Planner → Coding → Execution → Reviewer
                         ↘ Repair ↗
                         ↓
              Tools → Sandbox → Workspace
```

CLI 的 `coderking run` 默认 **进程内** 调用 Runtime（不必先起服务）。`coderking serve` 把同一 Runtime 暴露给 Web。这与「统一 Runtime」一致，而不是强迫本地开发先开 HTTP。

## 快速开始

要求：Python 3.12+，Node 22+（仅 Web），可选 Docker。

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
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
python -m coderking init
python -m coderking config model --base-url https://api.deepseek.com/v1 --model deepseek-chat
python -m coderking run "修复当前仓库里失败的单元测试" --workspace .
python -m coderking chat --workspace .
python -m coderking status
python -m coderking stop <task_id>
python -m coderking eval --path eval/tasks --report-dir eval/reports
```

配置优先级：CLI 参数 > 环境变量 / `.env` > `.coderking/config.yaml` > 默认值。API Key 只走环境变量，不写入 yaml。

`pytest -q -m "not docker"` 跑普通单测。本机有 Docker 时再跑 `pytest tests/test_docker.py`。

危险操作（删文件、危险 shell、`git commit`）默认要确认。`--yes` 自动批准。`--commit` 才允许 Agent 提交。

### Web

```bash
coderking serve --port 8000
```

另开终端：

```bash
cd web
npm install
npm run dev
```

浏览器打开 `http://127.0.0.1:5173`。生产构建 `npm run build` 后，若存在 `web/dist`，FastAPI 会一并托管静态资源。

### 评测

```bash
coderking eval --path eval/tasks
```

## 配置

| 变量 | 含义 |
| --- | --- |
| `CODERKING_OPENAI_BASE_URL` | OpenAI Compatible 网关 |
| `CODERKING_OPENAI_API_KEY` | API Key，勿提交进 Git |
| `CODERKING_MODEL` | 模型名 |
| `CODERKING_DISABLE_THINKING` | 关闭推理模型 thinking（默认 true）。官方 OpenAI 若 400，设为 false |
| `CODERKING_SANDBOX_MODE` | `auto` / `docker` / `local` |
| `CODERKING_ALLOW_COMMIT` | 是否允许 `git_commit` |

官方 OpenAI 不认识 `thinking` 字段时，客户端会自动去掉该字段重试一次。

## 工程化

```bash
pre-commit install
pre-commit run --all-files
pytest -q -m "not docker"
ruff check src tests
cd web && npm run lint && npm run build
```

CI：`.github/workflows/ci.yml`（单测默认跳过 Docker 集成；另有 `docker-sandbox` job）。

## 仓库布局

```text
src/coderking/     Python Runtime、CLI、API
web/               React + Vite + Tailwind 工作台
eval/tasks/        bug_fix / feature_add / refactor
tests/             单测
```

设计原文：`docs/CoderKing-Technical-Design.md`、`docs/CoderKing-WebUI-CLI-Design.md`。第一期明确不做：多租户、PostgreSQL/Redis/Milvus、Daytona、完整 SWE-bench。

## 简历表述（可直接用）

CoderKing：自研 Agent Loop 与 Tool Protocol 的 Coding Agent（CLI + Web）。第一期交付范围与验证结果见 `docs/phase1-acceptance.md`，不要把未勾选项写成已上线能力。
