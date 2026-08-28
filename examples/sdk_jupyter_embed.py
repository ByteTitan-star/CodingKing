"""Jupyter-style embed: await AgentSession in an async cell / IPython.

Usage in a notebook cell::

    %pip install -e ..
    from examples.sdk_jupyter_embed import run_once
    await run_once(".")
"""

from __future__ import annotations

from pathlib import Path

from coderking_sdk import AgentSession


async def run_once(workspace: str = ".", prompt: str = "List top-level files") -> list[dict]:
    """Run one prompt and return collected event records."""
    events: list[dict] = []
    async with AgentSession(workspace=Path(workspace), auto_approve=True) as session:
        async for event in session.run(prompt):
            events.append(dict(event))
            if event.get("type") in {"done", "error"}:
                break
    return events


# Notebook tip: do not call asyncio.run() inside Jupyter — the kernel already
# has a running loop. Use ``await run_once()`` directly.
