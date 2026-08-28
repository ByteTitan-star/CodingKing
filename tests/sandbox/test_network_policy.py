"""Network allowlist policy for sandbox egress."""

from __future__ import annotations

import asyncio

import pytest

from coderking.sandbox.network import (
    DEFAULT_ALLOW_HOSTS,
    NetworkPolicy,
    host_allowed,
    parse_allow_hosts,
    resolve_network_mode,
)


def test_host_allowed_exact_and_subdomain() -> None:
    allowed = ("pypi.org", "files.pythonhosted.org")
    assert host_allowed("pypi.org", allowed)
    assert host_allowed("pypi.org:443", allowed)
    assert host_allowed("files.pythonhosted.org", allowed)
    assert not host_allowed("evil.pypi.org.attacker.com", allowed)
    assert not host_allowed("google.com", allowed)
    assert not host_allowed("pypi.org.evil.com", allowed)


def test_host_allowed_rejects_empty_and_ip_literal_unless_listed() -> None:
    assert not host_allowed("", ("pypi.org",))
    assert not host_allowed("1.1.1.1", ("pypi.org",))
    assert host_allowed("1.1.1.1", ("1.1.1.1",))


def test_network_policy_restricted_requires_hosts() -> None:
    with pytest.raises(ValueError, match="allow_hosts"):
        NetworkPolicy(mode="restricted", allow_hosts=())


def test_network_policy_docker_flags() -> None:
    none = NetworkPolicy(mode="none")
    assert none.docker_network_args() == ["--network", "none"]
    assert none.proxy_env() == {}

    full = NetworkPolicy(mode="full")
    assert full.docker_network_args() == []
    assert full.proxy_env() == {}

    restricted = NetworkPolicy(mode="restricted", allow_hosts=("pypi.org",))
    assert restricted.docker_network_args() == []
    # proxy URL filled by sandbox when proxy is running
    assert restricted.needs_proxy is True


def test_resolve_network_mode_from_legacy_bool() -> None:
    assert resolve_network_mode(sandbox_network=False, sandbox_network_mode=None) == "none"
    assert resolve_network_mode(sandbox_network=True, sandbox_network_mode=None) == "full"
    assert (
        resolve_network_mode(sandbox_network=False, sandbox_network_mode="restricted")
        == "restricted"
    )


def test_parse_allow_hosts_csv_and_list() -> None:
    assert parse_allow_hosts("pypi.org, files.pythonhosted.org") == (
        "pypi.org",
        "files.pythonhosted.org",
    )
    assert parse_allow_hosts(["a.com", "b.com"]) == ("a.com", "b.com")
    assert "pypi.org" in DEFAULT_ALLOW_HOSTS


@pytest.mark.asyncio
async def test_allowlist_proxy_denies_and_allows() -> None:
    from coderking.sandbox.network import AllowlistProxy

    policy = NetworkPolicy(mode="restricted", allow_hosts=("example.com",))
    async with AllowlistProxy(policy, host="127.0.0.1") as proxy:
        # Denied CONNECT
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy.port)
        writer.write(b"CONNECT google.com:443 HTTP/1.1\r\nHost: google.com:443\r\n\r\n")
        await writer.drain()
        status = await reader.readline()
        writer.close()
        await writer.wait_closed()
        assert b"403" in status
        assert "google.com" in proxy.denials
