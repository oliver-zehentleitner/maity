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


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return str(value.decode("latin-1"))
    return None


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
    forwarded_proto = _header(scope, b"x-forwarded-proto")
    forwarded_for = _header(scope, b"x-forwarded-for")
    if forwarded_proto:
        scheme = forwarded_proto.split(",")[0].strip().lower()
    address = peer
    if forwarded_for:
        # Walk from the right past our own proxies; the first untrusted hop is the client.
        hops = [hop.strip() for hop in forwarded_for.split(",") if hop.strip()]
        for hop in reversed(hops):
            address = hop
            if not _trusted(hop, proxies):
                break
    return Origin(address, scheme if scheme in ("http", "https") else "http")
