"""Script embed: run a CoderKing AgentSession from asyncio."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from coderking_sdk import AgentSession


async def main() -> None:
    workspace = Path(os.environ.get("CODERKING_WORKSPACE", ".")).resolve()
    async with AgentSession(workspace=workspace, auto_approve=True) as session:
        async for event in session.run("Summarize the repository structure"):
            kind = event.get("type")
            if kind in {"done", "error", "agent_status", "tool_call"}:
                print(kind, event.get("payload"))
        print("status:", session.status().get("status"))


if __name__ == "__main__":
    asyncio.run(main())
