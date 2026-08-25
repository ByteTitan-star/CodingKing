# CoderKing Phase 1 验收记录

日期：2026-08-25

本文件只记录**实际跑过的证据**。API Key 不写入本文档、不写入报告、不提交 git。`.env` 已被 `.gitignore` 排除（`git check-ignore -v .env` → `.gitignore:13:.env`）。

## 检查清单

```text
[x] CLI 真实模型 Coding Task          — glm-5.2 + Coding Plan OpenAI 端点；三类 Eval 全通过。
[x] bug_fix Eval                     — eval/reports/phase1-report.*（live）
[x] feature_add Eval                  — 同上
[x] refactor Eval                     — 同上
[x] Docker Sandbox                    — pytest tests/test_docker.py：3 passed
[x] Local fallback                    — 真实 Eval / Repair / Web 均用 local sandbox
[x] Web 创建并执行真实任务            — Playwright：eval/reports/web-e2e-report.*（passed=true）
[x] Web Task Diff                     — web-e2e：diff_plus_minus=true
[x] Web Stop                          — web-e2e：stop_status + stop_no_late_write
[x] Real-model Repair Path            — mode=repair_fault_injection；eval/reports/repair-path-report.*
[x] Eval Report                       — phase1-report / repair-path-report / web-e2e-report
[x] Backend tests                     — pytest -q -m "not docker"：26 passed
[x] Frontend build                    — web npm run build：passed
```

## 真实模型配置（无 Key）

CoderKing 只请求 `{base_url}/chat/completions`：

- `.../api/anthropic`：不兼容（Anthropic Messages）
- `.../api/paas/v4`：开放平台；本 Key 曾 429
- `.../api/coding/paas/v4`：可用（本验收使用）

## Web 浏览器 E2E（Playwright + 真实模型）

证据：`eval/reports/web-e2e-report.json`

| 检查项 | 结果 |
| --- | --- |
| 页面打开 | pass |
| 创建任务并完成 | pass（status=已完成） |
| Plan / Activity / 角色 | pass（planner→coding→execution→reviewer） |
| Tool Trace | pass |
| Terminal / Test Result | pass |
| Diff +/- / Changed Files | pass |
| Tokens / Iteration | pass |
| Stop Task + 无晚写文件 | pass（status=已中断） |

## Real-model Repair Path（fault injection）

**独立场景**，不污染 `eval/tasks` 三类 Benchmark。

证据：`eval/reports/repair-path-report.json`（`mode: repair_fault_injection`）

闭环（真实 glm-5.2）：

1. Coding 后首次 `run_tests` 前注入故障：`multiply` 被改成 `a + b`
2. 首次测试失败：`assert 7 == 12`
3. Reviewer → `request_repair`
4. Repair → `write_file` 恢复 `a * b`
5. 再测 `exit=0` → Reviewer → `finish_task`

| 指标 | 值 |
| --- | --- |
| model | glm-5.2 |
| success | true |
| repair_count | 1 |
| iterations | 11 |
| tool_calls | 12 |
| tokens | 21292 / 727 |
| reviewer_decision | request_repair |
| roles | planner → coding → execution → reviewer → repair → execution → reviewer |

Runtime 变更：测试失败不再直接跳 Repair，而是先进入 Reviewer，由 `request_repair` 进入 Repair（与简历「自动修复闭环」一致）。

## 三类真实 Coding Eval（摘要）

详见 `eval/reports/phase1-report.json`（`extra.scripted=false` / live）。

| 任务 | iters | tools | 改文件 | 首次测试 | Repair | 最终测试 |
| --- | --- | --- | --- | --- | --- | --- |
| bug_fix_add | 7 | 8 | calc.py | pass | 0 | pass |
| feature_add_greet | 8 | 9 | greet.py | pass | 0 | pass |
| refactor_area | 6 | 7 | geometry.py | pass | 0 | pass |

## 明确结论

**CoderKing Phase 1：CLI + 可用 Web 达到正式交付标准。**

剩余非阻塞项（非 P0）：

- HITL Approve/Reject 未做浏览器点通（Web 默认 auto_approve；API/单测已有）
- Accept/Rollback 未做浏览器点通（API 单测已有）
- `refactor_area` prompt token 波动较大，属 Context Engineering，留二期

禁止范围未扩大：未做 Chroma / Milvus / PostgreSQL / Redis / Daytona / 多租户。

## 本机验证命令

- `git check-ignore -v .env`
- `python scripts/live_probe.py` / `live_smoke_agent.py` / `live_eval.py` / `live_repair.py` / `web_e2e.py`
- `python -m coderking serve --port 8000` + `cd web && npm run dev`
- `python -m pytest -q -m "not docker"` → **26 passed**
- `python -m pytest -q tests/test_docker.py` → **3 passed**
- `cd web && npm run build` → passed
