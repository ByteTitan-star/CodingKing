"""Async JSON-RPC line reader/writer over stdio."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any

from coderking_transport.rpc.jsonrpc import (
    JsonRpcError,
    format_error,
    format_notification,
    format_response,
    parse_request,
)

RequestHandler = Callable[[str, dict[str, Any]], Coroutine[Any, Any, Any]]


class StdioJsonRpcServer:
    def __init__(
        self,
        handlers: dict[str, RequestHandler],
        *,
        stdin: Any | None = None,
        stdout: Any | None = None,
    ) -> None:
        self.handlers = handlers
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout
        self._write_lock = asyncio.Lock()

    async def write_line(self, line: str) -> None:
        async with self._write_lock:
            await asyncio.to_thread(self._write_sync, line)

    def _write_sync(self, line: str) -> None:
        self.stdout.write(line + "\n")
        self.stdout.flush()

    async def notify(self, method: str, params: Any) -> None:
        await self.write_line(format_notification(method, params))

    async def respond(self, request_id: Any, result: Any) -> None:
        await self.write_line(format_response(request_id, result))

    async def respond_error(self, request_id: Any, error: JsonRpcError) -> None:
        await self.write_line(format_error(request_id, error))

    async def handle_request(self, line: str) -> None:
        request_id: Any = None
        try:
            request = parse_request(line)
            request_id = request.get("id")
            method = str(request["method"])
            params = request.get("params") or {}
            if not isinstance(params, dict):
                raise JsonRpcError(-32602, "Invalid params")
            handler = self.handlers.get(method)
            if handler is None:
                raise JsonRpcError(-32601, f"Method not found: {method}")
            result = await handler(method, params)
            if request_id is not None:
                await self.respond(request_id, result)
        except JsonRpcError as exc:
            if request_id is not None:
                await self.respond_error(request_id, exc)
        except Exception as exc:
            if request_id is not None:
                await self.respond_error(request_id, JsonRpcError(-32000, str(exc)))

    async def serve_forever(self) -> None:
        async for line in iter_stdin_lines(self.stdin):
            if line.strip():
                await self.handle_request(line.strip())


async def iter_stdin_lines(stdin: Any) -> AsyncIterator[str]:
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, stdin)
    while True:
        line = await reader.readline()
        if not line:
            break
        yield line.decode("utf-8", errors="replace")
