from pathlib import Path

from typer.testing import CliRunner

from coderking.cli import app
from coderking.config import load_settings
from coderking.registry import persist_state
from coderking.runtime.state import AgentState, Role, TaskStatus

runner = CliRunner()


def test_cli_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "run" in result.stdout
    assert "serve" in result.stdout
    assert "eval" in result.stdout
    assert "chat" in result.stdout
    assert "stop" in result.stdout
    assert "status" in result.stdout


def test_init_config_status_stop(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CODERKING_MODEL", raising=False)
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
    monkeypatch.delenv("CODERKING_OPENAI_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["eval", "--workspace", str(tmp_path)])
    assert result.exit_code == 1
    assert "CODERKING_OPENAI_API_KEY" in result.stdout
