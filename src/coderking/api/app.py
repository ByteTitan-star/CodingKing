from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from coderking import __version__
from coderking.controller import CONTROLLER, TaskController
from coderking.workspace import ensure_inside, iter_files
from coderking_coding_agent.context.project_docs import ProjectInstructionsLoader
from coderking_coding_agent.context.skills import SkillRegistry
from coderking_transport.http.sse import stream_task_events

_LOCAL_CLIENTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})
_PUBLIC_API_PATHS = frozenset({"/api/health"})


def api_token() -> str:
    return (os.environ.get("CODERKING_API_TOKEN") or "").strip()


def http_auto_approve_allowed() -> bool:
    return os.environ.get("CODERKING_HTTP_AUTO_APPROVE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _client_host(request: Request) -> str:
    return (request.client.host if request.client else "") or ""


def _provided_token(request: Request) -> str:
    header = (request.headers.get("x-coderking-token") or "").strip()
    auth = request.headers.get("authorization") or ""
    bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    query = (request.query_params.get("token") or "").strip()
    return header or bearer or query


def _authorize_request(request: Request) -> JSONResponse | None:
    path = request.url.path
    if path in _PUBLIC_API_PATHS or not (path.startswith("/api") or path.startswith("/ws")):
        return None
    expected = api_token()
    if expected:
        if _provided_token(request) != expected:
            return JSONResponse({"detail": "invalid or missing API token"}, status_code=401)
        return None
    if _client_host(request) not in _LOCAL_CLIENTS:
        return JSONResponse(
            {"detail": "CODERKING_API_TOKEN required for non-local HTTP access"},
            status_code=401,
        )
    return None


def _constrain_workspace(ctrl: TaskController, requested: str | None) -> Path:
    allowed = ctrl.settings.resolved_workspace()
    if not requested:
        return allowed
    try:
        return ensure_inside(allowed, Path(requested))
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc


def _web_dist() -> Path:
    here = Path(__file__).resolve()
    candidates = [here.parents[3] / "web" / "dist", Path.cwd() / "web" / "dist"]
    for path in candidates:
        if path.is_dir():
            return path
    return candidates[0]


class TaskCreate(BaseModel):
    prompt: str
    repository: str | None = None
    auto_approve: bool = False
    test_command: str | None = None


class SteerBody(BaseModel):
    content: str


class FollowUpBody(BaseModel):
    content: str


class ApprovalBody(BaseModel):
    allowed: bool = Field(..., alias="allowed")

    model_config = {"populate_by_name": True}


def create_app(controller: TaskController | None = None) -> FastAPI:
    ctrl = controller or CONTROLLER
    app = FastAPI(title="CoderKing", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def require_api_auth(request: Request, call_next):  # noqa: ANN001
        denied = _authorize_request(request)
        if denied is not None:
            return denied
        return await call_next(request)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.post("/api/tasks")
    async def create_task(body: TaskCreate) -> dict:
        workspace = _constrain_workspace(ctrl, body.repository)
        auto_approve = bool(body.auto_approve) and http_auto_approve_allowed()
        if body.auto_approve and not auto_approve:
            raise HTTPException(
                403,
                "auto_approve over HTTP requires CODERKING_HTTP_AUTO_APPROVE=1",
            )
        task = await ctrl.create_task(
            body.prompt,
            workspace,
            auto_approve=auto_approve,
            test_command=body.test_command,
        )
        return ctrl.public_task(task.state.task_id)

    @app.get("/api/tasks/{task_id}")
    async def get_task(task_id: str) -> dict:
        try:
            return ctrl.public_task(task_id)
        except KeyError as exc:
            raise HTTPException(404, "task not found") from exc

    @app.get("/api/tasks/{task_id}/tree")
    async def task_tree(task_id: str) -> dict:
        try:
            return {"files": ctrl.tree(task_id)}
        except KeyError as exc:
            raise HTTPException(404, "task not found") from exc

    @app.get("/api/tasks/{task_id}/file")
    async def task_file(task_id: str, path: str) -> dict:
        try:
            return {"path": path, "content": ctrl.read_file(task_id, path)}
        except (KeyError, PermissionError, FileNotFoundError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/tasks/{task_id}/diff")
    async def task_diff(task_id: str) -> dict:
        try:
            return {"diff": ctrl.diff(task_id)}
        except KeyError as exc:
            raise HTTPException(404, "task not found") from exc

    @app.post("/api/tasks/{task_id}/rollback")
    async def rollback(task_id: str) -> dict:
        try:
            ctrl.rollback(task_id)
            return {"ok": True, "diff": ctrl.diff(task_id)}
        except KeyError as exc:
            raise HTTPException(404, "task not found") from exc

    @app.post("/api/tasks/{task_id}/accept")
    async def accept_patch(task_id: str) -> dict:
        try:
            return {"ok": True, "diff": ctrl.diff(task_id)}
        except KeyError as exc:
            raise HTTPException(404, "task not found") from exc

    @app.get("/api/workspace/tree")
    async def workspace_tree(root: str | None = None) -> dict:
        base = _constrain_workspace(ctrl, root)
        files = [p.relative_to(base).as_posix() for p in iter_files(base, max_files=500)]
        return {"root": str(base), "files": files}

    @app.get("/api/workspace/project-instructions")
    async def workspace_project_instructions(root: str | None = None) -> dict:
        base = _constrain_workspace(ctrl, root)
        return ProjectInstructionsLoader(base).inspect()

    @app.get("/api/workspace/skills")
    async def workspace_skills(root: str | None = None) -> dict:
        base = _constrain_workspace(ctrl, root)
        return SkillRegistry(base, include_cursor=False).inspect()

    @app.post("/api/tasks/{task_id}/approve")
    async def approve(task_id: str, body: ApprovalBody | None = None) -> dict:
        allowed = True if body is None else body.allowed
        try:
            ctrl.resolve_approval(task_id, allowed)
        except KeyError as exc:
            raise HTTPException(404, "task not found") from exc
        return {"ok": True}

    @app.post("/api/tasks/{task_id}/reject")
    async def reject(task_id: str) -> dict:
        try:
            ctrl.resolve_approval(task_id, False)
        except KeyError as exc:
            raise HTTPException(404, "task not found") from exc
        return {"ok": True}

    @app.post("/api/tasks/{task_id}/interrupt")
    async def interrupt(task_id: str) -> dict:
        try:
            ctrl.interrupt(task_id)
        except KeyError as exc:
            raise HTTPException(404, "task not found") from exc
        return {"ok": True}

    @app.post("/api/tasks/{task_id}/steer")
    async def steer_task(task_id: str, body: SteerBody) -> dict:
        try:
            await ctrl.steer(task_id, body.content)
        except KeyError as exc:
            raise HTTPException(404, "task not found") from exc
        return {"ok": True}

    @app.post("/api/tasks/{task_id}/follow-up")
    async def follow_up_task(task_id: str, body: FollowUpBody) -> dict:
        try:
            await ctrl.follow_up(task_id, body.content)
        except KeyError as exc:
            raise HTTPException(404, "task not found") from exc
        return {"ok": True}

    @app.get("/api/v2/tasks/{task_id}/events")
    async def task_events_sse(task_id: str, request: Request) -> StreamingResponse:
        """v2 SSE event stream with Last-Event-ID replay (preferred over WebSocket)."""
        try:
            ctrl.get(task_id)
        except KeyError as exc:
            raise HTTPException(404, "task not found") from exc
        last_event_id = request.headers.get("Last-Event-ID") or request.headers.get("last-event-id")
        return StreamingResponse(
            stream_task_events(ctrl, task_id, last_event_id=last_event_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.websocket("/ws/tasks/{task_id}")
    async def task_ws(websocket: WebSocket, task_id: str) -> None:
        """Legacy WebSocket stream (deprecated; use /api/v2/tasks/{id}/events SSE)."""
        import asyncio

        expected = api_token()
        provided = (websocket.query_params.get("token") or "").strip()
        client = (websocket.client.host if websocket.client else "") or ""
        if expected:
            if provided != expected:
                await websocket.close(code=1008)
                return
        elif client not in _LOCAL_CLIENTS:
            await websocket.close(code=1008)
            return

        await websocket.accept()
        try:
            task = ctrl.get(task_id)
        except KeyError:
            await websocket.send_json({"type": "error", "payload": {"message": "task not found"}})
            await websocket.close()
            return
        for record in task.snapshot:
            await websocket.send_json(record)

        async def read_client() -> None:
            try:
                while True:
                    data = await websocket.receive_json()
                    msg_type = str(data.get("type") or "")
                    content = str(data.get("content") or "")
                    if msg_type == "steer":
                        await ctrl.steer(task_id, content)
                    elif msg_type in {"follow_up", "follow-up"}:
                        await ctrl.follow_up(task_id, content)
            except WebSocketDisconnect:
                return

        reader = asyncio.create_task(read_client())
        try:
            async for record in ctrl.subscribe_records(task_id):
                await websocket.send_json(record)
        except WebSocketDisconnect:
            return
        except KeyError:
            await websocket.close()
        finally:
            reader.cancel()

    dist = _web_dist()
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    return app


app = create_app()
