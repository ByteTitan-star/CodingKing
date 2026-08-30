from __future__ import annotations

from pathlib import Path

import pytest

from coderking.config import Settings
from coderking.sandbox.cow import CowWorkspace, clone_workspace
from coderking.sandbox.manager import create_sandbox


def test_cow_isolates_edits_from_source(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("source\n", encoding="utf-8")
    cow = CowWorkspace(tmp_path, session_id="t1")
    work = cow.materialize()
    assert (work / "a.py").read_text(encoding="utf-8") == "source\n"
    (work / "a.py").write_text("overlay\n", encoding="utf-8")
    (work / "b.py").write_text("new\n", encoding="utf-8")
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "source\n"
    assert not (tmp_path / "b.py").exists()
    cow.close()
    assert not cow.base_dir.exists()


@pytest.mark.asyncio
async def test_cow_commit_rollback_and_diff(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("old\n", encoding="utf-8")
    cow = CowWorkspace(tmp_path, session_id="t2")
    work = cow.materialize()
    snap = await cow.commit()
    (work / "a.py").write_text("new\n", encoding="utf-8")
    (work / "b.py").write_text("added\n", encoding="utf-8")
    diff = await cow.diff(snap)
    assert "+new" in diff
    assert "b.py" in diff
    await cow.rollback(snap)
    assert (work / "a.py").read_text(encoding="utf-8") == "old\n"
    assert not (work / "b.py").exists()
    cow.close()


def test_cow_promote_copies_changes_back(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("old\n", encoding="utf-8")
    (tmp_path / "gone.py").write_text("x\n", encoding="utf-8")
    cow = CowWorkspace(tmp_path, session_id="t3")
    work = cow.materialize()
    (work / "a.py").write_text("new\n", encoding="utf-8")
    (work / "b.py").write_text("added\n", encoding="utf-8")
    (work / "gone.py").unlink()
    cow.promote()
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "new\n"
    assert (tmp_path / "b.py").read_text(encoding="utf-8") == "added\n"
    assert not (tmp_path / "gone.py").exists()
    cow.close()


def test_cow_promote_skips_secret_paths(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text("ok\n", encoding="utf-8")
    cow = CowWorkspace(tmp_path, session_id="sec")
    work = cow.materialize()
    (work / "ok.py").write_text("changed\n", encoding="utf-8")
    (work / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (work / "leak.pem").write_text("BEGIN\n", encoding="utf-8")
    cow.promote()
    assert (tmp_path / "ok.py").read_text(encoding="utf-8") == "changed\n"
    assert not (tmp_path / ".env").exists()
    assert not (tmp_path / "leak.pem").exists()
    cow.close()


def test_concurrent_cow_workspaces_are_isolated(tmp_path: Path) -> None:
    (tmp_path / "shared.py").write_text("base\n", encoding="utf-8")
    a = CowWorkspace(tmp_path, session_id="a")
    b = CowWorkspace(tmp_path, session_id="b")
    wa = a.materialize()
    wb = b.materialize()
    (wa / "shared.py").write_text("from-a\n", encoding="utf-8")
    (wb / "shared.py").write_text("from-b\n", encoding="utf-8")
    assert (wa / "shared.py").read_text(encoding="utf-8") == "from-a\n"
    assert (wb / "shared.py").read_text(encoding="utf-8") == "from-b\n"
    assert (tmp_path / "shared.py").read_text(encoding="utf-8") == "base\n"
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_create_sandbox_with_cow_uses_work_path(tmp_path: Path) -> None:
    (tmp_path / "x.py").write_text("1\n", encoding="utf-8")
    cow = CowWorkspace(tmp_path, session_id="sb")
    cow.materialize()
    settings = Settings(sandbox_mode="local", workspace=tmp_path)
    sandbox, note = await create_sandbox(tmp_path, settings, cow=cow)
    assert "+cow" in note
    assert sandbox.workspace == cow.work_path  # type: ignore[attr-defined]
    cow.close()


def test_clone_workspace_skips_coderking_dir(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text("1\n", encoding="utf-8")
    secret = tmp_path / ".coderking" / "memory"
    secret.mkdir(parents=True)
    (secret / "x.db").write_text("secret", encoding="utf-8")
    dest = tmp_path / "clone"
    clone_workspace(tmp_path, dest)
    assert (dest / "ok.py").is_file()
    assert not (dest / ".coderking").exists()


@pytest.mark.asyncio
async def test_runtime_cow_promotes_on_success(tmp_path: Path) -> None:
    from coderking.llm.provider import LLMResponse, ToolCall
    from coderking.runtime.loop import AgentRuntime
    from coderking.runtime.state import TaskStatus

    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (tmp_path / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )

    class ScriptedLLM:
        def __init__(self) -> None:
            self.i = 0
            self.responses = [
                LLMResponse(
                    "",
                    [
                        ToolCall(
                            id="1",
                            name="submit_plan",
                            arguments={"steps": ["fix add", "run tests", "review"]},
                        )
                    ],
                ),
                LLMResponse(
                    "",
                    [
                        ToolCall(
                            id="2",
                            name="write_file",
                            arguments={
                                "path": "calc.py",
                                "content": "def add(a, b):\n    return a + b\n",
                            },
                        )
                    ],
                ),
                LLMResponse("", [ToolCall(id="3", name="submit_for_execution", arguments={})]),
                LLMResponse("", [ToolCall(id="4", name="run_tests", arguments={})]),
                LLMResponse(
                    "",
                    [ToolCall(id="5", name="finish_task", arguments={"summary": "fixed add"})],
                ),
            ]

        async def complete(self, messages, tools, cancel=None) -> LLMResponse:  # noqa: ANN001, ARG002
            item = self.responses[min(self.i, len(self.responses) - 1)]
            self.i += 1
            return item

    settings = Settings(
        openai_api_key="x",
        sandbox_mode="local",
        workspace=tmp_path,
        max_iterations=20,
        sandbox_cow=True,
    )
    events: list = []

    async def on_event(event) -> None:  # noqa: ANN001
        events.append(event)

    state = await AgentRuntime(settings, ScriptedLLM()).run(
        "fix add",
        tmp_path,
        on_event=on_event,
        auto_approve=True,
        test_command="python -m pytest -q",
    )
    assert state.status == TaskStatus.SUCCEEDED
    assert "a + b" in (tmp_path / "calc.py").read_text(encoding="utf-8")
    assert not (tmp_path / ".coderking" / "cow" / state.task_id).exists()
