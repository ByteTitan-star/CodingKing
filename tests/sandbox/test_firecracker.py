"""Firecracker Micro-VM provider (Phase 4b) unit tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from coderking.sandbox.microvm import (
    FIRECRACKER_REMOTE_ROOT,
    FirecrackerConfig,
    FirecrackerProvider,
    FirecrackerSession,
    configure_and_start_vm,
    firecracker_missing_deps,
)


def _cfg(tmp_path: Path, **overrides: object) -> FirecrackerConfig:
    kernel = tmp_path / "vmlinux"
    rootfs = tmp_path / "rootfs.ext4"
    kernel.write_bytes(b"k")
    rootfs.write_bytes(b"r")
    base = {
        "kernel": kernel,
        "rootfs": rootfs,
        "binary": str(tmp_path / "firecracker"),
        "ssh_host": "127.0.0.1",
        "ssh_port": 2222,
        "ssh_user": "root",
        "ssh_key": None,
        "memory_mb": 256,
        "vcpus": 1,
    }
    base.update(overrides)
    return FirecrackerConfig(**base)  # type: ignore[arg-type]


def test_firecracker_missing_deps_reports_kernel_rootfs(tmp_path: Path) -> None:
    cfg = FirecrackerConfig(
        kernel=tmp_path / "missing-kernel",
        rootfs=tmp_path / "missing-rootfs",
        binary="firecracker-not-installed-xyz",
    )
    missing = firecracker_missing_deps(cfg)
    assert any("KERNEL" in m for m in missing)
    assert any("ROOTFS" in m for m in missing)


def test_configure_and_start_vm_issues_api_puts(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    sock = tmp_path / "fc.sock"
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_put(socket_path: Path, path: str, body: dict[str, object]) -> None:
        assert socket_path == sock
        calls.append((path, body))

    with patch(
        "coderking_coding_agent.sandbox.firecracker._api_put",
        side_effect=fake_put,
    ):
        configure_and_start_vm(sock, cfg)

    paths = [p for p, _ in calls]
    assert paths == ["/machine-config", "/boot-source", "/drives/rootfs", "/actions"]
    assert calls[0][1]["mem_size_mib"] == 256
    assert calls[-1][1]["action_type"] == "InstanceStart"
    assert json.dumps(calls[1][1])  # serializable


@pytest.mark.asyncio
async def test_firecracker_session_exec_uses_ssh_cwd(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    recorded: list[list[str]] = []

    def fake_run(argv, **kwargs):  # noqa: ANN001
        recorded.append(list(argv))
        return MagicMock(returncode=0, stdout="ok\n", stderr="")

    session = FirecrackerSession(
        proc=MagicMock(returncode=0),
        socket_path=tmp_path / "x.sock",
        work_dir=tmp_path / "work",
        workspace=tmp_path,
        config=cfg,
    )
    with patch("coderking_coding_agent.sandbox.firecracker.subprocess.run", side_effect=fake_run):
        result = await session.exec("echo hi", timeout_sec=10)
    assert result.exit_code == 0
    assert "ok" in result.stdout
    assert recorded
    assert recorded[0][0] == "ssh"
    assert any(f"cd {FIRECRACKER_REMOTE_ROOT} && echo hi" in part for part in recorded[0])


@pytest.mark.asyncio
async def test_firecracker_provider_create_fail_closed(tmp_path: Path) -> None:
    provider = FirecrackerProvider(config=_cfg(tmp_path))
    with pytest.raises(RuntimeError, match="unavailable"):
        await provider.create(tmp_path)
