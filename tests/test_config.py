from pathlib import Path

from coderking.config import Settings, load_settings, write_yaml_config
from coderking.runtime.loop import AgentRuntime
from coderking_coding_agent.runtime.atomic_l1 import AtomicL1Runtime


def test_default_runtime_uses_atomic_l1(tmp_path: Path) -> None:
    class _LLM:
        async def complete(self, messages, tools, cancel=None):  # noqa: ANN001, ARG002
            from coderking.llm.provider import LLMResponse

            return LLMResponse("done", [])

    runtime = AgentRuntime(
        Settings(openai_api_key="x", sandbox_mode="local", workspace=tmp_path),
        _LLM(),
    )
    assert isinstance(runtime._backend, AtomicL1Runtime)


def test_yaml_then_env_then_cli(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    write_yaml_config(
        tmp_path, {"model": "from-yaml", "openai_base_url": "https://yaml.example/v1"}
    )
    monkeypatch.setattr("coderking.config.load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.delenv("CODERKING_MODEL", raising=False)
    monkeypatch.delenv("CODERKING_OPENAI_BASE_URL", raising=False)
    settings = load_settings(workspace=tmp_path)
    assert settings.model == "from-yaml"
    monkeypatch.setenv("CODERKING_MODEL", "from-env")
    settings = load_settings(workspace=tmp_path)
    assert settings.model == "from-env"
    settings = load_settings(workspace=tmp_path, model="from-cli")
    assert settings.model == "from-cli"


def test_config_model_does_not_write_api_key(tmp_path: Path) -> None:
    path = write_yaml_config(tmp_path, {"model": "deepseek-chat", "openai_api_key": "secret"})
    text = path.read_text(encoding="utf-8")
    assert "secret" not in text
    assert "deepseek-chat" in text
