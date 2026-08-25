"""Live repair-path runner with explicit fault injection (not a coding benchmark)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from coderking.config import Settings
from coderking.diffing import unified_diff
from coderking.evalkit.fault_injection import FirstRunTestsFaultInjector
from coderking.evalkit.loader import EvalTask
from coderking.llm.provider import LLMProvider
from coderking.runtime.events import AgentEvent
from coderking.runtime.loop import AgentRuntime
from coderking.runtime.state import TaskStatus
from coderking.sandbox.local import LocalProcessSandbox

FAULTY_MULTIPLY = "def multiply(a: int, b: int) -> int:\n    return a + b\n"


async def run_repair_path(
    task: EvalTask,
    dest: Path,
    settings: Settings,
    llm: LLMProvider,
) -> dict[str, Any]:
    injector = FirstRunTestsFaultInjector(dest, "multiply.py", FAULTY_MULTIPLY)
    events: list[AgentEvent] = []
    snapshots: list[str] = []

    async def on_event(event: AgentEvent) -> None:
        events.append(event)
        if event.type == "test_result":
            snapshots.append((dest / "multiply.py").read_text(encoding="utf-8"))

    runtime = AgentRuntime(settings, llm)
    state = await runtime.run(
        task.instruction,
        dest,
        on_event=on_event,
        auto_approve=True,
        test_command=task.test_command,
        wrap_tools=injector.wrap,
    )
    test_events = [str(e.payload.get("text", "")) for e in events if e.type == "test_result"]
    first_fail = test_events[0] if test_events else ""
    retest = test_events[1] if len(test_events) > 1 else ""
    reviewer_tools = [
        r.name
        for r in state.tool_history
        if r.name in {"finish_task", "request_repair", "continue_execution"}
    ]
    repair_started = False
    repair_calls = []
    for rec in state.tool_history:
        if rec.name == "request_repair":
            repair_started = True
        if repair_started:
            repair_calls.append({"tool": rec.name, "ok": rec.ok, "preview": rec.output[:400]})
    sandbox = LocalProcessSandbox(dest)
    final = await sandbox.run(task.test_command, timeout_sec=settings.sandbox_timeout_sec)
    roles = [e.payload.get("role") for e in events if e.type == "agent_status"]
    path_ok = (
        injector.injected
        and (not _test_ok(first_fail))
        and "request_repair" in {r.name for r in state.tool_history}
        and "repair" in roles
        and _test_ok(retest or "")
        and state.status == TaskStatus.SUCCEEDED
        and final.exit_code == 0
    )
    return {
        "mode": "repair_fault_injection",
        "task_id": task.task_id,
        "model": settings.model,
        "success": path_ok,
        "status": state.status.value,
        "injected": injector.injected,
        "first_failure_log": first_fail,
        "reviewer_decision": reviewer_tools[0] if reviewer_tools else "",
        "repair_tool_calls": repair_calls,
        "repair_changed_files": [
            r.arguments.get("path")
            for r in state.tool_history
            if r.name in {"write_file", "create_file"} and r.ok
        ],
        "source_after_first_test": snapshots[0] if snapshots else "",
        "source_final": (dest / "multiply.py").read_text(encoding="utf-8"),
        "diff_final": unified_diff(dest, state.snapshot),
        "retest_result": retest,
        "final_test_result": final.combined,
        "repair_count": state.repair_count,
        "iterations": state.iteration,
        "tool_calls": len(state.tool_history),
        "roles": roles,
        "tokens": {"prompt": state.token_input, "completion": state.token_output},
        "error": "; ".join(state.errors),
    }


def _test_ok(text: str) -> bool:
    head = text.split("\n", 1)[0]
    return "exit=0" in head


def write_repair_report(payload: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    body = {"generated_at": datetime.now(UTC).isoformat(), **payload}
    json_path = out_dir / "repair-path-report.json"
    md_path = out_dir / "repair-path-report.md"
    json_path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Repair path report",
        "",
        f"Generated: {body['generated_at']}",
        "",
        "- mode: repair_fault_injection",
        f"- model: {payload.get('model')}",
        f"- success: {payload.get('success')}",
        f"- injected: {payload.get('injected')}",
        f"- reviewer_decision: {payload.get('reviewer_decision')}",
        f"- repair_count: {payload.get('repair_count')}",
        f"- iterations: {payload.get('iterations')}",
        f"- tool_calls: {payload.get('tool_calls')}",
        f"- tokens: {payload.get('tokens')}",
        "",
        "## First failure log",
        "",
        "```",
        str(payload.get("first_failure_log") or "")[:4000],
        "```",
        "",
        "## Repair tool calls",
        "",
    ]
    for call in payload.get("repair_tool_calls") or []:
        lines.append(f"- {call.get('tool')} ok={call.get('ok')}")
        lines.append(f"  {str(call.get('preview') or '')[:300]}")
    lines.extend(
        [
            "",
            "## Source after first test (injected fault expected)",
            "",
            "```python",
            str(payload.get("source_after_first_test") or "")[:2000],
            "```",
            "",
            "## Final source",
            "",
            "```python",
            str(payload.get("source_final") or "")[:2000],
            "```",
            "",
            "## Final diff vs snapshot",
            "",
            "```diff",
            str(payload.get("diff_final") or "(none)")[:8000],
            "```",
            "",
            "## Re-test",
            "",
            "```",
            str(payload.get("retest_result") or "")[:2000],
            "```",
        ]
    )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path
