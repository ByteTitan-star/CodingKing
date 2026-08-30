"""Docker-marked integration for restricted network allowlist."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from coderking.sandbox.docker import DockerSandbox, docker_available
from coderking.sandbox.network import NetworkPolicy


@pytest.mark.docker
@pytest.mark.asyncio
async def test_restricted_allows_pypi_denies_google(tmp_path: Path) -> None:
    if shutil.which("docker") is None or not await docker_available():
        pytest.skip("docker unavailable")

    sandbox = DockerSandbox(
        tmp_path,
        image="python:3.12-slim",
        memory_mb=512,
        cpus=1.0,
        network_policy=NetworkPolicy(
            mode="restricted",
            allow_hosts=("pypi.org", "files.pythonhosted.org", "pypi.python.org"),
        ),
    )
    # pip should succeed via allowlisted hosts (uses HTTPS_PROXY).
    pip_cmd = (
        "pip install --disable-pip-version-check -q six==1.16.0 && "
        "python -c 'import six; print(six.__version__)'"
    )
    pip = await sandbox.run(pip_cmd, timeout_sec=180)
    assert pip.exit_code == 0, pip.combined
    assert "1.16.0" in pip.combined

    deny_cmd = (
        'python -c "import urllib.request; '
        "urllib.request.urlopen('https://www.google.com', timeout=5)\""
    )
    denied = await sandbox.run(deny_cmd, timeout_sec=60)
    assert denied.exit_code != 0
    assert sandbox.last_denials  # proxy recorded a denial
    # Hard isolation attaches the no-masquerade bridge when Docker supports it.
    if sandbox.policy.docker_network:
        assert "--network" in sandbox.last_args
        assert sandbox.policy.docker_network in sandbox.last_args


@pytest.mark.docker
@pytest.mark.asyncio
async def test_restricted_blocks_raw_ip_when_hard_network(tmp_path: Path) -> None:
    """Raw IP egress must fail on the no-masquerade restricted bridge."""
    if shutil.which("docker") is None or not await docker_available():
        pytest.skip("docker unavailable")

    sandbox = DockerSandbox(
        tmp_path,
        image="python:3.12-slim",
        memory_mb=256,
        cpus=0.5,
        network_policy=NetworkPolicy(mode="restricted", allow_hosts=("example.com",)),
    )
    # Probe without proxy-aware stack: connect to a public IP directly.
    probe = (
        "python -c \"import socket; "
        "s=socket.create_connection(('1.1.1.1', 443), timeout=3)\""
    )
    result = await sandbox.run(probe, timeout_sec=60)
    if not sandbox.policy.docker_network:
        pytest.skip("restricted no-masquerade network unavailable; best-effort fallback")
    assert result.exit_code != 0, result.combined
    assert sandbox.policy.docker_network in sandbox.last_args
