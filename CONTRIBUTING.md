# 贡献指南

## 开发环境

- Python 3.12
- 推荐：`pip install -e ".[dev]"` 后执行 `pre-commit install`
  - 这一步会装上 commit 时自动修格式、push 时对齐 CI 门槛的钩子
  - 推送前钩子需要拉取钩子仓库，首次运行需联网
- Web：`cd web && npm install`

## 提交

- 不要把 `.env`、真实 API Key 提交进仓库
- 提交信息建议 Conventional Commits：`feat:` / `fix:` / `docs:` / `test:` / `chore:`

## 推送前本地门槛（与 CI 完全一致）

CI 的 `python` job 执行以下检查，本地推送前请跑齐同样的四条（装了 pre-commit 并 `pre-commit install` 后，push 时会自动执行前两条）：

```bash
ruff check src tests scripts packages
ruff format --check src tests scripts packages
python scripts/check_layer_deps.py
pytest -q -m "not docker and not live"
```

> 历史教训：CI 一直有 `ruff format --check` 这道门，但早期贡献者本地只跑 `ruff check`，
> 导致某个不合规文件进入 main 后连续十几次 CI 全红（连纯文档 PR 也挂）。
> 所以上面的四条请原样复制执行，别只跑其中一两条。

- 有 Docker 时再跑：`pytest tests/test_docker.py`
- 真实模型评测需要根目录 `.env`（从 `.env.example` 复制，不要提交）

## 范围

第一期只强化 Runtime、工具边界、沙箱与可观测性。不要在未讨论的情况下引入 LangChain、独立微服务拆分或完整账号体系。
