"""Credential isolation: sandbox env/mount must not leak host secrets."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from coderking.sandbox.cow import clone_workspace
from coderking.sandbox.credentials import (
    contains_secret_marker,
    is_secret_path,
    scrub_env,
)
from coderking.sandbox.docker import DockerSandbox, _docker_env_args
from coderking.sandbox.local import LocalProcessSandbox


def test_scrub_env_strips_secret_prefixes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-key-value")
    monkeypatch.setenv("CODERKING_OPENAI_API_KEY", "sk-host-only")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")
    monkeypatch.setenv("PATH", os.environ.get("PATH", "/usr/bin"))
    monkeypatch.setenv("SAFE_CUSTOM", "keep-me")

    cleaned = scrub_env()
    assert "OPENAI_API_KEY" not in cleaned
    assert "CODERKING_OPENAI_API_KEY" not in cleaned
    assert "ANTHROPIC_API_KEY" not in cleaned
    assert cleaned.get("SAFE_CUSTOM") == "keep-me"
    assert "PATH" in cleaned
    assert not any(contains_secret_marker(v) for v in cleaned.values())


def test_scrub_env_empty_source_stays_minimal() -> None:
    cleaned = scrub_env({}, allowlist_only=True)
    assert "OPENAI_API_KEY" not in cleaned
    assert cleaned.get("PYTHONIOENCODING") == "utf-8"


def test_secret_path_patterns() -> None:
    assert is_secret_path(".env")
    assert is_secret_path(".env.local")
    assert is_secret_path("aws_credentials.json")
    assert is_secret_path(".git/config")
    assert is_secret_path(".coderking")
    assert is_secret_path("certs/server.pem")
    assert not is_secret_path("src/main.py")
    assert not is_secret_path("README.md")


def test_clone_workspace_excludes_secrets(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "ok.py").write_text("print(1)\n", encoding="utf-8")
    (src / ".env").write_text("OPENAI_API_KEY=sk-leak-me\n", encoding="utf-8")
    (src / "my_credentials.txt").write_text("secret\n", encoding="utf-8")
    (src / "server.pem").write_text("-----BEGIN-----\n", encoding="utf-8")
    git = src / ".git"
    git.mkdir()
    (git / "config").write_text("[core]\n", encoding="utf-8")
    coderking = src / ".coderking"
    coderking.mkdir()
    (coderking / "policy.yaml").write_text("rules: []\n", encoding="utf-8")

    dest = tmp_path / "dest"
    clone_workspace(src, dest)

    assert (dest / "ok.py").is_file()
    assert not (dest / ".env").exists()
    assert not (dest / "my_credentials.txt").exists()
    assert not (dest / "server.pem").exists()
    assert not (dest / ".git").exists()  # SKIP_DIRS
    assert not (dest / ".coderking").exists()


def test_docker_env_args_never_include_host_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-appear")
    monkeypatch.setenv("CODERKING_OPENAI_API_KEY", "sk-host")
    args = _docker_env_args()
    joined = " ".join(args)
    assert "CODERKING_SANDBOX=1" in joined
    assert "sk-should-not-appear" not in joined
    assert "OPENAI_API_KEY" not in joined
    assert "CODERKING_OPENAI_API_KEY" not in joined


def test_docker_build_args_use_scrubbed_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-docker-leak")
    sandbox = DockerSandbox(
        tmp_path,
        image="python:3.12-slim",
        memory_mb=256,
        cpus=0.5,
        network=False,
    )
    args = sandbox.build_args("printenv", "coderking-cred-test")
    assert "--env" in args
    assert "CODERKING_SANDBOX=1" in args
    assert not any("sk-docker-leak" in a for a in args)
    assert not any(a.startswith("OPENAI_API_KEY=") for a in args)


@pytest.mark.asyncio
async def test_local_sandbox_printenv_has_no_api_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local-must-not-leak")
    monkeypatch.setenv("CODERKING_OPENAI_API_KEY", "sk-ck-must-not-leak")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-must-not-leak")
    sandbox = LocalProcessSandbox(tmp_path)
    # Cross-platform: print selected vars; missing vars print empty / error.
    result = await sandbox.run(
        "python -c \"import os; print(os.environ.get('OPENAI_API_KEY','')); "
        "print(os.environ.get('CODERKING_OPENAI_API_KEY','')); "
        "print(os.environ.get('ANTHROPIC_API_KEY','')); "
        "print('MARKER_OK')\"",
        timeout_sec=30,
    )
    assert result.exit_code == 0
    assert "MARKER_OK" in result.stdout
    assert "sk-local-must-not-leak" not in result.combined
    assert "sk-ck-must-not-leak" not in result.combined
    assert "sk-ant-must-not-leak" not in result.combined
    assert not contains_secret_marker(result.combined)
