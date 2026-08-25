# 贡献指南

## 开发环境

- Python 3.12
- 推荐：`pip install -e ".[dev]"` 后执行 `pre-commit install`
- Web：`cd web && npm install`

## 提交

- 不要把 `.env`、真实 API Key 提交进仓库
- 提交信息建议 Conventional Commits：`feat:` / `fix:` / `docs:` / `test:` / `chore:`
- 推送前本地至少通过：`pytest -q -m "not docker"` 与 `ruff check src tests`
- 有 Docker 时再跑：`pytest tests/test_docker.py`
- 真实模型评测需要根目录 `.env`（从 `.env.example` 复制，不要提交）

## 范围

第一期只强化 Runtime、工具边界、沙箱与可观测性。不要在未讨论的情况下引入 LangChain、独立微服务拆分或完整账号体系。
