"""Live repair-path eval. Never prints API keys."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

from coderking.config import load_settings
from coderking.evalkit.loader import load_task
from coderking.evalkit.repair_path import run_repair_path, write_repair_report
from coderking.llm.openai_compat import OpenAICompatProvider

ROOT = Path(__file__).resolve().parents[1]


async def main() -> None:
    settings = load_settings(workspace=ROOT, sandbox_mode="local")
    host = settings.openai_base_url.split("://", 1)[-1]
    print(f"model={settings.model} endpoint={host} key_set={bool(settings.openai_api_key)}")
    task, task_dir = load_task(ROOT / "eval" / "repair_path" / "multiply" / "task.json")
    tmp = Path(tempfile.mkdtemp(prefix="coderking-repair-"))
    try:
        dest = tmp / "repo"
        shutil.copytree(task.repo_path(task_dir), dest)
        report = await run_repair_path(task, dest, settings, OpenAICompatProvider(settings))
        json_path, md_path = write_repair_report(report, ROOT / "eval" / "reports")
        print(
            f"success={report['success']} decision={report['reviewer_decision']} "
            f"repair_count={report['repair_count']} iters={report['iterations']} "
            f"tools={report['tool_calls']} tokens={report['tokens']}"
        )
        print(f"wrote {json_path} and {md_path}")
        if not report["success"]:
            raise SystemExit(2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
