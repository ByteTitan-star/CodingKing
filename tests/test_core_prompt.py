from __future__ import annotations

from pathlib import Path

import pytest

from coderking.config import Settings
from coderking.llm.provider import LLMResponse
from coderking.prompts.loader import (
    CORE_TOKEN_BUDGET,
    append_verification_hint,
    estimate_text_tokens,
    load_core_prompt,
    resolve_system_prompt,
)
from coderking.runtime.loop import AgentRuntime


def test_core_prompt_under_token_budget() -> None:
    prompt = load_core_prompt()
    assert prompt
    assert "read" in prompt
    assert "bash" in prompt
    assert "Verification" in prompt
    assert estimate_text_tokens(prompt) < CORE_TOKEN_BUDGET


def test_resolve_system_prompt_is_core() -> None:
    prompt = resolve_system_prompt(Settings())
    assert prompt == load_core_prompt()


def test_atomic_prompt_appends_preferred_test_command() -> None:
    base = load_core_prompt()
    hinted = resolve_system_prompt(Settings(), test_command="python -m pytest -q")
    assert hinted.startswith(base)
    assert "python -m pytest -q" in hinted
    assert append_verification_hint(base, None) == base


class _CaptureLLM:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def complete(self, messages, tools, cancel=None) -> LLMResponse:  # noqa: ANN001, ARG002
        self.messages = list(messages)
        return LLMResponse("done", [])


@pytest.mark.asyncio
async def test_loop_does_not_inject_repository_summary(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("x" * 5000, encoding="utf-8")
    (tmp_path / "module.py").write_text("value = 1\n", encoding="utf-8")
    llm = _CaptureLLM()
    runtime = AgentRuntime(
        Settings(openai_api_key="x", sandbox_mode="local", workspace=tmp_path, max_iterations=1),
        llm,
    )

    async def on_event(_event) -> None:  # noqa: ANN001
        return None

    state = await runtime.run("inspect repo", tmp_path, on_event=on_event, auto_approve=True)
    system = state.messages[0]["content"]
    assert "Repository summary" not in system
    assert "README excerpt" not in system
    assert "BM25 hits" not in system
    assert len(system) < 2000
