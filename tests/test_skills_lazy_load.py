from __future__ import annotations

from pathlib import Path

import pytest

from coderking.config import Settings
from coderking.llm.provider import LLMResponse
from coderking.runtime.loop import AgentRuntime
from coderking_agent_core.types import AgentMessage
from coderking_coding_agent.context.compress import phase_a_compress
from coderking_coding_agent.context.skills import (
    SkillMatcher,
    SkillRegistry,
    activated_skill_names,
    inject_matching_skills,
)


def _write_skill(
    root: Path,
    name: str,
    triggers: list[str],
    *,
    body: str = "Detailed skill instructions.",
) -> None:
    skill_dir = root / ".coderking" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    content = (
        "---\n"
        f"name: {name}\n"
        f'description: "Skill {name}"\n'
        f"triggers: {triggers!r}\n"
        "max_inject_tokens: 2000\n"
        "---\n"
        f"# {name}\n{body}\n"
    )
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")


def test_ten_skills_frontmatter_under_1k_tokens(tmp_path: Path) -> None:
    for index in range(10):
        _write_skill(tmp_path, f"skill-{index}", [f"trigger-{index}"])
    registry = SkillRegistry(tmp_path, include_cursor=False)
    assert len(registry.manifests()) == 10
    assert registry.frontmatter_token_estimate() < 1000


def test_matcher_hits_trigger(tmp_path: Path) -> None:
    _write_skill(tmp_path, "swe-repair", ["pytest", "repair"])
    registry = SkillRegistry(tmp_path, include_cursor=False)
    hits = SkillMatcher(registry).match("please repair failing pytest")
    assert [item.name for item in hits] == ["swe-repair"]


def test_matcher_misses_unrelated_prompt(tmp_path: Path) -> None:
    _write_skill(tmp_path, "swe-repair", ["pytest", "repair"])
    registry = SkillRegistry(tmp_path, include_cursor=False)
    hits = SkillMatcher(registry).match("write documentation for the landing page")
    assert hits == []


def test_inject_once_per_session(tmp_path: Path) -> None:
    _write_skill(tmp_path, "swe-repair", ["pytest"])
    messages = [
        {"role": "system", "content": "core"},
        {"role": "user", "content": "run pytest"},
    ]
    registry = SkillRegistry(tmp_path, include_cursor=False)
    updated, injected = inject_matching_skills(tmp_path, messages, "run pytest", registry=registry)
    assert len(injected) == 1
    again, reinjected = inject_matching_skills(
        tmp_path, updated, "run pytest again", registry=registry
    )
    assert reinjected == []
    assert len(activated_skill_names(again)) == 1


def test_inject_from_recent_tool_context(tmp_path: Path) -> None:
    _write_skill(tmp_path, "swe-repair", ["test failed"])
    messages = [
        {"role": "system", "content": "core"},
        {"role": "user", "content": "fix bug"},
        {"role": "tool", "content": "AssertionError: test failed for add()"},
    ]
    registry = SkillRegistry(tmp_path, include_cursor=False)
    _, injected = inject_matching_skills(
        tmp_path,
        messages,
        "fix bug",
        "AssertionError: test failed for add()",
        registry=registry,
    )
    assert len(injected) == 1
    assert injected[0].manifest.name == "swe-repair"


def test_compression_preserves_active_skills() -> None:
    messages = [
        AgentMessage(role="system", content="core"),
        AgentMessage(
            role="user",
            content='<skill name="swe-repair">\nrepair loop\n</skill>',
            meta={"skill": "swe-repair"},
        ),
        *[AgentMessage(role="user", content=f"turn-{i}") for i in range(30)],
    ]
    compressed, summary = phase_a_compress(messages, keep_recent_messages=5)
    assert "swe-repair" in summary.active_skills
    assert any("active_skills" in (msg.content or "") for msg in compressed)


@pytest.mark.parametrize(
    "prompt",
    [
        "add a login form",
        "refactor the navbar layout",
        "document the rest api",
        "optimize database queries",
        "rename variables for clarity",
    ],
)
def test_low_false_positive_prompts(tmp_path: Path, prompt: str) -> None:
    _write_skill(tmp_path, "swe-repair", ["pytest failed", "repair loop"])
    registry = SkillRegistry(tmp_path, include_cursor=False)
    hits = SkillMatcher(registry).match(prompt)
    assert hits == []


class _CaptureLLM:
    async def complete(self, messages, tools, cancel=None) -> LLMResponse:  # noqa: ANN001, ARG002
        self.messages = list(messages)
        return LLMResponse("done", [])


@pytest.mark.asyncio
async def test_loop_injects_matching_skill(tmp_path: Path) -> None:
    _write_skill(tmp_path, "swe-repair", ["pytest"])
    llm = _CaptureLLM()
    runtime = AgentRuntime(
        Settings(openai_api_key="x", sandbox_mode="local", workspace=tmp_path, max_iterations=1),
        llm,
    )
    events: list[str] = []

    async def on_event(event) -> None:  # noqa: ANN001
        events.append(event.type)

    state = await runtime.run("please run pytest", tmp_path, on_event=on_event, auto_approve=True)
    assert any('<skill name="swe-repair">' in str(m.get("content")) for m in state.messages)
    assert "skill_injected" in events
