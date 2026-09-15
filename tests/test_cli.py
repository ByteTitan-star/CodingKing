import json
import re
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from coderking.cli import app
from coderking.config import load_settings
from coderking.registry import current_session_id, load_session, persist_state, save_session
from coderking.runtime.checkpoints import CheckpointStore
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
    assert "skills" in out
    assert "tasks" in out
    assert "tools" in out
    assert "mcp" in out
    assert "retry" in out
    assert "checkpoint" in out


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
    stopped = runner.invoke(app, ["status", "abc123def456", "--workspace", str(tmp_path)])
    assert "cancelling" in stopped.stdout


def test_eval_requires_api_key(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr("coderking.config.load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.delenv("CODERKING_OPENAI_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["eval", "--workspace", str(tmp_path)])
    assert result.exit_code == 1
    assert "CODERKING_OPENAI_API_KEY" in result.stdout


def test_skills_list_and_show(tmp_path: Path) -> None:
    skill_dir = tmp_path / ".coderking" / "skills" / "review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review code\ntriggers: [review]\n---\n"
        "# Steps\nBe precise.\n",
        encoding="utf-8",
    )
    listed = runner.invoke(app, ["skills", "list", "--workspace", str(tmp_path)])
    assert listed.exit_code == 0
    assert "review" in listed.stdout
    shown = runner.invoke(app, ["skills", "show", "review", "--workspace", str(tmp_path)])
    assert shown.exit_code == 0
    assert "Be precise" in shown.stdout


def test_tasks_lists_persisted_records(tmp_path: Path) -> None:
    first = AgentState(task="first", repository=str(tmp_path), task_id="task-first")
    first.status = TaskStatus.SUCCEEDED
    persist_state(tmp_path, first)
    second = AgentState(task="second", repository=str(tmp_path), task_id="task-second")
    second.status = TaskStatus.FAILED
    persist_state(tmp_path, second)

    result = runner.invoke(app, ["tasks", "--workspace", str(tmp_path)])
    assert result.exit_code == 0
    assert "task-first" in result.stdout
    assert "task-second" in result.stdout

    filtered = runner.invoke(
        app,
        ["tasks", "--status", "failed", "--workspace", str(tmp_path)],
    )
    assert filtered.exit_code == 0
    assert "task-second" in filtered.stdout
    assert "task-first" not in filtered.stdout

    rebuilt = runner.invoke(
        app,
        ["tasks", "--rebuild-index", "--workspace", str(tmp_path)],
    )
    assert rebuilt.exit_code == 0
    assert "rebuilt task index from 2 record(s)" in rebuilt.stdout


def test_retry_rejects_successful_persisted_task(tmp_path: Path) -> None:
    state = AgentState(task="done", repository=str(tmp_path), task_id="successful-task")
    state.status = TaskStatus.SUCCEEDED
    persist_state(tmp_path, state)

    result = runner.invoke(app, ["retry", state.task_id, "--workspace", str(tmp_path)])

    assert result.exit_code == 1
    assert "only failed or interrupted" in result.stdout


def test_checkpoint_list_and_rollback_commands(tmp_path: Path) -> None:
    state = AgentState(task="edit", repository=str(tmp_path), task_id="checkpoint-task")
    state.status = TaskStatus.SUCCEEDED
    target = tmp_path / "a.txt"
    target.write_text("before", encoding="utf-8")
    store = CheckpointStore(tmp_path, tmp_path, state.task_id)
    prepared = store.prepare(
        turn_id="turn_a",
        tool_call_id=None,
        tool="edit",
        arguments={"path": "a.txt"},
    )
    assert prepared is not None
    target.write_text("after", encoding="utf-8")
    store.complete(prepared.checkpoint_id, ok=True)
    state.checkpoint_count = 1
    state.latest_checkpoint_id = prepared.checkpoint_id
    persist_state(tmp_path, state)

    listed = runner.invoke(
        app,
        ["checkpoint", "list", state.task_id, "--workspace", str(tmp_path)],
    )
    assert listed.exit_code == 0
    assert prepared.checkpoint_id in listed.stdout
    rolled = runner.invoke(
        app,
        [
            "checkpoint",
            "rollback",
            prepared.checkpoint_id,
            "--task",
            state.task_id,
            "--workspace",
            str(tmp_path),
            "--yes",
        ],
    )
    assert rolled.exit_code == 0
    assert target.read_text(encoding="utf-8") == "before"


def test_tools_list_and_check_dynamic_manifest(tmp_path: Path) -> None:
    tool_dir = tmp_path / ".coderking" / "tools" / "demo"
    tool_dir.mkdir(parents=True)
    (tool_dir / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (tool_dir / "tool.yaml").write_text(
        "name: demo\n"
        "description: demo tool\n"
        "entry: main.py\n"
        "parameters:\n  type: object\n  properties: {}\n",
        encoding="utf-8",
    )

    listed = runner.invoke(app, ["tools", "list", "--workspace", str(tmp_path)])
    assert listed.exit_code == 0
    assert "demo" in listed.stdout
    assert "disabled" in listed.stdout
    checked = runner.invoke(app, ["tools", "check", "--workspace", str(tmp_path)])
    assert checked.exit_code == 0
    assert "1 dynamic tool(s) valid" in checked.stdout


def test_mcp_list_and_check_mock_server(tmp_path: Path) -> None:
    config_dir = tmp_path / ".coderking"
    config_dir.mkdir()
    (config_dir / "mcp.json").write_text(
        json.dumps(
            {
                "allowlist": ["demo"],
                "mcpServers": {
                    "demo": {
                        "command": sys.executable,
                        "args": ["-m", "coderking.mcp.mock_server"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    listed = runner.invoke(app, ["mcp", "list", "--workspace", str(tmp_path)])
    assert listed.exit_code == 0
    assert "demo" in listed.stdout
    checked = runner.invoke(app, ["mcp", "check", "--workspace", str(tmp_path)])
    assert checked.exit_code == 0
    assert "mcp_demo_echo" in checked.stdout


def test_prepare_run_state_separates_task_from_session_context(tmp_path: Path) -> None:
    from coderking.cli import _prepare_run_state

    previous = AgentState(
        task="first",
        repository=str(tmp_path),
        task_id="old-task",
        session_id="session-1",
        messages=[{"role": "user", "content": "first"}],
        changed_files=["old.py"],
    )

    current = _prepare_run_state(
        "second",
        tmp_path,
        previous,
        session_id="session-1",
    )

    assert current.task_id != previous.task_id
    assert current.session_id == "session-1"
    assert current.messages == previous.messages
    assert current.changed_files == []
    assert current.snapshot == {}


def test_session_tree_and_fork_commands(tmp_path: Path) -> None:
    payload = {
        "task_id": "source-task",
        "session_id": "source-session",
        "prompt": "source prompt",
        "status": "succeeded",
        "messages": [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ],
    }
    save_session(tmp_path, payload, session_id="source-session")

    tree = runner.invoke(
        app,
        ["session", "tree", "source-session", "--workspace", str(tmp_path)],
    )
    assert tree.exit_code == 0
    assert "message" in tree.stdout
    assert "source prompt" in tree.stdout

    forked = runner.invoke(
        app,
        [
            "session",
            "fork",
            "--from",
            "source-session",
            "--name",
            "forked-session",
            "--workspace",
            str(tmp_path),
        ],
    )
    assert forked.exit_code == 0
    assert current_session_id(tmp_path) == "forked-session"
    assert load_session(tmp_path, "forked-session")["messages"] == payload["messages"]


def test_session_tree_does_not_create_missing_session(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["session", "tree", "missing", "--workspace", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert "does not exist" in result.stdout
    assert not (tmp_path / ".coderking" / "sessions" / "missing.jsonl").exists()
