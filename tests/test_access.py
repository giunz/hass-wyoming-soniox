import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from wyoming.info import Info

from wyoming_soniox.access import ClientAccess, parse_networks
from wyoming_soniox.const import Limits, Settings
from wyoming_soniox.handler import SonioxEventHandler


def peer(host, port=5555):
    return (host, port)


@pytest.mark.parametrize(
    "host",
    ["192.168.1.20", "10.0.0.5", "172.30.32.1", "172.17.0.2", "169.254.3.4", "fd12::1", "fe80::1%eth0", "::ffff:192.168.1.20"],
)
def test_default_allows_home_and_local_networks(host):
    assert ClientAccess().admit(peer(host))


@pytest.mark.parametrize(
    "host", ["8.8.8.8", "203.0.113.9", "172.32.0.1", "2001:db8::1", "::ffff:8.8.8.8"]
)
def test_default_refuses_public_addresses(host):
    assert not ClientAccess().admit(peer(host))


def test_explicit_list_replaces_the_default_but_this_machine_is_always_allowed():
    access = ClientAccess(["192.168.1.0/24", "10.0.0.5"])
    assert access.admit(peer("192.168.1.77"))
    assert access.admit(peer("10.0.0.5"))
    assert not access.admit(peer("10.0.0.6"))  # private, but not listed
    assert not access.admit(peer("172.30.32.1"))
    assert access.admit(peer("127.0.0.1")) and access.admit(peer("::1"))


def test_unix_socket_and_unreadable_addresses():
    access = ClientAccess()
    assert access.admit("")  # a local unix socket
    assert access.admit(None)
    assert not access.admit(peer("not-an-ip"))


def test_invalid_entries_are_reported():
    with pytest.raises(ValueError, match="not an IP address or network"):
        parse_networks(["192.168.1.0/24", "192.168.1.x"])
    with pytest.raises(ValueError, match="192.168.1.x"):
        Settings(api_key="k", allowed_clients=["192.168.1.x"])
    assert parse_networks([" ", "", " 10.0.0.1 "]) == parse_networks(["10.0.0.1"])


def test_new_clients_are_logged_once(caplog):
    caplog.set_level(logging.INFO)
    access = ClientAccess()
    for _ in range(3):
        access.admit(peer("192.168.1.20"))
    access.admit(peer("192.168.1.21"))
    access.admit(peer("127.0.0.1"))  # health checks: not mentioned
    lines = [r.getMessage() for r in caplog.records]
    assert lines == ["New client address: 192.168.1.20", "New client address: 192.168.1.21"]


def test_every_connection_is_logged_when_asked(caplog):
    caplog.set_level(logging.INFO)
    access = ClientAccess(log_connections=True)
    for _ in range(3):
        access.admit(peer("192.168.1.20"))
    access.admit(peer("127.0.0.1"))
    lines = [r.getMessage() for r in caplog.records]
    assert lines == ["Connection from 192.168.1.20"] * 3


def test_refused_clients_are_warned_about_without_flooding(caplog):
    caplog.set_level(logging.INFO)
    access = ClientAccess()
    for _ in range(50):
        assert not access.admit(peer("203.0.113.9"))
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "203.0.113.9" in warnings[0].getMessage()


def test_log_memory_is_bounded(caplog):
    caplog.set_level(logging.INFO)
    access = ClientAccess(["10.0.0.0/8"])
    for i in range(1000):
        access.admit(peer(f"10.1.{i // 250}.{i % 250 + 1}"))
        access.admit(peer(f"198.51.{i // 250}.{i % 250 + 1}"))
    assert len(access._seen) <= 256 and len(access._refused_at) <= 256


def test_describe():
    assert "home and local networks" in ClientAccess().describe()
    assert "192.168.1.0/24 (from the setting" in ClientAccess(["192.168.1.0/24"]).describe()


def _handler(host, allowed=()):
    settings = Settings(api_key="k", allowed_clients=list(allowed))
    reader, writer = MagicMock(), MagicMock()
    reader.readline = AsyncMock(return_value=b"")  # client hangs up at once
    writer.get_extra_info.return_value = (host, 4242)
    return SonioxEventHandler(Info(), settings, None, Limits(settings), reader, writer), reader, writer


@pytest.mark.asyncio
async def test_handler_refuses_a_disallowed_client_before_reading_anything():
    handler, reader, writer = _handler("203.0.113.9")
    await handler.run()
    reader.readline.assert_not_called()
    writer.close.assert_called_once()


@pytest.mark.asyncio
async def test_handler_serves_an_allowed_client():
    handler, reader, writer = _handler("192.168.1.20")
    await handler.run()
    reader.readline.assert_awaited()
    writer.close.assert_called_once()
