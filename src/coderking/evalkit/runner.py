from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from coderking.config import Settings
from coderking.diffing import unified_diff
from coderking.evalkit.loader import EvalTask, discover_tasks
from coderking.llm.provider import LLMProvider
from coderking.runtime.events import AgentEvent
from coderking.runtime.loop import AgentRuntime
from coderking.runtime.state import TaskStatus
from coderking.sandbox.local import LocalProcessSandbox


@dataclass
class EvalMetrics:
    task_id: str
    category: str
    success: bool
    test_pass: bool
    iterations: int
    repair_used: bool
    repair_count: int
    tool_calls: int
    prompt_tokens: int
    completion_tokens: int
    changed_files: list[str]
    first_test_result: str
    final_test_result: str
    diff: str
    error: str = ""
    model: str = ""


async def run_eval_task(
    task: EvalTask,
    task_dir: Path,
    settings: Settings,
    llm: LLMProvider,
) -> EvalMetrics:
    src = task.repo_path(task_dir)
    tmp = Path(tempfile.mkdtemp(prefix="coderking-eval-"))
    try:
        dest = tmp / "repo"
        shutil.copytree(src, dest)
        runtime = AgentRuntime(settings, llm)
        events: list[AgentEvent] = []

        async def on_event(event: AgentEvent) -> None:
            events.append(event)

        state = await runtime.run(
            task.instruction,
            dest,
            on_event=on_event,
            auto_approve=True,
            test_command=task.test_command,
        )
        sandbox = LocalProcessSandbox(dest)
        test = await sandbox.run(task.test_command, timeout_sec=settings.sandbox_timeout_sec)
        test_events = [e.payload.get("text", "") for e in events if e.type == "test_result"]
        repair_used = any(
            e.payload.get("role") == "repair" for e in events if e.type == "agent_status"
        )
        return EvalMetrics(
            task_id=task.task_id,
            category=task.category,
            success=state.status == TaskStatus.SUCCEEDED and test.exit_code == 0,
            test_pass=test.exit_code == 0,
            iterations=state.iteration,
            repair_used=repair_used,
            repair_count=state.repair_count,
            tool_calls=len(state.tool_history),
            prompt_tokens=state.token_input,
            completion_tokens=state.token_output,
            changed_files=list(state.changed_files),
            first_test_result=str(test_events[0] if test_events else ""),
            final_test_result=test.combined,
            diff=unified_diff(dest, state.snapshot),
            error="; ".join(state.errors),
            model=settings.model,
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def run_suite(eval_root: Path, settings: Settings, llm: LLMProvider) -> list[EvalMetrics]:
    results = []
    for task, task_dir in discover_tasks(eval_root):
        results.append(await run_eval_task(task, task_dir, settings, llm))
    return results


def summarize(results: list[EvalMetrics]) -> dict[str, float]:
    n = max(len(results), 1)
    return {
        "task_success_rate": sum(r.success for r in results) / n,
        "test_pass_rate": sum(r.test_pass for r in results) / n,
        "repair_success_rate": (
            sum(r.success for r in results if r.repair_used)
            / max(sum(1 for r in results if r.repair_used), 1)
        ),
        "avg_iterations": sum(r.iterations for r in results) / n,
        "avg_tool_calls": sum(r.tool_calls for r in results) / n,
        "token_usage": float(sum(r.prompt_tokens + r.completion_tokens for r in results)),
    }


def write_reports(
    results: list[EvalMetrics],
    out_dir: Path,
    *,
    stem: str = "latest",
    extra: dict | None = None,
) -> tuple[Path, Path]:
    from coderking_coding_agent.sandbox.credentials import (
        contains_secret_marker,
        redact_tool_arguments,
        scrub_secret_text,
    )

    def _scrub_text(text: str, *, max_len: int = 8000) -> str:
        cleaned = (
            scrub_secret_text(text or "") if contains_secret_marker(text or "") else (text or "")
        )
        if len(cleaned) > max_len:
            cleaned = cleaned[:max_len] + f"\n…<truncated n={len(cleaned) - max_len}>"
        return cleaned

    out_dir.mkdir(parents=True, exist_ok=True)
    safe_results = []
    for item in results:
        row = asdict(item)
        for field in ("diff", "first_test_result", "final_test_result", "error"):
            if isinstance(row.get(field), str):
                row[field] = _scrub_text(row[field])
        safe_results.append(row)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": summarize(results),
        "extra": redact_tool_arguments(extra or {}) if extra else {},
        "results": safe_results,
    }
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        f"# CoderKing eval report (`{stem}`)",
        "",
        f"Generated: {payload['generated_at']}",
        "",
        "## Summary",
        "",
    ]
    for key, value in payload["summary"].items():
        lines.append(f"- {key}: {value}")
    if extra:
        lines.extend(["", "## Extra", ""])
        for key, value in payload["extra"].items():
            lines.append(f"- {key}: {value}")
    lines.extend(["", "## Tasks", ""])
    for row in safe_results:
        lines.extend(
            [
                f"### {row['task_id']} ({row['category']})",
                "",
                f"- success: {row['success']}",
                f"- test_pass: {row['test_pass']}",
                f"- iterations: {row['iterations']}",
                f"- tool_calls: {row['tool_calls']}",
                f"- repair_count: {row['repair_count']}",
                f"- model: {row['model']}",
                f"- changed_files: {', '.join(row['changed_files']) or '(none)'}",
                f"- tokens: {row['prompt_tokens']} / {row['completion_tokens']}",
                "",
                "```diff",
                (row.get("diff") or "(no diff)"),
                "```",
                "",
            ]
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path
