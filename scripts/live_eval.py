"""Live eval runner. Does not print API keys."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from coderking.config import load_settings
from coderking.evalkit.loader import discover_tasks
from coderking.evalkit.runner import run_eval_task, write_reports
from coderking.llm.openai_compat import OpenAICompatProvider

ROOT = Path(__file__).resolve().parents[1]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", default="")
    parser.add_argument("--task-id", default="")
    parser.add_argument("--stem", default="latest")
    parser.add_argument("--report-dir", default="eval/reports")
    args = parser.parse_args()

    settings = load_settings(workspace=ROOT, sandbox_mode="local")
    host = settings.openai_base_url.split("://", 1)[-1]
    print(f"model={settings.model} endpoint={host} key_set={bool(settings.openai_api_key)}")
    llm = OpenAICompatProvider(settings)
    selected = []
    for task, task_dir in discover_tasks(ROOT / "eval" / "tasks"):
        if args.category and task.category != args.category:
            continue
        if args.task_id and task.task_id != args.task_id:
            continue
        selected.append((task, task_dir))
    if not selected:
        raise SystemExit("no tasks selected")
    results = []
    for task, task_dir in selected:
        print(f"running {task.task_id} ({task.category}) ...")
        row = await run_eval_task(task, task_dir, settings, llm)
        print(
            f"  success={row.success} tests={row.test_pass} "
            f"iters={row.iterations} repair={row.repair_count} "
            f"tools={row.tool_calls} files={row.changed_files} "
            f"tokens={row.prompt_tokens}+{row.completion_tokens} "
            f"error={row.error!r}"
        )
        results.append(row)
    extra = {
        "llm": "live openai-compatible",
        "model": settings.model,
        "endpoint_host": host,
        "sandbox_mode": settings.sandbox_mode,
        "scripted": False,
    }
    json_path, md_path = write_reports(
        results, ROOT / args.report_dir, stem=args.stem, extra=extra
    )
    print(f"wrote {json_path} and {md_path}")
    if not all(r.success and r.test_pass for r in results):
        raise SystemExit(2)


if __name__ == "__main__":
    asyncio.run(main())
