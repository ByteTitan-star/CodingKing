"""Live model E2E — skipped unless a real provider API key is configured."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from coderking.evalkit.live import (
    EVAL_TASKS,
    REPO_ROOT,
    copy_eval_repo,
    live_settings,
    require_live_key,
)
from coderking.evalkit.loader import discover_tasks
from coderking.evalkit.runner import run_eval_task, summarize, write_reports
from coderking.llm.openai_compat import OpenAICompatProvider
from coderking.runtime.events import AgentEvent
from coderking.runtime.loop import AgentRuntime
from coderking.runtime.state import TaskStatus

pytestmark = pytest.mark.live


async def _noop_event(_event: AgentEvent) -> None:
    return None


@pytest.mark.asyncio
async def test_live_bugfix_add(tmp_path: Path) -> None:
    require_live_key()
    workspace = copy_eval_repo("bug_fix", "add", tmp_path / "repo")
    settings = live_settings(workspace)
    llm = OpenAICompatProvider(settings)
    events: list[AgentEvent] = []

    async def on_event(event: AgentEvent) -> None:
        events.append(event)

    state = await AgentRuntime(settings, llm).run(
        "Fix add() so it returns the sum of two integers. Do not change tests.",
        workspace,
        on_event=on_event,
        auto_approve=True,
        test_command="python -m pytest -q",
    )
    assert state.status == TaskStatus.SUCCEEDED, state.errors
    assert state.token_input + state.token_output > 0
    assert state.iteration < settings.max_iterations
    calc = (workspace / "calc.py").read_text(encoding="utf-8")
    assert "a + b" in calc or "a+b" in calc
    assert any(e.type == "done" and e.payload.get("ok") for e in events)


@pytest.mark.asyncio
async def test_live_feature_greet(tmp_path: Path) -> None:
    require_live_key()
    workspace = copy_eval_repo("feature_add", "greet", tmp_path / "repo")
    settings = live_settings(workspace)
    task_json = json.loads(
        (EVAL_TASKS / "feature_add" / "greet" / "task.json").read_text(encoding="utf-8")
    )
    llm = OpenAICompatProvider(settings)
    state = await AgentRuntime(settings, llm).run(
        str(task_json["instruction"]),
        workspace,
        on_event=_noop_event,
        auto_approve=True,
        test_command=str(task_json.get("test_command") or "python -m pytest -q"),
    )
    assert state.status == TaskStatus.SUCCEEDED, state.errors
    assert state.token_input + state.token_output > 0


@pytest.mark.asyncio
async def test_live_refactor_area(tmp_path: Path) -> None:
    require_live_key()
    workspace = copy_eval_repo("refactor", "area", tmp_path / "repo")
    settings = live_settings(workspace)
    task_json = json.loads(
        (EVAL_TASKS / "refactor" / "area" / "task.json").read_text(encoding="utf-8")
    )
    llm = OpenAICompatProvider(settings)
    state = await AgentRuntime(settings, llm).run(
        str(task_json["instruction"]),
        workspace,
        on_event=_noop_event,
        auto_approve=True,
        test_command=str(task_json.get("test_command") or "python -m pytest -q"),
    )
    assert state.status == TaskStatus.SUCCEEDED, state.errors
    assert state.token_input + state.token_output > 0


@pytest.mark.asyncio
async def test_live_eval_suite_success_rate(tmp_path: Path) -> None:
    """Run full eval suite with live LLM; require ≥ 2/3 success."""
    require_live_key()
    settings = live_settings(tmp_path)
    llm = OpenAICompatProvider(settings)
    results = []
    for task, task_dir in discover_tasks(EVAL_TASKS):
        results.append(await run_eval_task(task, task_dir, settings, llm))
    summary = summarize(results)
    out = tmp_path / "reports"
    write_reports(
        results,
        out,
        stem="live-e2e",
        extra={
            "llm": {
                "mode": "live",
                "model": settings.model,
                "base_url": settings.openai_base_url,
            },
            "repo_root": str(REPO_ROOT),
        },
    )
    assert summary["task_success_rate"] >= 2 / 3, (summary, [r.error for r in results])
    report = json.loads((out / "live-e2e.json").read_text(encoding="utf-8"))
    assert report["extra"]["llm"]["mode"] == "live"
    assert "scripted" not in str(report["extra"]["llm"]).lower()
