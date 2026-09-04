from pathlib import Path

import pytest
import yaml

from coderking.config import Settings
from coderking.llm.provider import LLMResponse, ToolCall
from coderking.runtime.loop import AgentRuntime
from coderking.runtime.state import AgentState, Role
from coderking_coding_agent.safety.policy import (
    PolicyAction,
    PolicyEngine,
    policy_yaml_path,
)


def test_default_policy_denies_dangerous_bash() -> None:
    engine = PolicyEngine.load(Path("/nonexistent"))
    decision = engine.evaluate("bash", {"command": "rm -rf /"})
    assert decision.action == PolicyAction.DENY


def test_default_policy_asks_git_push() -> None:
    engine = PolicyEngine.load(Path("/nonexistent"))
    decision = engine.evaluate("bash", {"command": "git push origin main"})
    assert decision.action == PolicyAction.ASK


def test_default_policy_denies_env_write() -> None:
    engine = PolicyEngine.load(Path("/nonexistent"))
    decision = engine.evaluate("write_file", {"path": ".env", "content": "x=1"})
    assert decision.action == PolicyAction.DENY


def test_default_policy_denies_shell_secret_path_write() -> None:
    engine = PolicyEngine.load(Path("/nonexistent"))
    for tool in ("bash", "shell"):
        tee = engine.evaluate(tool, {"command": "echo SECRET=1 > .env"})
        assert tee.action == PolicyAction.DENY, tool
        cat = engine.evaluate(tool, {"command": "cat secrets/prod.pem"})
        assert cat.action == PolicyAction.DENY, tool
        echo = engine.evaluate(tool, {"command": "echo hello"})
        assert echo.action == PolicyAction.ALLOW, tool


def test_custom_policy_merged_from_workspace(tmp_path: Path) -> None:
    policy_dir = tmp_path / ".coderking"
    policy_dir.mkdir()
    (policy_dir / "policy.yaml").write_text(
        yaml.safe_dump(
            {
                "tools": {
                    "bash": {
                        "ask_patterns": ["curl"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    engine = PolicyEngine.load(tmp_path)
    decision = engine.evaluate("bash", {"command": "curl https://example.com"})
    assert decision.action == PolicyAction.ASK
    assert decision.rule == "curl"


def test_workspace_policy_cannot_weaken_hitl_floor(tmp_path: Path) -> None:
    policy_dir = tmp_path / ".coderking"
    policy_dir.mkdir()
    (policy_dir / "policy.yaml").write_text(
        yaml.safe_dump(
            {
                "tools": {
                    "delete_file": {"default_action": "allow"},
                    "git_commit": {"default_action": "allow"},
                    "mcp_*": {"default_action": "allow"},
                }
            }
        ),
        encoding="utf-8",
    )
    engine = PolicyEngine.load(tmp_path)
    assert engine.evaluate("delete_file", {"path": "a.txt"}).action == PolicyAction.ASK
    assert engine.evaluate("git_commit", {"message": "x"}).action == PolicyAction.ASK
    assert engine.evaluate("mcp_demo_tool", {}).action == PolicyAction.ASK


class ScriptedLLM:
    def __init__(self, responses: list[LLMResponse]):
        self.responses = responses
        self.i = 0

    async def complete(self, messages, tools, cancel=None) -> LLMResponse:  # noqa: ANN001, ARG002
        item = self.responses[min(self.i, len(self.responses) - 1)]
        self.i += 1
        return item


def _settings(workspace: Path, **kwargs: object) -> Settings:
    data = {
        "openai_api_key": "x",
        "sandbox_mode": "local",
        "workspace": workspace,
        "max_iterations": 20,
    }
    data.update(kwargs)
    return Settings(**data)


@pytest.mark.asyncio
async def test_loop_emits_policy_decision_and_denies(tmp_path: Path) -> None:
    llm = ScriptedLLM(
        [
            LLMResponse("", [ToolCall(id="1", name="bash", arguments={"command": "rm -rf /"})]),
            LLMResponse("", []),
        ]
    )
    events: list = []

    async def on_event(event) -> None:  # noqa: ANN001
        events.append(event)

    runtime = AgentRuntime(_settings(tmp_path), llm)
    state = AgentState(task="test", repository=str(tmp_path), task_id="t1", role=Role.CODING)
    await runtime.run("run", tmp_path, on_event=on_event, auto_approve=True, state=state)
    policy_events = [e for e in events if e.type == "policy_decision"]
    assert policy_events
    assert policy_events[0].payload["action"] == "deny"
    assert any(
        e.type == "tool_call" and e.payload.get("status") in {"denied", "error"} for e in events
    )


@pytest.mark.asyncio
async def test_loop_approval_when_policy_asks(tmp_path: Path) -> None:
    llm = ScriptedLLM(
        [
            LLMResponse(
                "",
                [ToolCall(id="1", name="bash", arguments={"command": "git push origin main"})],
            ),
            LLMResponse("", []),
        ]
    )
    events: list = []

    async def on_event(event) -> None:  # noqa: ANN001
        events.append(event)

    async def approve(tool: str, reason: str, arguments: dict) -> bool:  # noqa: ARG001
        return False

    runtime = AgentRuntime(_settings(tmp_path), llm)
    state = AgentState(task="test", repository=str(tmp_path), task_id="t2", role=Role.CODING)
    await runtime.run(
        "push",
        tmp_path,
        on_event=on_event,
        auto_approve=False,
        approve=approve,
        state=state,
    )
    assert any(e.type == "policy_decision" and e.payload["action"] == "ask" for e in events)
    assert any(e.type == "approval_required" for e in events)

def test_init_creates_policy_template(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    from typer.testing import CliRunner

    from coderking.cli import app

    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["init", "--workspace", str(tmp_path)])
    assert result.exit_code == 0
    assert policy_yaml_path(tmp_path).is_file()
