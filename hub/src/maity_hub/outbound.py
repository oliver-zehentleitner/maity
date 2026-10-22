"""Every read the hub makes on its own, under one transport rule (docs/api.md §11.1).

- `https` on port 443, the TLS certificate verified against the host name;
- one fixed host per read: redirects are followed only to `https` on the same host and
  port, at most `MAX_REDIRECTS` times, and any other redirect ends the read;
- the host is resolved once, every resolved address must be globally routable, and the
  connection goes to the address that was checked, so a second resolution cannot point the
  read somewhere else;
- `TIMEOUT` seconds from connect to last byte, and the body capped at `cap` decoded bytes;
- a failure is a reason code (`Refused.reason`), never the upstream's body or error text.

A caller that holds a token passes it in `headers` and only for a host it chose; this
module adds nothing but `User-Agent: maity-hub`. The probe's reads (forge.py) go only to the
forge's fixed API host, which satisfies the rule as it is; this module is for the reads whose
host comes from data or from the forge's answers.
"""

from __future__ import annotations

import contextlib
import http.client
import ipaddress
import socket
import ssl
import threading
import time
import urllib.parse
import zlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

PORT = 443
TIMEOUT = 10.0
MAX_REDIRECTS = 3
USER_AGENT = "maity-hub"
CHUNK = 64 * 1024

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

_NAT64 = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))
# The low 32 bits of these are an IPv4 address: IPv4-compatible (::/96, deprecated) and
# IPv4-translated (RFC 2765). `ipaddress` unwraps neither.
_WRAPPED_V4 = (ipaddress.ip_network("::/96"), ipaddress.ip_network("::ffff:0:0:0/96"))
_SITE_LOCAL = ipaddress.ip_network("fec0::/10")  # deprecated, still local, and `is_global`


class Refused(Exception):
    """The read did not produce an answer. `reason` is one of `address_refused`,
    `redirect_refused`, `timeout`, `http_status` (with `status`), `too_large`,
    `unavailable` (connect, TLS or protocol failure) or `url_invalid`."""

    def __init__(self, reason: str, status: int | None = None) -> None:
        super().__init__(reason if status is None else f"{reason} {status}")
        self.reason = reason
        self.status = status


@dataclass(frozen=True)
class Answer:
    status: int
    headers: Mapping[str, str] = field(repr=False)
    body: bytes = field(repr=False)


def _embedded(ip: IPAddress) -> ipaddress.IPv4Address | None:
    """The IPv4 address an IPv6 address carries: mapped, 6to4, NAT64 or Teredo."""
    if not isinstance(ip, ipaddress.IPv6Address):
        return None
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip.sixtofour is not None:
        return ip.sixtofour
    if ip.teredo is not None:
        return ip.teredo[1]
    if any(ip in net for net in (*_NAT64, *_WRAPPED_V4)):
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def routable(ip: IPAddress) -> bool:
    """Globally routable, and so is every IPv4 address it wraps. Python's `is_global`
    counts multicast and the NAT64 prefix as global; neither may be read from."""
    if not ip.is_global or ip.is_multicast or ip in _SITE_LOCAL:
        return False
    inner = _embedded(ip)
    return inner is None or routable(inner)


def _resolve(host: str) -> list[IPAddress]:
    try:
        infos = socket.getaddrinfo(host, PORT, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        raise Refused("unavailable") from None
    found: list[IPAddress] = []
    for _family, _type, _proto, _name, sockaddr in infos:
        ip = ipaddress.ip_address(str(sockaddr[0]).split("%", 1)[0])
        if ip not in found:
            found.append(ip)
    if not found:
        raise Refused("unavailable")
    return found


def _connect(host: str, address: IPAddress, timeout: float) -> socket.socket:
    """A TLS socket to the checked address, with SNI and certificate verification against
    the host name."""
    sock = socket.create_connection((str(address), PORT), timeout)
    try:
        return ssl.create_default_context().wrap_socket(sock, server_hostname=host)
    except BaseException:
        sock.close()
        raise


# The two seams tests replace: name resolution and the connection. Production code never
# changes them; conftest.py makes both refuse, so no test reaches the network.
resolver: Callable[[str], list[IPAddress]] = _resolve
connector: Callable[[str, IPAddress, float], Any] = _connect


class _Connection(http.client.HTTPSConnection):
    """An HTTPS connection to a checked address, never a second resolution."""

    def __init__(self, host: str, address: IPAddress, timeout: float) -> None:
        super().__init__(host, PORT, timeout=timeout)
        self._address = address

    def connect(self) -> None:
        self.sock = connector(self.host, self._address, self.timeout or TIMEOUT)


def _target(url: str) -> tuple[str, str]:
    """(host, path with query) of an https URL on port 443; `url_invalid` otherwise."""
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        raise Refused("url_invalid") from None
    if parts.scheme != "https" or not parts.hostname or port not in (None, PORT):
        raise Refused("url_invalid")
    if parts.username is not None or parts.password is not None:
        raise Refused("url_invalid")
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return parts.hostname.lower(), path


def _decoder(encoding: str) -> zlib._Decompress | None:
    encoding = encoding.strip().lower()
    if encoding in ("", "identity"):
        return None
    if encoding in ("gzip", "x-gzip"):
        return zlib.decompressobj(16 + zlib.MAX_WBITS)
    raise Refused("unavailable")  # a coding the hub did not ask for: it asks for gzip only


def _body(response: http.client.HTTPResponse, cap: int, deadline: float, sock: Any) -> bytes:
    """The body, decoded, refused at the first byte past `cap`. Decompression is bounded
    per step, so a small compressed answer cannot expand far past the cap in memory."""
    decoder = _decoder(response.getheader("Content-Encoding") or "")
    out = bytearray()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise Refused("timeout")
        if sock is not None:
            sock.settimeout(remaining)
        chunk = response.read1(CHUNK)
        if not chunk:
            # A gzip answer must end where its stream ends: a truncated stream or a second
            # member after the first is not the body the server meant.
            if decoder is not None and (not decoder.eof or decoder.unused_data):
                raise Refused("unavailable")
            return bytes(out)
        if decoder is None:
            out += chunk
        else:
            pending = chunk
            while pending and len(out) <= cap:
                out += decoder.decompress(pending, cap + 1 - len(out))
                pending = decoder.unconsumed_tail
        if len(out) > cap:
            raise Refused("too_large")


def read(
    url: str,
    *,
    cap: int,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
    body: bytes | None = None,
    host: str | None = None,
) -> Answer:
    """One read under the transport rule. Any status the server answers with is returned,
    errors included; the caller decides what a 404 means. `host`, when given, is the only
    host the URL may name (`url_invalid` otherwise)."""
    expected = host
    host, path = _target(url)
    if expected is not None and host != expected.lower():
        raise Refused("url_invalid")
    addresses = resolver(host)
    if not all(routable(ip) for ip in addresses):
        raise Refused("address_refused")
    deadline = time.monotonic() + TIMEOUT
    sent = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip", **(headers or {})}
    for _hop in range(MAX_REDIRECTS + 1):
        answer, location = _one(host, addresses[0], method, path, sent, body, cap, deadline)
        if location is None:
            return answer
        next_host, path = _redirect(url, location, host)
        url = f"https://{next_host}{path}"
        if method == "POST" and answer.status in (301, 302, 303):
            method, body = "GET", None
    raise Refused("redirect_refused")


def _redirect(base: str, location: str, host: str) -> tuple[str, str]:
    try:
        target_host, path = _target(urllib.parse.urljoin(base, location))
    except Refused:
        raise Refused("redirect_refused") from None
    if target_host != host:
        raise Refused("redirect_refused")
    return target_host, path


def _one(
    host: str,
    address: IPAddress,
    method: str,
    path: str,
    headers: Mapping[str, str],
    body: bytes | None,
    cap: int,
    deadline: float,
) -> tuple[Answer, str | None]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise Refused("timeout")
    connection = _Connection(host, address, timeout=remaining)
    # A per-recv timeout is no total deadline: a server that drips its headers a byte at
    # a time would keep the read open. The watchdog closes the socket at the deadline.
    watchdog = threading.Timer(remaining, _expire, (connection,))
    watchdog.daemon = True
    watchdog.start()
    try:
        connection.request(method, path, body=body, headers=dict(headers))
        if connection.sock is not None:
            connection.sock.settimeout(max(deadline - time.monotonic(), 0.001))
        response = connection.getresponse()
        if response.status in (301, 302, 303, 307, 308):
            location = response.getheader("Location")
            if not location:
                raise Refused("redirect_refused")
            return Answer(response.status, {}, b""), location
        data = _body(response, cap, deadline, connection.sock)
        found = {k.lower(): v for k, v in response.getheaders()}
        return Answer(response.status, found, data), None
    except Refused:
        raise
    except TimeoutError:
        raise Refused("timeout") from None
    except (OSError, ssl.SSLError, http.client.HTTPException, zlib.error, ValueError):
        if time.monotonic() >= deadline:
            raise Refused("timeout") from None
        raise Refused("unavailable") from None
    finally:
        watchdog.cancel()
        connection.close()


def _expire(connection: http.client.HTTPConnection) -> None:
    """The deadline passed: close the socket under whatever read is blocked on it."""
    sock = connection.sock
    if sock is not None:
        with contextlib.suppress(OSError):
            sock.shutdown(socket.SHUT_RDWR)
        with contextlib.suppress(OSError):
            sock.close()
