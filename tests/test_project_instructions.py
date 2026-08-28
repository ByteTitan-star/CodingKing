from __future__ import annotations

from pathlib import Path

import pytest

from coderking.config import Settings
from coderking.llm.provider import LLMResponse
from coderking.runtime.loop import AgentRuntime
from coderking_coding_agent.context.project_docs import (
    MAX_BYTES,
    ProjectInstructionsLoader,
    inject_project_instructions,
)


def test_loader_prefers_agents_md(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("from agents\n", encoding="utf-8")
    (tmp_path / "SYSTEM.md").write_text("from system\n", encoding="utf-8")
    doc = ProjectInstructionsLoader(tmp_path).load()
    assert doc is not None
    assert doc.source == "AGENTS.md"
    assert "from agents" in doc.content


def test_loader_falls_back_to_system_md(tmp_path: Path) -> None:
    (tmp_path / "SYSTEM.md").write_text("system rules\n", encoding="utf-8")
    doc = ProjectInstructionsLoader(tmp_path).load()
    assert doc is not None
    assert doc.source == "SYSTEM.md"


def test_loader_falls_back_to_coderking_agents(tmp_path: Path) -> None:
    (tmp_path / ".coderking").mkdir()
    (tmp_path / ".coderking" / "AGENTS.md").write_text("nested rules\n", encoding="utf-8")
    doc = ProjectInstructionsLoader(tmp_path).load()
    assert doc is not None
    assert doc.source == ".coderking/AGENTS.md"


def test_loader_truncates_at_8kb(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_bytes(b"x" * (MAX_BYTES + 500))
    doc = ProjectInstructionsLoader(tmp_path).load()
    assert doc is not None
    assert doc.truncated is True
    assert len(doc.content.encode("utf-8")) <= MAX_BYTES


def test_loader_caches_unchanged_file(tmp_path: Path) -> None:
    path = tmp_path / "AGENTS.md"
    path.write_text("stable content", encoding="utf-8")
    loader = ProjectInstructionsLoader(tmp_path)
    first = loader.load()
    second = loader.load()
    assert first is not None and second is not None
    assert first.content_hash == second.content_hash
    assert first.content == second.content


def test_loader_reloads_when_file_size_changes(tmp_path: Path) -> None:
    path = tmp_path / "AGENTS.md"
    path.write_text("short", encoding="utf-8")
    loader = ProjectInstructionsLoader(tmp_path)
    first = loader.load()
    path.write_text("much longer content", encoding="utf-8")
    second = loader.load()
    assert first is not None and second is not None
    assert first.content == "short"
    assert second.content == "much longer content"


def test_inject_inserts_after_system_prompt() -> None:
    messages = [
        {"role": "system", "content": "core"},
        {"role": "user", "content": "task"},
    ]
    updated, doc = inject_project_instructions(
        Path("."),
        messages,
        loader=_StubLoader("AGENTS.md", "use pytest"),
    )
    assert doc is not None
    assert updated[0]["role"] == "system"
    assert "<project_instructions" in updated[1]["content"]
    assert updated[2]["content"] == "task"


def test_inject_skips_when_already_present() -> None:
    messages = [
        {"role": "system", "content": "core"},
        {
            "role": "user",
            "content": '<project_instructions source="AGENTS.md">x</project_instructions>',
        },
        {"role": "user", "content": "task"},
    ]
    updated, doc = inject_project_instructions(
        Path("."),
        messages,
        loader=_StubLoader("AGENTS.md", "ignored"),
    )
    assert doc is None
    assert updated == messages


class _StubLoader:
    def __init__(self, source: str, content: str) -> None:
        self.source = source
        self.content = content

    def load(self):
        from coderking_coding_agent.context.project_docs import ProjectInstructions

        return ProjectInstructions(
            source=self.source,
            content=self.content,
            truncated=False,
            content_hash="abc123",
        )


class _CaptureLLM:
    async def complete(self, messages, tools, cancel=None) -> LLMResponse:  # noqa: ANN001, ARG002
        self.messages = list(messages)
        return LLMResponse("done", [])


@pytest.mark.asyncio
async def test_loop_injects_project_instructions_once(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("Always run pytest before finishing.\n", encoding="utf-8")
    llm = _CaptureLLM()
    runtime = AgentRuntime(
        Settings(openai_api_key="x", sandbox_mode="local", workspace=tmp_path, max_iterations=1),
        llm,
    )
    events: list[str] = []

    async def on_event(event) -> None:  # noqa: ANN001
        events.append(event.type)

    state = await runtime.run("fix bug", tmp_path, on_event=on_event, auto_approve=True)
    assert any("<project_instructions" in str(m.get("content")) for m in state.messages)
    assert "project_instructions" in events
    assert llm.messages[1]["content"].startswith("<project_instructions")


@pytest.mark.asyncio
async def test_loop_without_agents_md_has_no_injection(tmp_path: Path) -> None:
    llm = _CaptureLLM()
    runtime = AgentRuntime(
        Settings(openai_api_key="x", sandbox_mode="local", workspace=tmp_path, max_iterations=1),
        llm,
    )

    async def on_event(_event) -> None:  # noqa: ANN001
        return None

    state = await runtime.run("fix bug", tmp_path, on_event=on_event, auto_approve=True)
    assert all("<project_instructions" not in str(m.get("content")) for m in state.messages)
