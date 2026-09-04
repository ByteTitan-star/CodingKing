<h1 align="center">💻 CoderKing</h1>

<p align="center">
  <a href="https://github.com/ByteTitan-star/CodingKing/releases/tag/v1.0.9"><img src="https://img.shields.io/badge/CoderKing-v1.0.9-2563eb" alt="CoderKing v1.0.9" /></a>
  <img src="https://img.shields.io/badge/python-3.12-3776AB" alt="Python 3.12" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT" /></a>
  <a href="https://github.com/ByteTitan-star/CodingKing/actions/workflows/ci.yml?query=branch%3Amain"><img src="https://github.com/ByteTitan-star/CodingKing/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI" /></a>
  <img src="https://img.shields.io/badge/English-0A66C2" alt="English" />
  <a href="./README_zh.md"><img src="https://img.shields.io/badge/%E4%B8%AD%E6%96%87-555555" alt="Chinese" /></a>
</p>

> Describe an engineering task in natural language — the coding agent edits code with read/write/edit/bash, verifies with tests in a sandbox, and keeps iterating until checks pass. One Agent Runtime powers both CLI and Web.

<p align="center">
  <a href="./docs/showcase/demo.html"><strong>Open workspace demo</strong></a>
  &nbsp;·&nbsp;
  <a href="./docs/CoderKing-Technical-Design.md"><strong>Read technical design</strong></a>
</p>

## What is CoderKing?

CoderKing is an autonomous **coding agent** runtime (Pi-aligned). You describe a task in natural language; a single agent loop uses four tools (`read` / `write` / `edit` / `bash`) to change the repository, run checks in an isolated sandbox, and continue until verification passes. CLI and Web share the same runtime — there is no fixed multi-role workflow.

Phase 1 is a runnable MVP (Python runtime + React workspace in one repo), not a multi-tenant SaaS.

## How the agent works

| Step | What happens |
| --- | --- |
| Task | You describe a bug fix, feature, or refactor in CLI or Web. |
| Loop | The model chooses tools each turn (explore → edit → run checks). |
| Verify | After edits, it runs tests/lint via `bash` (prompt-guided; optional `--test` hint). |
| Iterate | On failure, it diagnoses from tool output and edits again. |
| Deliver | Stops when the task is done and verification passed; review the diff. |

## Product showcase

### Agent loop in action

![CoderKing workspace during a bug-fix repair loop](docs/showcase/assets/product-workspace.png)

A failing unit test triggers the pure agent loop (edit → bash/tests → iterate). The workspace shows tool trace, patched files, and pytest output in one view.

### Unified diff

![CoderKing diff viewer after repair](docs/showcase/assets/product-diff.png)

Review exactly what changed before accepting or rolling back.

## Product interface

| Engineering workspace | Diff & runtime |
| --- | --- |
| ![CoderKing engineering workspace](docs/showcase/assets/product-workspace.png) | ![CoderKing diff and runtime panel](docs/showcase/assets/product-diff.png) |
| Describe a task, watch agent activity, and inspect changed files. | Inspect unified diffs, terminal output, and test results side by side. |

Screenshots live under [`docs/showcase/`](docs/showcase/). Re-capture with `python scripts/capture_showcase.py` or replace assets after a live demo run.

## Core features

| Feature | Description |
| --- | --- |
| Unified runtime | CLI and Web call the same Agent Runtime — no duplicate orchestration logic. |
| Pure agent loop | Pi-aligned ReAct-style loop without LangChain / LangGraph and without fixed role stages. |
| Four atomic tools | `read` / `write` / `edit` / `bash` only — the model decides the order. |
| Prompt verification | After edits, run checks with bash; optional `--test` soft hint (not a hard gate). |
| Sandbox execution | Docker-first isolation; local process fallback for development only. |
| Model-agnostic | OpenAI-compatible APIs — DeepSeek, GLM, Qwen, Ollama, and similar gateways. |
| Human-in-the-loop | Dangerous operations require explicit approval unless `--yes` is set. |
| Evaluation harness | Scripted tasks for `bug_fix`, `feature_add`, and `refactor`. |
| Live observability | Web UI shows tool trace, terminal output, diff, and sandbox status. |

<p align="center">
  <a href="./docs/showcase/demo.html"><strong>Explore the workspace demo</strong></a>
  &nbsp;·&nbsp;
  <a href="./docs/phase1-acceptance.md"><strong>Phase 1 acceptance checklist</strong></a>
</p>

## Architecture

```text
User → CLI / Web UI → FastAPI + WebSocket
                         ↓
                   Agent Runtime
                         ↓
              L1 pure loop: Perceive → Decide → Act → Observe
                         ↓
              Tools (read/write/edit/bash) → Sandbox → Workspace
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
coderking run "Fix failing tests" --workspace . --test "python -m pytest -q"
coderking chat --workspace .
coderking status
coderking stop <task_id>
coderking eval --path eval/tasks --report-dir eval/reports
```

Configuration priority: CLI flags → environment / `.env` → `.coderking/config.yaml` → defaults. API keys are read from the environment only and must not be committed.

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

With Docker available: `pytest tests/test_docker.py`.

See [CONTRIBUTING.md](CONTRIBUTING.md) for scope and commit conventions. CI runs via [`.github/workflows/ci.yml`](.github/workflows/ci.yml) (unit tests skip Docker by default; a separate `docker-sandbox` job runs Docker integration tests).

## Repository layout

```text
src/coderking/     Python runtime, CLI, and API
web/               React + Vite workspace
eval/tasks/        Evaluation scenarios
tests/             Unit tests
docs/              Design docs, showcase assets, and acceptance checklist
```

## Documentation

- [Technical design](docs/CoderKing-Technical-Design.md)
- [Web UI & CLI design](docs/CoderKing-WebUI-CLI-Design.md)
- [Phase 1 acceptance](docs/phase1-acceptance.md)

## License

MIT © CodeTitan, 2026 — see [LICENSE](LICENSE).
