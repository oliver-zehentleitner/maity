"""docs/api.md §11.1: the transport rule for every read the hub makes on its own.

The rules are tested against fake sockets: `outbound.resolver` answers with chosen
addresses, `outbound.connector` hands out a socket that replays a canned HTTP answer.
"""

from __future__ import annotations

import gzip
import io
import ipaddress
import threading
import time
from typing import Any

import pytest

from maity_hub import outbound

PUBLIC = ipaddress.ip_address("93.184.215.14")


class FakeSocket:
    """What http.client needs from a socket: sendall, makefile, settimeout, close."""

    def __init__(self, answer: bytes) -> None:
        self.answer = answer
        self.sent = b""

    def sendall(self, data: bytes) -> None:
        self.sent += data

    def makefile(self, mode: str, *args: Any, **kwargs: Any) -> io.BufferedReader:
        return io.BufferedReader(io.BytesIO(self.answer))

    def settimeout(self, value: float | None) -> None:
        pass

    def shutdown(self, how: int) -> None:
        pass

    def close(self) -> None:
        pass


def response(
    status: int = 200, body: bytes = b"hello", headers: dict[str, str] | None = None
) -> bytes:
    head = [f"HTTP/1.1 {status} X"]
    given = {"Content-Length": str(len(body)), **(headers or {})}
    head += [f"{k}: {v}" for k, v in given.items()]
    return ("\r\n".join(head) + "\r\n\r\n").encode() + body


class Net:
    """Resolves every host to the given addresses and answers with the queued responses."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.addresses: dict[str, list[Any]] = {}
        self.answers: list[bytes] = []
        self.resolved: list[str] = []
        self.connected: list[tuple[str, Any]] = []
        self.sockets: list[FakeSocket] = []
        monkeypatch.setattr(outbound, "resolver", self.resolve)
        monkeypatch.setattr(outbound, "connector", self.connect)

    def resolve(self, host: str) -> list[Any]:
        self.resolved.append(host)
        return self.addresses.get(host, [PUBLIC])

    def connect(self, host: str, address: Any, timeout: float) -> FakeSocket:
        self.connected.append((host, address))
        sock = FakeSocket(self.answers.pop(0))
        self.sockets.append(sock)
        return sock


@pytest.fixture
def net(monkeypatch: pytest.MonkeyPatch) -> Net:
    return Net(monkeypatch)


# --- which addresses may be read ------------------------------------------------------------


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "0.0.0.0",
        "10.1.2.3",
        "172.16.0.1",
        "192.168.1.1",
        "100.64.0.1",
        "169.254.169.254",
        "224.0.0.1",
        "239.255.255.250",
        "192.0.2.1",
        "198.51.100.7",
        "240.0.0.1",
        "255.255.255.255",
        "::1",
        "::",
        "fe80::1",
        "fc00::1",
        "fd12:3456::1",
        "ff02::1",
        "2001:db8::1",
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
        "2002:7f00:1::",
        "2002:a00:1::",
        "64:ff9b::7f00:1",
        "64:ff9b::a9fe:a9fe",
        "64:ff9b:1::a00:1",
        "fec0::1",
        "::a00:1",
        "::7f00:1",
        "::ffff:0:a00:1",
        "::ffff:0:7f00:1",
    ],
)
def test_addresses_that_are_not_globally_routable_are_refused(address: str) -> None:
    assert not outbound.routable(ipaddress.ip_address(address))


@pytest.mark.parametrize("address", ["93.184.215.14", "8.8.8.8", "2606:4700::1111"])
def test_public_addresses_may_be_read(address: str) -> None:
    assert outbound.routable(ipaddress.ip_address(address))


def test_one_private_address_among_several_refuses_the_read(net: Net) -> None:
    net.addresses["mixed.example"] = [PUBLIC, ipaddress.ip_address("10.0.0.5")]
    with pytest.raises(outbound.Refused) as refused:
        outbound.read("https://mixed.example/x", cap=100)
    assert refused.value.reason == "address_refused"
    assert net.connected == []


def test_the_read_connects_to_the_address_it_checked_and_resolves_once(net: Net) -> None:
    net.answers.append(response())
    answer = outbound.read("https://example.org/state.json", cap=100)
    assert (answer.status, answer.body) == (200, b"hello")
    assert net.resolved == ["example.org"]
    assert net.connected == [("example.org", PUBLIC)]


# --- the URL ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org/x",
        "https://example.org:8443/x",
        "https://user:pw@example.org/x",
        "ftp://example.org/x",
        "https:///x",
        "https://example.org:notaport/x",
    ],
)
def test_only_https_on_port_443_without_user_info(net: Net, url: str) -> None:
    with pytest.raises(outbound.Refused) as refused:
        outbound.read(url, cap=100)
    assert refused.value.reason == "url_invalid"
    assert net.resolved == []


def test_the_request_carries_the_user_agent_and_only_the_given_headers(net: Net) -> None:
    net.answers.append(response())
    outbound.read("https://example.org/a?b=c", cap=100, headers={"Accept": "application/json"})
    sent = net.sockets[0].sent.decode()
    assert sent.startswith("GET /a?b=c HTTP/1.1\r\n")
    assert "User-Agent: maity-hub\r\n" in sent
    assert "Accept: application/json\r\n" in sent
    assert "Authorization" not in sent and "Cookie" not in sent


# --- redirects -------------------------------------------------------------------------------


def test_a_redirect_on_the_same_host_is_followed(net: Net) -> None:
    net.answers += [response(301, b"", {"Location": "/moved"}), response(body=b"there")]
    answer = outbound.read("https://example.org/old", cap=100)
    assert answer.body == b"there"
    assert net.sockets[1].sent.startswith(b"GET /moved HTTP/1.1")
    assert net.resolved == ["example.org"]  # not resolved again


def test_more_than_three_redirects_are_refused(net: Net) -> None:
    net.answers += [response(302, b"", {"Location": f"/{n}"}) for n in range(4)]
    with pytest.raises(outbound.Refused) as refused:
        outbound.read("https://example.org/0", cap=100)
    assert refused.value.reason == "redirect_refused"
    assert len(net.connected) == 4


@pytest.mark.parametrize(
    "location",
    [
        "https://elsewhere.example/x",
        "http://example.org/x",
        "https://example.org:8443/x",
        "https://user@example.org/x",
    ],
)
def test_a_redirect_anywhere_else_is_refused(net: Net, location: str) -> None:
    net.answers.append(response(307, b"", {"Location": location}))
    with pytest.raises(outbound.Refused) as refused:
        outbound.read("https://example.org/x", cap=100)
    assert refused.value.reason == "redirect_refused"
    assert len(net.connected) == 1


# --- size, encoding, failures ----------------------------------------------------------------


def test_a_body_over_the_cap_is_refused(net: Net) -> None:
    net.answers.append(response(body=b"x" * 101))
    with pytest.raises(outbound.Refused) as refused:
        outbound.read("https://example.org/x", cap=100)
    assert refused.value.reason == "too_large"


def test_a_body_at_the_cap_is_read(net: Net) -> None:
    net.answers.append(response(body=b"x" * 100))
    assert outbound.read("https://example.org/x", cap=100).body == b"x" * 100


def test_the_cap_counts_decoded_bytes(net: Net) -> None:
    bomb = gzip.compress(b"\0" * 10_000_000)
    assert len(bomb) < 20_000
    net.answers.append(response(body=bomb, headers={"Content-Encoding": "gzip"}))
    with pytest.raises(outbound.Refused) as refused:
        outbound.read("https://example.org/x", cap=1024 * 1024)
    assert refused.value.reason == "too_large"


def test_a_gzip_answer_is_decoded(net: Net) -> None:
    net.answers.append(response(body=gzip.compress(b"{}"), headers={"Content-Encoding": "gzip"}))
    assert outbound.read("https://example.org/x", cap=100).body == b"{}"


@pytest.mark.parametrize("coding", ["br", "deflate"])
def test_an_encoding_the_hub_did_not_ask_for_is_refused(net: Net, coding: str) -> None:
    net.answers.append(response(body=b"x", headers={"Content-Encoding": coding}))
    with pytest.raises(outbound.Refused) as refused:
        outbound.read("https://example.org/x", cap=100)
    assert refused.value.reason == "unavailable"


def test_a_chunked_answer_is_read(net: Net) -> None:
    raw = b"HTTP/1.1 200 X\r\nTransfer-Encoding: chunked\r\n\r\n3\r\nabc\r\n2\r\nde\r\n0\r\n\r\n"
    net.answers.append(raw)
    assert outbound.read("https://example.org/x", cap=100).body == b"abcde"


def test_an_error_status_is_an_answer_for_the_caller(net: Net) -> None:
    net.answers.append(response(404, b"not here"))
    assert outbound.read("https://example.org/x", cap=100).status == 404


@pytest.mark.parametrize(
    ("error", "reason"),
    [(TimeoutError(), "timeout"), (ConnectionRefusedError(), "unavailable")],
)
def test_a_failed_connection_is_a_reason_code(
    monkeypatch: pytest.MonkeyPatch, net: Net, error: Exception, reason: str
) -> None:
    def fail(host: str, address: Any, timeout: float) -> None:
        raise error

    monkeypatch.setattr(outbound, "connector", fail)
    with pytest.raises(outbound.Refused) as refused:
        outbound.read("https://example.org/x", cap=100)
    assert refused.value.reason == reason


def test_a_garbled_answer_is_unavailable_and_quotes_nothing(net: Net) -> None:
    net.answers.append(b"SECRET-UPSTREAM-TEXT\r\n\r\n")
    with pytest.raises(outbound.Refused) as refused:
        outbound.read("https://example.org/x", cap=100)
    assert refused.value.reason == "unavailable"
    assert "SECRET" not in str(refused.value)


def test_tests_never_reach_the_network() -> None:
    with pytest.raises(outbound.Refused):
        outbound.read("https://example.org/x", cap=100)


class DrippingSocket(FakeSocket):
    """A server that sends its status line, then one header byte at a time, forever; a
    close from another thread ends the read like a closed socket does."""

    def __init__(self) -> None:
        super().__init__(b"")
        self.closed = threading.Event()

    def makefile(self, mode: str, *args: Any, **kwargs: Any) -> Any:
        sock = self

        class Drip(io.RawIOBase):
            status = list(b"HTTP/1.1 200 X\r\n")

            def readable(self) -> bool:
                return True

            def readinto(self, buffer: Any) -> int:
                if self.status:
                    buffer[0] = self.status.pop(0)
                    return 1
                if sock.closed.wait(0.05):
                    raise OSError("closed")
                buffer[0] = ord("X")
                return 1

        return io.BufferedReader(Drip(), buffer_size=1)

    def shutdown(self, how: int) -> None:
        self.closed.set()

    def close(self) -> None:
        self.closed.set()


def test_a_server_that_drips_its_headers_meets_the_total_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(outbound, "TIMEOUT", 0.5)
    monkeypatch.setattr(outbound, "resolver", lambda host: [PUBLIC])
    monkeypatch.setattr(outbound, "connector", lambda host, address, timeout: DrippingSocket())
    started = time.monotonic()
    with pytest.raises(outbound.Refused) as refused:
        outbound.read("https://example.org/x", cap=100)
    assert refused.value.reason == "timeout"
    assert time.monotonic() - started < 2
