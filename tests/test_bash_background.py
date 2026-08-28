from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from coderking.sandbox.local import LocalProcessSandbox
from coderking.tools.shell import ShellTool


@pytest.mark.asyncio
async def test_background_start_and_poll(tmp_path: Path) -> None:
    sandbox = LocalProcessSandbox(tmp_path)
    tool = ShellTool(sandbox, timeout_sec=30, name="bash")
    if sys.platform == "win32":
        start_cmd = "python -c \"import time; print('dev-server-ready'); time.sleep(2)\""
    else:
        start_cmd = "sleep 0.5 && echo dev-server-ready && sleep 2"
    started = await tool.execute(command=start_cmd, background=True)
    assert started.ok
    payload = json.loads(started.output)
    job_id = payload["job_id"]

    for _ in range(40):
        polled = await tool.execute(job_id=job_id)
        assert polled.ok
        status = json.loads(polled.output)
        if status["status"] in {"completed", "failed", "killed"}:
            break
        await asyncio.sleep(0.1)
    else:
        pytest.fail("background job did not finish")

    assert "dev-server-ready" in status["stdout_tail"]
    await sandbox.close()


@pytest.mark.asyncio
async def test_background_kill(tmp_path: Path) -> None:
    sandbox = LocalProcessSandbox(tmp_path)
    tool = ShellTool(sandbox, timeout_sec=30, name="bash")
    cmd = 'python -c "import time; time.sleep(60)"' if sys.platform == "win32" else "sleep 60"
    started = await tool.execute(command=cmd, background=True)
    job_id = json.loads(started.output)["job_id"]

    killed = await tool.execute(job_id=job_id, kill=True)
    assert killed.ok

    polled = await tool.execute(job_id=job_id)
    status = json.loads(polled.output)
    assert status["status"] == "killed"
    await sandbox.close()


@pytest.mark.asyncio
async def test_sandbox_close_kills_background_jobs(tmp_path: Path) -> None:
    sandbox = LocalProcessSandbox(tmp_path)
    tool = ShellTool(sandbox, timeout_sec=30, name="bash")
    cmd = 'python -c "import time; time.sleep(60)"' if sys.platform == "win32" else "sleep 60"
    started = await tool.execute(command=cmd, background=True)
    job_id = json.loads(started.output)["job_id"]
    job = sandbox._jobs._jobs[job_id]
    assert job.proc.returncode is None

    await sandbox.close()
    assert job.proc.returncode is not None


@pytest.mark.asyncio
async def test_foreground_command_unchanged(tmp_path: Path) -> None:
    sandbox = LocalProcessSandbox(tmp_path)
    tool = ShellTool(sandbox, timeout_sec=30, name="bash")
    if sys.platform == "win32":
        result = await tool.execute(command="python -c \"print('ok')\"")
    else:
        result = await tool.execute(command="echo ok")
    assert result.ok
    assert "ok" in result.output
    await sandbox.close()
