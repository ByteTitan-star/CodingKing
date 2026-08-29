# CoderKing Phase 1 验收记录

日期：2026-08-25（更新：2026-08-29 — 真实模型 live E2E 通过）

本文件只记录**实际跑过的证据**。没有 API Key 的环境不能勾选「真实模型 E2E」。

## 检查清单

```text
[x] CLI 可以完成 Coding Task          — 命令存在；scripted Runtime 单测通过。未用真实模型跑 `coderking run`。
[x] Web 可以完成 Coding Task          — 工作台已接真实 API/WS/Diff/Stop/HITL/Rollback。未做浏览器人工点通。
[x] 真实模型 E2E 成功                 — 2026-08-29 本机：`pytest -q -m live tests/e2e` → 4 passed（约 4m41s）；`coderking eval` 3/3 success，token_usage=24526，model=glm-5.2。
[x] 测试失败可以自动 Repair           — `tests/test_runtime_loop.py::test_failed_tests_go_repair_then_succeed` 通过。
[x] Docker Sandbox 验证成功           — 本机 `pytest tests/test_docker.py`：3 passed（echo / mount+network / timeout 无残留容器）。
[x] Local fallback 验证成功           — scripted loop 与 eval harness 使用 `sandbox_mode=local`，测试通过。
[x] Web 可以查看 Diff                 — `GET /api/tasks/{id}/diff` + Web DiffViewer；`tests/test_api.py`、`tests/test_diffing.py` 通过。未浏览器点通。
[x] Web 可以 Stop Task                — `POST /api/tasks/{id}/interrupt` 取消 token + cancel 文件；API 单测有 interrupt。
[x] CLI 可以 Stop Task                — `coderking stop <task_id>` 写 cancel 文件；`--help` 含 stop。跨进程与 in-flight HTTP 取消有 `tests/test_cancel.py`。
[x] Eval 可以生成报告                 — `eval/reports/latest.json|md` 与 `phase1-report.json|md` 已用真实模型重跑，`extra.llm.mode=live`。
```

## 真实模型 E2E（#22）

配置 `.env` / 环境变量 `CODERKING_OPENAI_API_KEY`（真实 provider key，勿提交）：

```bash
pytest -q -m live tests/e2e --tb=short
python -m coderking eval --path eval/tasks --report-dir eval/reports
```

### 2026-08-29 本机证据

| 项 | 结果 |
|----|------|
| `pytest -m live tests/e2e` | 4 passed in 281.06s |
| eval task success_rate | 1.0（3/3：bug_fix_add / feature_add_greet / refactor_area） |
| token_usage | 24526 |
| report `extra.llm.mode` | `live` |
| CI | job `e2e-live` 在 secret `CODERKING_OPENAI_API_KEY` 存在时执行 |

## 本机已执行的验证命令

- `python -m pytest -q -m "not docker and not live"`
- `python -m pytest -q -m live tests/e2e --tb=short`（2026-08-29，4 passed）
- `python -m coderking eval --path eval/tasks --report-dir eval/reports`（2026-08-29，3/3）
- `python -m pytest -q tests/test_docker.py`（本机 Docker 可用时）
- `python -m ruff check src tests`
- `cd web && npm run lint && npm run build`
