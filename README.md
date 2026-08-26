# CoderKing

<p align="center">
  <a href="https://github.com/ByteTitan-star/CodingKing"><img src="https://img.shields.io/badge/CoderKing-v0.1.0-2563eb" alt="CoderKing v0.1.0" /></a>
  <img src="https://img.shields.io/badge/python-3.12-3776AB" alt="Python 3.12" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT" /></a>
  <img src="https://img.shields.io/badge/English-0A66C2" alt="English" />
  <a href="./README_zh.md"><img src="https://img.shields.io/badge/%E4%B8%AD%E6%96%87-555555" alt="Chinese" /></a>
</p>

> Describe an engineering task in natural language — plan, edit code, run tests in a sandbox, and auto-repair until verification passes. One Agent Runtime powers both CLI and Web.

## What is CoderKing?

CoderKing is an autonomous coding agent runtime for software engineering workflows. You describe a task in natural language; the agent plans the work, modifies the repository, executes commands in an isolated sandbox, runs tests, and enters a repair loop when verification fails — all through a single runtime shared by CLI and Web UI.

Phase 1 is a runnable MVP (Python runtime + React workspace in one repo), not a multi-tenant SaaS.

## Agent workflow

| Stage | Key action | Stage output |
| --- | --- | --- |
| Task input | Describe a bug fix, feature, or refactor in CLI or Web. | A clear engineering brief |
| Planning | Break the task into reviewable steps. | A structured task plan |
| Coding | Read, search, and edit files in the workspace. | Patched source code |
| Execution | Run shell commands and tests inside the sandbox. | Command and test output |
| Review | Verify results against the plan and diff. | Pass / fail decision |
| Repair | On test failure, diagnose and patch again. | A corrected implementation |
| Delivery | Finish with diff summary; optional git commit with approval. | A completed task |

## Core features

| Feature | Description |
| --- | --- |
| Unified runtime | CLI and Web call the same Agent Runtime — no duplicate orchestration logic. |
| ReAct + reflection loop | Custom agent loop without LangChain / LangGraph dependencies. |
| Role-based tools | Planner, Coding, Execution, Reviewer, and Repair roles with scoped tool access. |
| Sandbox execution | Docker-first isolation; local process fallback for development only. |
| Model-agnostic | OpenAI-compatible APIs — DeepSeek, GLM, Qwen, Ollama, and similar gateways. |
| Human-in-the-loop | Dangerous operations require explicit approval unless `--yes` is set. |
| Evaluation harness | Scripted tasks for `bug_fix`, `feature_add`, and `refactor`. |
| Live observability | Web UI shows plan, tool trace, terminal output, diff, and sandbox status. |

## Architecture

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

`coderking run` invokes the runtime in-process (no HTTP server required). `coderking serve` exposes the same runtime to the Web UI.

## Quick start

**Requirements:** Python 3.12+, Node 22+ (Web only), Docker optional.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env
```

Edit `.env`:

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
coderking run "Fix failing unit tests in this repo" --workspace .
coderking chat --workspace .
coderking status
coderking stop <task_id>
coderking eval --path eval/tasks --report-dir eval/reports
```

Configuration priority: CLI flags → environment / `.env` → `.coderking/config.yaml` → defaults. API keys are read from the environment only and must not be committed.

Run tests: `pytest -q -m "not docker"`. With Docker available: `pytest tests/test_docker.py`.

Use `--yes` to auto-approve dangerous operations. Use `--commit` to allow the agent to run `git commit`.

### Web

```bash
coderking serve --port 8000
```

In another terminal:

```bash
cd web && npm install && npm run dev
```

Open `http://127.0.0.1:5173`. For production, run `npm run build` — FastAPI serves `web/dist` when present.

## Configuration

| Variable | Description |
| --- | --- |
| `CODERKING_OPENAI_BASE_URL` | OpenAI-compatible API base URL |
| `CODERKING_OPENAI_API_KEY` | API key (never commit to Git) |
| `CODERKING_MODEL` | Model name |
| `CODERKING_DISABLE_THINKING` | Disable reasoning-model `thinking` field (default `true`) |
| `CODERKING_SANDBOX_MODE` | `auto`, `docker`, or `local` |
| `CODERKING_ALLOW_COMMIT` | Allow the `git_commit` tool |

If the upstream API rejects the `thinking` field, the client strips it and retries once automatically.

## Development

```bash
pre-commit install
pre-commit run --all-files
pytest -q -m "not docker"
ruff check src tests
cd web && npm run lint && npm run build
```

CI: `.github/workflows/ci.yml` (unit tests skip Docker by default; a separate `docker-sandbox` job runs Docker integration tests).

## Repository layout

```text
src/coderking/     Python runtime, CLI, and API
web/               React + Vite workspace
eval/tasks/        Evaluation scenarios
tests/             Unit tests
docs/              Design docs and acceptance checklist
```

## Documentation

- [Technical design](docs/CoderKing-Technical-Design.md)
- [Web UI & CLI design](docs/CoderKing-WebUI-CLI-Design.md)
- [Phase 1 acceptance](docs/phase1-acceptance.md)

## Naming

| Use | Value |
| --- | --- |
| Product name | CoderKing |
| Python package / CLI | `coderking` |
| Config directory | `.coderking/` |
| Environment prefix | `CODERKING_` |

## License

MIT © CodeTitan, 2026 — see [LICENSE](LICENSE).
