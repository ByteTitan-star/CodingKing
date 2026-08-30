"""Micro-VM sandbox backend (#44)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from coderking.config import Settings
from coderking.sandbox.manager import create_sandbox
from coderking.sandbox.microvm import (
    E2B_REMOTE_ROOT,
    E2BProvider,
    E2BSession,
    FirecrackerProvider,
    MicroVmSandbox,
    MockMicroVmProvider,
    create_microvm_provider,
    sync_workspace_to_e2b,
)


def test_settings_accept_microvm_mode() -> None:
    settings = Settings(sandbox_mode="microvm", sandbox_microvm_provider="mock")
    assert settings.sandbox_mode == "microvm"
    assert settings.sandbox_microvm_provider == "mock"


@pytest.mark.asyncio
async def test_firecracker_provider_fails_closed_without_deps() -> None:
    provider = create_microvm_provider("firecracker")
    assert isinstance(provider, FirecrackerProvider)
    assert await provider.available() is False
    with pytest.raises(RuntimeError, match="Firecracker Micro-VM unavailable"):
        await provider.create(Path("."))


def test_create_microvm_provider_e2b_requires_api_key() -> None:
    with pytest.raises(ValueError, match="E2B"):
        create_microvm_provider("e2b", api_key="")


@pytest.mark.asyncio
async def test_manager_selects_microvm(tmp_path: Path) -> None:
    settings = Settings(
        sandbox_mode="microvm",
        sandbox_microvm_provider="mock",
        workspace=tmp_path,
    )
    sandbox, note = await create_sandbox(tmp_path, settings)
    assert isinstance(sandbox, MicroVmSandbox)
    assert "microvm" in note
    await sandbox.close()


def test_sync_workspace_to_e2b_uploads_and_skips_secrets(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hi\n", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.js").write_text("nope\n", encoding="utf-8")

    written: dict[str, bytes] = {}

    class FakeFiles:
        def write(self, path: str, data: bytes | str) -> None:
            written[path] = data if isinstance(data, bytes) else data.encode()

    sandbox = SimpleNamespace(files=FakeFiles())
    count = sync_workspace_to_e2b(sandbox, tmp_path)
    assert count == 2
    assert f"{E2B_REMOTE_ROOT}/hello.txt" in written
    assert written[f"{E2B_REMOTE_ROOT}/hello.txt"].replace(b"\r\n", b"\n") == b"hi\n"
    assert f"{E2B_REMOTE_ROOT}/src/a.py" in written
    assert not any(".env" in p for p in written)
    assert not any("node_modules" in p for p in written)


def test_sync_workspace_to_e2b_fail_closed_on_write_error(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hi\n", encoding="utf-8")

    class BoomFiles:
        def write(self, path: str, data: bytes | str) -> None:
            raise OSError("upload denied")

    with pytest.raises(RuntimeError, match="failed uploading"):
        sync_workspace_to_e2b(SimpleNamespace(files=BoomFiles()), tmp_path)


@pytest.mark.asyncio
async def test_e2b_session_exec_uses_remote_cwd(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    class FakeCommands:
        def run(self, command: str, timeout: int = 0, cwd: str | None = None) -> SimpleNamespace:
            calls.append({"command": command, "timeout": timeout, "cwd": cwd})
            return SimpleNamespace(exit_code=0, stdout="ok\n", stderr="")

    session = E2BSession(
        SimpleNamespace(commands=FakeCommands()),
        tmp_path,
        remote_root=E2B_REMOTE_ROOT,
    )
    result = await session.exec("cat hello.txt", timeout_sec=30)
    assert result.exit_code == 0
    assert result.stdout == "ok\n"
    assert calls[0]["cwd"] == E2B_REMOTE_ROOT
    assert calls[0]["command"] == "cat hello.txt"


@pytest.mark.asyncio
async def test_e2b_provider_create_syncs_then_exposes_files(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("visible\n", encoding="utf-8")
    written: dict[str, bytes] = {}
    killed: list[bool] = []

    class FakeFiles:
        def write(self, path: str, data: bytes | str) -> None:
            written[path] = data if isinstance(data, bytes) else data.encode()

    class FakeCommands:
        def run(self, command: str, timeout: int = 0, cwd: str | None = None) -> SimpleNamespace:
            assert cwd == E2B_REMOTE_ROOT
            path = f"{cwd}/hello.txt"
            body = written.get(path, b"")
            return SimpleNamespace(exit_code=0, stdout=body.decode(), stderr="")

    class FakeSandbox:
        def __init__(self) -> None:
            self.files = FakeFiles()
            self.commands = FakeCommands()

        def kill(self) -> None:
            killed.append(True)

        @classmethod
        def create(cls, **kwargs: object) -> FakeSandbox:
            assert kwargs.get("api_key") == "test-key"
            return cls()

    fake_mod = ModuleType("e2b_code_interpreter")
    fake_mod.Sandbox = FakeSandbox  # type: ignore[attr-defined]
    sys.modules["e2b_code_interpreter"] = fake_mod
    provider = E2BProvider(api_key="test-key")
    try:
        session = await provider.create(tmp_path)
    finally:
        sys.modules.pop("e2b_code_interpreter", None)

    assert f"{E2B_REMOTE_ROOT}/hello.txt" in written
    result = await session.exec("cat hello.txt", timeout_sec=30)
    assert "visible" in result.stdout
    await session.close()
    assert killed


@pytest.mark.asyncio
async def test_e2b_provider_create_fail_closed_kills_sandbox(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("x\n", encoding="utf-8")
    killed: list[bool] = []

    class BoomFiles:
        def write(self, path: str, data: bytes | str) -> None:
            raise OSError("nope")

    class FakeSandbox:
        def __init__(self) -> None:
            self.files = BoomFiles()

        def kill(self) -> None:
            killed.append(True)

        @classmethod
        def create(cls, **kwargs: object) -> FakeSandbox:
            return cls()

    fake_mod = ModuleType("e2b_code_interpreter")
    fake_mod.Sandbox = FakeSandbox  # type: ignore[attr-defined]
    sys.modules["e2b_code_interpreter"] = fake_mod
    provider = E2BProvider(api_key="test-key")
    try:
        with pytest.raises(RuntimeError, match="failed uploading"):
            await provider.create(tmp_path)
    finally:
        sys.modules.pop("e2b_code_interpreter", None)
    assert killed


@pytest.mark.docker
@pytest.mark.asyncio
async def test_mock_microvm_isolates_passwd(tmp_path: Path) -> None:
    """VM must not expose the host /etc/passwd contents."""
    (tmp_path / "hello.txt").write_text("hi\n", encoding="utf-8")
    provider = MockMicroVmProvider(image="python:3.12-slim")
    if not await provider.available():
        pytest.skip("docker unavailable for mock microvm")

    sandbox = MicroVmSandbox(tmp_path, provider=provider)
    host_passwd = Path("/etc/passwd")
    host_text = host_passwd.read_text(encoding="utf-8") if host_passwd.is_file() else ""

    result = await sandbox.run("cat /etc/passwd", timeout_sec=60)
    assert result.exit_code == 0, result.combined
    assert "CoderKing-MicroVM" in result.stdout
    if host_text:
        assert host_text not in result.stdout
    ws = await sandbox.run("cat hello.txt", timeout_sec=60)
    assert "hi" in ws.combined
    await sandbox.close()


@pytest.mark.docker
@pytest.mark.asyncio
async def test_mock_microvm_cold_start_under_5s(tmp_path: Path) -> None:
    provider = MockMicroVmProvider(image="python:3.12-slim")
    if not await provider.available():
        pytest.skip("docker unavailable for mock microvm")
    sandbox = MicroVmSandbox(tmp_path, provider=provider)
    started = await sandbox.ensure_started()
    assert started < 5.0
    await sandbox.close()
