import shutil
from pathlib import Path

import pytest

from coderking.config import Settings
from coderking.sandbox.docker import DockerSandbox, docker_available
from coderking.workspace import ensure_inside


def test_docker_args_include_limits_and_network() -> None:
    sandbox = DockerSandbox(
        Path("."),
        image="python:3.12-slim",
        memory_mb=256,
        cpus=0.5,
        network=False,
    )
    args = sandbox.build_args("echo hello", "coderking-flag-test")
    assert "--network" in args and "none" in args
    assert "--memory" in args and "256m" in args
    assert "--cpus" in args and "0.5" in args


@pytest.mark.docker
@pytest.mark.asyncio
async def test_docker_echo_mount_network_timeout(tmp_path: Path) -> None:
    if shutil.which("docker") is None or not await docker_available():
        pytest.skip("docker unavailable")
    (tmp_path / "marker.txt").write_text("mounted", encoding="utf-8")
    sandbox = DockerSandbox(
        tmp_path,
        image="python:3.12-slim",
        memory_mb=256,
        cpus=1.0,
        network=False,
    )
    hello = await sandbox.run("echo hello", timeout_sec=60)
    assert hello.exit_code == 0
    assert "hello" in hello.combined
    mounted = await sandbox.run("cat marker.txt", timeout_sec=60)
    assert "mounted" in mounted.combined
    with pytest.raises(PermissionError):
        ensure_inside(tmp_path, Path("../outside.txt"))
    net = await sandbox.run(
        "python -c \"import urllib.request; urllib.request.urlopen('https://1.1.1.1', timeout=3)\"",
        timeout_sec=30,
    )
    assert net.exit_code != 0
    timed = await sandbox.run("sleep 60", timeout_sec=2)
    assert timed.exit_code == 124
    import asyncio

    proc = await asyncio.create_subprocess_exec(
        "docker",
        "ps",
        "-aq",
        "--filter",
        f"name={sandbox.last_container}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    assert out.decode().strip() == ""


def test_settings_sandbox_defaults() -> None:
    settings = Settings()
    assert settings.sandbox_network is False
    assert settings.sandbox_memory_mb >= 128
