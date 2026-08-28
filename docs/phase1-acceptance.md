# CoderKing Phase 1 验收记录

日期：2026-08-25（更新：2026-08-28 — live E2E harness）

本文件只记录**实际跑过的证据**。没有 API Key 的环境不能勾选「真实模型 E2E」。

## 检查清单

```text
[x] CLI 可以完成 Coding Task          — 命令存在；scripted Runtime 单测通过。未用真实模型跑 `coderking run`。
[x] Web 可以完成 Coding Task          — 工作台已接真实 API/WS/Diff/Stop/HITL/Rollback。未做浏览器人工点通。
[ ] 真实模型 E2E 成功                 — harness 已就绪：`pytest -m live tests/e2e` + CI `e2e-live`（需 repo secret）。本环境未配置真实 key，故未勾选。
[x] 测试失败可以自动 Repair           — `tests/test_runtime_loop.py::test_failed_tests_go_repair_then_succeed` 通过。
[x] Docker Sandbox 验证成功           — 本机 `pytest tests/test_docker.py`：3 passed（echo / mount+network / timeout 无残留容器）。
[x] Local fallback 验证成功           — scripted loop 与 eval harness 使用 `sandbox_mode=local`，测试通过。
[x] Web 可以查看 Diff                 — `GET /api/tasks/{id}/diff` + Web DiffViewer；`tests/test_api.py`、`tests/test_diffing.py` 通过。未浏览器点通。
[x] Web 可以 Stop Task                — `POST /api/tasks/{id}/interrupt` 取消 token + cancel 文件；API 单测有 interrupt。
[x] CLI 可以 Stop Task                — `coderking stop <task_id>` 写 cancel 文件；`--help` 含 stop。跨进程与 in-flight HTTP 取消有 `tests/test_cancel.py`。
[x] Eval 可以生成报告                 — `eval/reports/latest.json|md` 与 `phase1-report.json|md` 已生成（**ScriptedLLM 夹具**，不是真实模型）。
```

## 真实模型 E2E（#22）

配置 `.env` / 环境变量 `CODERKING_OPENAI_API_KEY`（真实 provider key，勿提交）：

```bash
pytest -q -m live tests/e2e --tb=short
python -m coderking eval --path eval/tasks --report-dir eval/reports
```

CI：job `e2e-live` 在 GitHub secret `CODERKING_OPENAI_API_KEY` 存在时执行；缺失则 skip（exit 0）。
成功标准：3 类 eval task success_rate ≥ 2/3；报告 `extra.llm.mode=live`。

## 明确未交付为「真实模型闭环」的原因

当前 eval 报告 `extra.llm` 若为 scripted fixture，则 **不能** 勾选上方「真实模型 E2E」。

## 本机已执行的验证命令

- `python -m pytest -q -m "not docker and not live"`
- `python -m pytest -q tests/test_docker.py`（本机 Docker 可用时）
- `python -m ruff check src tests`
- `cd web && npm run lint && npm run build`
