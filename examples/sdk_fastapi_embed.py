"""FastAPI embed: expose AgentSession behind a simple HTTP endpoint."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel, Field

from coderking_sdk import AgentSession

app = FastAPI(title="CoderKing SDK embed example")


class RunRequest(BaseModel):
    prompt: str
    workspace: str = Field(default=".")


class RunResponse(BaseModel):
    status: str
    events: list[dict]


@app.post("/run", response_model=RunResponse)
async def run_agent(body: RunRequest) -> RunResponse:
    events: list[dict] = []
    async with AgentSession(
        workspace=Path(body.workspace),
        auto_approve=True,
    ) as session:
        async for event in session.run(body.prompt):
            events.append(dict(event))
        status = session.status().get("status", "unknown")
    return RunResponse(status=str(status), events=events)


# uvicorn examples.sdk_fastapi_embed:app --reload
