"""Who is calling, and over what: the client address and scheme (docs/api.md §2.5).

Forwarded headers count only when the socket peer is a trusted proxy;
otherwise a client could claim TLS or another address with one header.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass

from starlette.types import Scope

from maity_hub.config import IPNetwork


@dataclass(frozen=True)
class Origin:
    address: str
    scheme: str  # http or https

    @property
    def loopback(self) -> bool:
        try:
            return ipaddress.ip_address(self.address).is_loopback
        except ValueError:
            return False

    @property
    def tls(self) -> bool:
        return self.scheme == "https"

    @property
    def limit_key(self) -> str:
        """The key of every limit per source address (§2.5): an IPv4 address as it is, an
        IPv6 address as its /64, which one client usually holds whole; an IPv4-mapped IPv6
        address as its IPv4. Anything else stays as it is. What is recorded or shown of the
        caller (a session's address, a mail) stays `address`."""
        return limit_key(self.address)


def limit_key(address: str) -> str:
    """`Origin.limit_key` of an address."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return address
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        return str(ipaddress.IPv6Network((int(ip) >> 64 << 64, 64)))  # no zone, if any
    return str(ip)


def _values(scope: Scope, name: bytes) -> list[str]:
    """Every comma-separated value of every line of a header, in order: a proxy
    that appends a second line must not leave the client's first line in charge."""
    values: list[str] = []
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            values += [v.strip() for v in value.decode("latin-1").split(",") if v.strip()]
    return values


def _trusted(address: str, proxies: tuple[IPNetwork, ...]) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in network for network in proxies)


def resolve(scope: Scope, proxies: tuple[IPNetwork, ...]) -> Origin:
    client = scope.get("client")
    peer = client[0] if client else ""
    scheme = str(scope.get("scheme", "http"))
    if not _trusted(peer, proxies):
        return Origin(peer, scheme)
    hops = _values(scope, b"x-forwarded-for")
    protos = [p.lower() for p in _values(scope, b"x-forwarded-proto")]
    # Each proxy appends one hop and one scheme. Walk from the trusted end; the
    # first hop that is not one of our proxies is the client, and the scheme it
    # spoke is the one recorded at that same position, counted from the right.
    address, depth = peer, 0
    while depth < len(hops):
        depth += 1
        address = hops[-depth]
        if not _trusted(address, proxies):
            break
    if protos and depth:
        index = len(protos) - depth
        scheme = protos[index] if 0 <= index < len(protos) else protos[0]
    elif protos:
        scheme = protos[-1]
    return Origin(address, scheme if scheme in ("http", "https") else "http")
