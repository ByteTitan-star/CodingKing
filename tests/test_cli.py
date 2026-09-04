import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from coderking.cli import app
from coderking.config import load_settings
from coderking.registry import persist_state
from coderking.runtime.state import AgentState, Role, TaskStatus

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    """Strip ANSI so Rich-styled help still matches option literals like --test."""
    return _ANSI.sub("", text)


def test_cli_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    out = _plain(result.stdout)
    assert "run" in out
    assert "serve" in out
    assert "eval" in out
    assert "chat" in out
    assert "tui" in out
    assert "stop" in out
    assert "status" in out


def test_run_help_exposes_test_soft_hint() -> None:
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    out = _plain(result.stdout)
    assert "--test" in out
    assert "--extension" not in out
    assert "hint" in out.lower()


@pytest.mark.asyncio
async def test_atomic_run_injects_test_command_into_system_prompt(tmp_path: Path) -> None:
    from coderking.config import Settings
    from coderking.llm.provider import LLMResponse
    from coderking.runtime.loop import AgentRuntime

    class CaptureLLM:
        def __init__(self) -> None:
            self.messages: list = []

        async def complete(self, messages, tools, cancel=None):  # noqa: ANN001, ARG002
            self.messages = list(messages)
            return LLMResponse("done", [])

    llm = CaptureLLM()
    runtime = AgentRuntime(
        Settings(
            openai_api_key="x",
            sandbox_mode="local",
            workspace=tmp_path,
            max_iterations=1,
        ),
        llm,
    )

    async def on_event(_event) -> None:  # noqa: ANN001
        return None

    await runtime.run(
        "fix add",
        tmp_path,
        on_event=on_event,
        auto_approve=True,
        test_command="python -m pytest -q",
    )
    system = str(llm.messages[0]["content"])
    assert "python -m pytest -q" in system
    assert "Preferred verification command" in system


def test_init_config_status_stop(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("coderking.config.load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.delenv("CODERKING_MODEL", raising=False)
    monkeypatch.delenv("CODERKING_OPENAI_BASE_URL", raising=False)
    init = runner.invoke(app, ["init", "--workspace", str(tmp_path)])
    assert init.exit_code == 0
    assert (tmp_path / ".coderking" / "config.yaml").is_file()
    cfg = runner.invoke(
        app,
        [
            "config",
            "model",
            "--workspace",
            str(tmp_path),
            "--model",
            "deepseek-chat",
            "--base-url",
            "https://api.deepseek.com/v1",
        ],
    )
    assert cfg.exit_code == 0
    settings = load_settings(workspace=tmp_path)
    assert settings.model == "deepseek-chat"
    assert "deepseek.com" in settings.openai_base_url
    state = AgentState(task="fix tests", repository=str(tmp_path), task_id="abc123def456")
    state.status = TaskStatus.RUNNING
    state.role = Role.CODING
    state.iteration = 2
    persist_state(tmp_path, state)
    st = runner.invoke(app, ["status", "--workspace", str(tmp_path)])
    assert st.exit_code == 0
    assert "abc123def456" in st.stdout
    assert "fix tests" in st.stdout
    stop = runner.invoke(app, ["stop", "abc123def456", "--workspace", str(tmp_path)])
    assert stop.exit_code == 0
    assert (tmp_path / ".coderking" / "cancels" / "abc123def456").is_file()


def test_eval_requires_api_key(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr("coderking.config.load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.delenv("CODERKING_OPENAI_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["eval", "--workspace", str(tmp_path)])
    assert result.exit_code == 1
    assert "CODERKING_OPENAI_API_KEY" in result.stdout
