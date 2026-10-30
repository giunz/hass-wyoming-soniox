"""Which clients may connect, and logging of client addresses.

The Wyoming protocol has no login, so the client's network address is the only
thing the bridge can check.
"""

import ipaddress
import logging
import time
from typing import Dict, Iterable, List, Optional, Set, Union

_LOGGER = logging.getLogger(__name__)

IPAddress = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]
IPNetwork = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]

# Used when no allowed client addresses are set: this machine, the usual home
# network ranges, and Home Assistant's own container networks (172.16/12).
# Public internet addresses are refused.
DEFAULT_ALLOWED = (
    "127.0.0.0/8",
    "::1/128",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "169.254.0.0/16",
    "fc00::/7",
    "fe80::/10",
)

_MAX_TRACKED = 256  # addresses remembered for log de-duplication
_REFUSED_LOG_INTERVAL = 600  # seconds between warnings about the same address


def parse_networks(values: Iterable[str]) -> List[IPNetwork]:
    """Turn "192.168.1.5" / "192.168.1.0/24" strings into networks."""
    networks: List[IPNetwork] = []
    for raw in values:
        raw = raw.strip()
        if not raw:
            continue
        try:
            networks.append(ipaddress.ip_network(raw, strict=False))
        except ValueError:
            raise ValueError(
                f"Allowed client addresses: {raw!r} is not an IP address or "
                "network (examples: 192.168.1.20 or 192.168.1.0/24)"
            ) from None
    return networks


def _client_ip(peername) -> Optional[IPAddress]:
    """The client's IP address, or None for a local (unix socket) client."""
    if not isinstance(peername, (tuple, list)) or not peername:
        return None
    ip = ipaddress.ip_address(str(peername[0]).split("%")[0])  # drop IPv6 zone
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip


class ClientAccess:
    """Decides which connections are accepted and logs the client addresses."""

    def __init__(self, allowed: Iterable[str] = (), log_connections: bool = False) -> None:
        explicit = parse_networks(allowed)
        self.is_default = not explicit
        self._networks = explicit or parse_networks(DEFAULT_ALLOWED)
        self._log_connections = log_connections
        self._seen: Set[str] = set()
        self._refused_at: Dict[str, float] = {}

    def describe(self) -> str:
        nets = ", ".join(str(n) for n in self._networks)
        kind = "home and local networks" if self.is_default else "from the setting"
        return f"{nets} ({kind}; this machine is always allowed)"

    def admit(self, peername) -> bool:
        """True if a client at this address may connect. Also logs it."""
        try:
            ip = _client_ip(peername)
        except ValueError:
            _LOGGER.warning("Refused a connection with an unreadable address: %r", peername)
            return False
        if ip is None:
            return True  # a local process on a unix socket
        text = str(ip)

        if ip.is_loopback:
            # Home Assistant's health check and discovery connect from here
            # all the time, so only mention it when debugging.
            _LOGGER.debug("Connection from %s (this machine)", text)
            return True

        if not any(ip in net for net in self._networks):
            self._log_refused(text)
            return False

        if self._log_connections:
            _LOGGER.info("Connection from %s", text)
        elif text not in self._seen and len(self._seen) < _MAX_TRACKED:
            self._seen.add(text)
            _LOGGER.info("New client address: %s", text)
        else:
            _LOGGER.debug("Connection from %s", text)
        return True

    def _log_refused(self, text: str) -> None:
        now = time.monotonic()
        last = self._refused_at.get(text)
        if last is not None and now - last < _REFUSED_LOG_INTERVAL:
            return
        if len(self._refused_at) >= _MAX_TRACKED:
            self._refused_at.clear()
        self._refused_at[text] = now
        _LOGGER.warning(
            "Refused a connection from %s: it is not in the allowed client "
            "addresses. If it is one of your devices, add it to the setting.",
            text,
        )
