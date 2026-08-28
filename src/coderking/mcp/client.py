"""Minimal MCP stdio JSON-RPC client (tools/list + tools/call)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from coderking.mcp.config import McpServerConfig
from coderking.sandbox.credentials import scrub_env

PROTOCOL_VERSION = "2024-11-05"


@dataclass
class McpToolInfo:
    server: str
    name: str
    description: str
    input_schema: dict[str, Any]

    @property
    def namespaced(self) -> str:
        return f"mcp_{self.server}_{self.name}"


class McpStdioSession:
    def __init__(self, config: McpServerConfig, *, timeout_sec: float = 60.0) -> None:
        self.config = config
        self.timeout_sec = timeout_sec
        self._proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._next_id = 1
        self._closed = False
        self.tools: list[McpToolInfo] = []

    async def start(self) -> None:
        env = scrub_env()
        env.update(self.config.env)
        self._proc = await asyncio.create_subprocess_exec(
            self.config.command,
            *self.config.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        assert self._proc.stdout is not None
        self._reader_task = asyncio.create_task(self._read_loop())
        await self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "coderking", "version": "1.0.5"},
            },
        )
        await self._notify("notifications/initialized", {})
        listed = await self._request("tools/list", {})
        for item in listed.get("tools") or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            schema = (
                item.get("inputSchema")
                or item.get("input_schema")
                or {
                    "type": "object",
                    "properties": {},
                }
            )
            self.tools.append(
                McpToolInfo(
                    server=self.config.name,
                    name=name,
                    description=str(item.get("description") or name),
                    input_schema=dict(schema) if isinstance(schema, dict) else {},
                )
            )

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> tuple[bool, str]:
        result = await self._request(
            "tools/call",
            {"name": name, "arguments": arguments},
        )
        is_error = bool(result.get("isError"))
        parts: list[str] = []
        for block in result.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
            elif isinstance(block, dict):
                parts.append(json.dumps(block, ensure_ascii=False))
            else:
                parts.append(str(block))
        text = "\n".join(p for p in parts if p).strip() or json.dumps(result, ensure_ascii=False)
        return (not is_error), text

    async def close(self) -> None:
        self._closed = True
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None
        if self._proc is not None and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=3)
            except TimeoutError:
                self._proc.kill()
                await self._proc.wait()
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(RuntimeError("MCP session closed"))
        self._pending.clear()
        self._proc = None

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        req_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[req_id] = fut
        await self._write({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        try:
            return await asyncio.wait_for(fut, timeout=self.timeout_sec)
        finally:
            self._pending.pop(req_id, None)

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        await self._write({"jsonrpc": "2.0", "method": method, "params": params})

    async def _write(self, message: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("MCP process not started")
        payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
        header = f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii")
        self._proc.stdin.write(header + payload)
        await self._proc.stdin.drain()

    async def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        reader = self._proc.stdout
        try:
            while not self._closed:
                headers: dict[str, str] = {}
                while True:
                    line = await reader.readline()
                    if not line:
                        return
                    if line in (b"\r\n", b"\n"):
                        break
                    text = line.decode("utf-8", errors="replace").strip()
                    if ":" in text:
                        key, value = text.split(":", 1)
                        headers[key.strip().lower()] = value.strip()
                length = int(headers.get("content-length") or "0")
                if length <= 0:
                    continue
                body = await reader.readexactly(length)
                message = json.loads(body.decode("utf-8"))
                if not isinstance(message, dict):
                    continue
                msg_id = message.get("id")
                if msg_id is None:
                    continue
                fut = self._pending.get(int(msg_id))
                if fut is None or fut.done():
                    continue
                if "error" in message:
                    err = message["error"]
                    fut.set_exception(RuntimeError(str(err)))
                else:
                    fut.set_result(dict(message.get("result") or {}))
        except (asyncio.CancelledError, asyncio.IncompleteReadError, ConnectionResetError):
            return
        except Exception as exc:  # noqa: BLE001
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(exc)
            self._pending.clear()
