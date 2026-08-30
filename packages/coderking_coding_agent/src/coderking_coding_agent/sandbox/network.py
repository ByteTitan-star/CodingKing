"""Sandbox network policy: none | full | restricted (host allowlist + proxy)."""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import secrets
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit

NetworkMode = Literal["none", "full", "restricted"]

DEFAULT_ALLOW_HOSTS: tuple[str, ...] = (
    "pypi.org",
    "files.pythonhosted.org",
    "pypi.python.org",
    "registry.npmjs.org",
    "registry.yarnpkg.com",
    "github.com",
    "codeload.github.com",
    "objects.githubusercontent.com",
)

_HOST_PORT_RE = re.compile(r"^\[?(?P<host>[^\]:]+)\]?(?::(?P<port>\d+))?$")
log = logging.getLogger(__name__)


def normalize_host(host: str) -> str:
    raw = host.strip().lower().rstrip(".")
    if not raw:
        return ""
    match = _HOST_PORT_RE.match(raw)
    if not match:
        return raw
    return match.group("host")


def host_allowed(host: str, allow_hosts: Sequence[str]) -> bool:
    candidate = normalize_host(host)
    if not candidate:
        return False
    allowed = {normalize_host(h) for h in allow_hosts if normalize_host(h)}
    if candidate in allowed:
        return True
    # Exact match only — no automatic subdomain wildcard (pypi.org != evil.pypi.org).
    return False


def parse_allow_hosts(value: str | Iterable[str] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(",")]
        return tuple(p for p in parts if p)
    return tuple(str(p).strip() for p in value if str(p).strip())


def resolve_network_mode(
    *,
    sandbox_network: bool,
    sandbox_network_mode: NetworkMode | None,
) -> NetworkMode:
    if sandbox_network_mode is not None:
        return sandbox_network_mode
    return "full" if sandbox_network else "none"


@dataclass(frozen=True)
class NetworkPolicy:
    mode: NetworkMode = "none"
    allow_hosts: tuple[str, ...] = field(default_factory=tuple)
    proxy_url: str | None = None

    def __post_init__(self) -> None:
        if self.mode == "restricted" and not self.allow_hosts:
            raise ValueError(
                "sandbox network mode 'restricted' requires non-empty allow_hosts "
                "(e.g. pypi.org, files.pythonhosted.org)"
            )

    @property
    def needs_proxy(self) -> bool:
        return self.mode == "restricted"

    def docker_network_args(self) -> list[str]:
        if self.mode == "none":
            return ["--network", "none"]
        return []

    def proxy_env(self) -> dict[str, str]:
        if not self.needs_proxy or not self.proxy_url:
            return {}
        return {
            "HTTP_PROXY": self.proxy_url,
            "HTTPS_PROXY": self.proxy_url,
            "http_proxy": self.proxy_url,
            "https_proxy": self.proxy_url,
            "ALL_PROXY": self.proxy_url,
            "all_proxy": self.proxy_url,
            "NO_PROXY": "localhost,127.0.0.1",
            "no_proxy": "localhost,127.0.0.1",
        }

    def with_proxy_url(self, url: str) -> NetworkPolicy:
        return NetworkPolicy(mode=self.mode, allow_hosts=self.allow_hosts, proxy_url=url)


class AllowlistProxy:
    """HTTP CONNECT / absolute-URI proxy with host allowlist + Basic auth token.

    Auth prevents other local processes from reusing a temporary proxy even when
    the socket must bind beyond loopback for Docker host-gateway reachability.
    """

    def __init__(self, policy: NetworkPolicy, *, host: str = "127.0.0.1") -> None:
        if not policy.needs_proxy:
            raise ValueError("AllowlistProxy requires restricted NetworkPolicy")
        self.policy = policy
        self.host = host
        self.token = secrets.token_urlsafe(24)
        self.port: int | None = None
        self.denials: list[str] = []
        self._server: asyncio.Server | None = None

    @property
    def url(self) -> str:
        if self.port is None:
            raise RuntimeError("proxy is not started")
        return self.proxy_url_for(self.host)

    def proxy_url_for(self, host: str) -> str:
        if self.port is None:
            raise RuntimeError("proxy is not started")
        return f"http://ck:{self.token}@{host}:{self.port}"

    async def start(self) -> str:
        self._server = await asyncio.start_server(self._handle, self.host, 0)
        sockets = self._server.sockets or []
        if not sockets:
            raise RuntimeError("failed to bind allowlist proxy")
        self.port = int(sockets[0].getsockname()[1])
        return self.url

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    async def __aenter__(self) -> AllowlistProxy:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()

    def _authorized(self, headers: dict[str, str]) -> bool:
        raw = headers.get("proxy-authorization") or headers.get("authorization") or ""
        if not raw.lower().startswith("basic "):
            return False
        try:
            decoded = base64.b64decode(raw.split(" ", 1)[1].strip()).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return False
        user, _, password = decoded.partition(":")
        return user == "ck" and password == self.token and bool(password)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = await reader.readline()
            if not request_line:
                return
            line = request_line.decode("latin-1", errors="replace").strip()
            parts = line.split(" ")
            if len(parts) < 2:
                await self._deny(writer, "bad-request", line)
                return
            method, target = parts[0].upper(), parts[1]
            headers: dict[str, str] = {}
            while True:
                header = await reader.readline()
                if header in (b"\r\n", b"\n", b""):
                    break
                text = header.decode("latin-1", errors="replace").strip()
                if ":" in text:
                    key, value = text.split(":", 1)
                    headers[key.strip().lower()] = value.strip()

            if not self._authorized(headers):
                await self._auth_required(writer)
                return

            if method == "CONNECT":
                host = normalize_host(target)
                if not host_allowed(host, self.policy.allow_hosts):
                    await self._deny(writer, host, line)
                    return
                await self._tunnel(reader, writer, host, target)
                return

            host = self._host_from_absolute_uri(target)
            if host is None or not host_allowed(host, self.policy.allow_hosts):
                await self._deny(writer, host or "unknown", line)
                return
            await self._forward_http(reader, writer, method, target, line)
        except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass

    async def _auth_required(self, writer: asyncio.StreamWriter) -> None:
        body = b"Proxy authentication required\n"
        writer.write(
            b"HTTP/1.1 407 Proxy Authentication Required\r\n"
            b'Proxy-Authenticate: Basic realm="coderking"\r\n'
            b"Content-Type: text/plain\r\n"
            b"Connection: close\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
        )
        await writer.drain()

    async def _deny(self, writer: asyncio.StreamWriter, host: str, line: str) -> None:
        self.denials.append(host)
        log.warning("sandbox network denied: host=%s request=%s", host, line[:200])
        body = f"CoderKing network policy denied host: {host}\n".encode()
        writer.write(
            b"HTTP/1.1 403 Forbidden\r\n"
            b"Content-Type: text/plain\r\n"
            b"Connection: close\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
        )
        await writer.drain()

    def _host_from_absolute_uri(self, target: str) -> str | None:
        parsed = urlsplit(target)
        if parsed.hostname:
            return normalize_host(parsed.hostname)
        return None

    async def _tunnel(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
        host: str,
        target: str,
    ) -> None:
        match = _HOST_PORT_RE.match(target.strip())
        port = int(match.group("port")) if match and match.group("port") else 443
        try:
            remote_reader, remote_writer = await asyncio.open_connection(host, port)
        except OSError:
            await self._deny(client_writer, host, f"CONNECT {target}")
            return
        client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await client_writer.drain()

        async def pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
            try:
                while True:
                    data = await src.read(65536)
                    if not data:
                        break
                    dst.write(data)
                    await dst.drain()
            except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
                pass
            finally:
                try:
                    dst.close()
                except Exception:  # noqa: BLE001
                    pass

        await asyncio.gather(
            pipe(client_reader, remote_writer),
            pipe(remote_reader, client_writer),
        )

    async def _forward_http(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
        method: str,
        target: str,
        request_line: str,
    ) -> None:
        parsed = urlsplit(target)
        host = parsed.hostname
        if not host:
            await self._deny(client_writer, "unknown", request_line)
            return
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        try:
            remote_reader, remote_writer = await asyncio.open_connection(host, port)
        except OSError:
            await self._deny(client_writer, host, request_line)
            return
        remote_writer.write(f"{method} {path} HTTP/1.1\r\n".encode())
        remote_writer.write(f"Host: {host}\r\n".encode())
        remote_writer.write(b"Connection: close\r\n\r\n")
        await remote_writer.drain()
        # Best-effort: no request body for GET-style package index probes.
        while True:
            chunk = await remote_reader.read(65536)
            if not chunk:
                break
            client_writer.write(chunk)
            await client_writer.drain()
        remote_writer.close()
        await remote_writer.wait_closed()
