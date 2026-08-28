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
    pip = await sandbox.run(
        "pip install --disable-pip-version-check -q six==1.16.0 && python -c 'import six; print(six.__version__)'",
        timeout_sec=180,
    )
    assert pip.exit_code == 0, pip.combined
    assert "1.16.0" in pip.combined

    denied = await sandbox.run(
        "python -c \"import urllib.request; urllib.request.urlopen('https://www.google.com', timeout=5)\"",
        timeout_sec=60,
    )
    assert denied.exit_code != 0
    assert sandbox.last_denials  # proxy recorded a denial
