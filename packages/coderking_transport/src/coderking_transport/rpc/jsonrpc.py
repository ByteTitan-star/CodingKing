"""JSON-RPC 2.0 line helpers for stdio transport."""

from __future__ import annotations

import json
from typing import Any

JSONRPC_VERSION = "2.0"


class JsonRpcError(Exception):
    def __init__(self, code: int, message: str, *, data: Any | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def parse_request(line: str) -> dict[str, Any]:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        raise JsonRpcError(-32700, "Parse error") from exc
    if not isinstance(payload, dict):
        raise JsonRpcError(-32600, "Invalid Request")
    if payload.get("jsonrpc") != JSONRPC_VERSION:
        raise JsonRpcError(-32600, "Invalid Request")
    if "method" not in payload:
        raise JsonRpcError(-32600, "Invalid Request")
    return payload


def format_response(request_id: Any, result: Any) -> str:
    return json.dumps(
        {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def format_error(request_id: Any, error: JsonRpcError) -> str:
    payload: dict[str, Any] = {"code": error.code, "message": error.message}
    if error.data is not None:
        payload["data"] = error.data
    return json.dumps(
        {"jsonrpc": JSONRPC_VERSION, "id": request_id, "error": payload},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def format_notification(method: str, params: Any) -> str:
    return json.dumps(
        {"jsonrpc": JSONRPC_VERSION, "method": method, "params": params},
        ensure_ascii=False,
        separators=(",", ":"),
    )
