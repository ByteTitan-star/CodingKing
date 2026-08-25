"""Read-only live smoke: scan + one tool call. Never prints secrets."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path

from coderking.config import load_settings
from coderking.llm.openai_compat import OpenAICompatProvider
from coderking.runtime.loop import AgentRuntime
from coderking.runtime.state import TaskStatus

ROOT = Path(__file__).resolve().parents[1]


async def main() -> None:
    settings = load_settings(workspace=ROOT, sandbox_mode="local", max_iterations=12)
    host = settings.openai_base_url.split("://", 1)[-1]
    print(f"model={settings.model} endpoint={host} key_set={bool(settings.openai_api_key)}")
    tmp = Path(tempfile.mkdtemp(prefix="coderking-smoke-"))
    try:
        dest = tmp / "repo"
        dest.mkdir()
        (dest / "README.md").write_text("# smoke\nhello from coderking\n", encoding="utf-8")
        (dest / "app.py").write_text("VALUE = 42\n", encoding="utf-8")
        (dest / "test_smoke.py").write_text("def test_ok() -> None:\n    assert True\n", encoding="utf-8")
        subprocess.run(["git", "init"], cwd=dest, check=True, capture_output=True)
        events: list[str] = []

        async def on_event(event) -> None:  # noqa: ANN001
            if event.type in {"agent_status", "tool_call", "done", "error"}:
                payload = {k: v for k, v in event.payload.items() if k != "arguments"}
                events.append(f"{event.type}:{payload}")

        state = await AgentRuntime(settings, OpenAICompatProvider(settings)).run(
            "Read-only smoke: search the repo, read README.md and app.py, do not write or edit any file, "
            "then run_tests, then finish_task. Goal: prove tool calling works.",
            dest,
            on_event=on_event,
            auto_approve=True,
            test_command="python -c \"print('ok')\"",
        )
        tools = [r.name for r in state.tool_history]
        print(f"status={state.status.value} role={state.role.value} iters={state.iteration}")
        print(f"tools={tools}")
        print(f"changed={state.changed_files}")
        print(f"tokens={state.token_input}+{state.token_output}")
        print("events:")
        for line in events[:30]:
            print(" ", line)
        if state.status == TaskStatus.FAILED:
            raise SystemExit(1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
