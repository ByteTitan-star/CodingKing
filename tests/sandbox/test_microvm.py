"""Micro-VM sandbox backend (#44)."""

from __future__ import annotations

from pathlib import Path

import pytest

from coderking.config import Settings
from coderking.sandbox.manager import create_sandbox
from coderking.sandbox.microvm import (
    FirecrackerProvider,
    MicroVmSandbox,
    MockMicroVmProvider,
    create_microvm_provider,
)


def test_settings_accept_microvm_mode() -> None:
    settings = Settings(sandbox_mode="microvm", sandbox_microvm_provider="mock")
    assert settings.sandbox_mode == "microvm"
    assert settings.sandbox_microvm_provider == "mock"


@pytest.mark.asyncio
async def test_firecracker_provider_raises_phase4b() -> None:
    provider = create_microvm_provider("firecracker")
    assert isinstance(provider, FirecrackerProvider)
    with pytest.raises(NotImplementedError, match="Phase 4b"):
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
