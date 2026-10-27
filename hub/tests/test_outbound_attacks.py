"""Attacks on the outbound reads and the image routes (docs/api.md §11.1, §11.2), from the
adversarial review of the logo and banner slice; kept as regressions."""

from __future__ import annotations

import contextlib
import gzip
import ipaddress
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from sqlalchemy import Engine

from maity_hub import forge, outbound
from tests import flow
from tests.conftest import ClientFactory
from tests.test_project_images import PNG, REPO, FakeForge, put

PUBLIC = ipaddress.ip_address("93.184.215.14")


# --- a real loopback server, plain TCP (TLS is not under test) -----------------------------


class Server:
    def __init__(self, handler: Any) -> None:
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.handler = handler
        self.requests: list[bytes] = []
        self.stop = False
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        while not self.stop:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._one, args=(conn,), daemon=True).start()

    def _one(self, conn: socket.socket) -> None:
        data = b""
        conn.settimeout(5)
        try:
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            self.requests.append(data)
            self.handler(conn)
        except OSError:
            pass
        finally:
            with contextlib.suppress(OSError):
                conn.close()

    def close(self) -> None:
        self.stop = True
        self.sock.close()


def wire(
    monkeypatch: pytest.MonkeyPatch, server: Server, addresses: list[Any] | None = None
) -> dict[str, Any]:
    seen: dict[str, Any] = {"resolved": [], "connected": []}

    def resolve(host: str) -> list[Any]:
        seen["resolved"].append(host)
        return addresses or [PUBLIC]

    def connect(host: str, address: Any, timeout: float) -> socket.socket:
        seen["connected"].append((host, address, timeout))
        return socket.create_connection(("127.0.0.1", server.port), timeout)

    monkeypatch.setattr(outbound, "resolver", resolve)
    monkeypatch.setattr(outbound, "connector", connect)
    return seen


def test_slowloris_headers_exceed_total_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(outbound, "TIMEOUT", 2.0)
    head = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"

    def drip(conn: socket.socket) -> None:
        for b in head:
            conn.sendall(bytes([b]))
            time.sleep(0.25)

    server = Server(drip)
    wire(monkeypatch, server)
    start = time.monotonic()
    try:
        outcome: Any = outbound.read("https://example.org/x", cap=1024)
    except outbound.Refused as refused:
        outcome = refused.reason
    elapsed = time.monotonic() - start
    server.close()
    print("HEADER-DRIP", outcome, round(elapsed, 2), "deadline 2.0")
    assert elapsed < 3.0, f"header slowloris ran {elapsed:.1f}s past a 2 s deadline: {outcome}"


def test_slowloris_body_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(outbound, "TIMEOUT", 2.0)

    def drip(conn: socket.socket) -> None:
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n")
        for _ in range(100):
            conn.sendall(b"x")
            time.sleep(0.25)

    server = Server(drip)
    wire(monkeypatch, server)
    start = time.monotonic()
    with pytest.raises(outbound.Refused) as refused:
        outbound.read("https://example.org/x", cap=1024)
    elapsed = time.monotonic() - start
    server.close()
    print("BODY-DRIP", refused.value.reason, round(elapsed, 2))
    assert elapsed < 3.0


def test_slowloris_chunked_body_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(outbound, "TIMEOUT", 2.0)

    def drip(conn: socket.socket) -> None:
        conn.sendall(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n")
        # one chunk whose size line and payload arrive byte by byte
        for b in b"64\r\n" + b"x" * 100 + b"\r\n0\r\n\r\n":
            conn.sendall(bytes([b]))
            time.sleep(0.25)

    server = Server(drip)
    wire(monkeypatch, server)
    start = time.monotonic()
    try:
        outcome: Any = outbound.read("https://example.org/x", cap=1024)
    except outbound.Refused as refused:
        outcome = refused.reason
    elapsed = time.monotonic() - start
    server.close()
    print("CHUNK-DRIP", outcome, round(elapsed, 2))
    assert elapsed < 3.0, f"chunked drip ran {elapsed:.1f}s"


def test_endless_body_and_gzip_bomb(monkeypatch: pytest.MonkeyPatch) -> None:
    bomb = gzip.compress(b"\0" * (512 * 1024 * 1024), compresslevel=9)

    def endless(conn: socket.socket) -> None:
        conn.sendall(b"HTTP/1.1 200 OK\r\n\r\n")
        while True:
            conn.sendall(b"y" * 65536)

    def bombing(conn: socket.socket) -> None:
        conn.sendall(
            b"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\nContent-Length: "
            + str(len(bomb)).encode()
            + b"\r\n\r\n"
            + bomb
        )

    for handler in (endless, bombing):
        server = Server(handler)
        wire(monkeypatch, server)
        start = time.monotonic()
        with pytest.raises(outbound.Refused) as refused:
            outbound.read("https://example.org/x", cap=1024 * 1024)
        print(handler.__name__, refused.value.reason, round(time.monotonic() - start, 2), len(bomb))
        assert refused.value.reason == "too_large"
        server.close()


def test_truncated_gzip_and_multi_member(monkeypatch: pytest.MonkeyPatch) -> None:
    whole = gzip.compress(PNG * 100)
    for name, body in (
        ("truncated", whole[: len(whole) // 2]),
        ("two-members", gzip.compress(PNG) + gzip.compress(b"<script>")),
    ):

        def send(conn: socket.socket, body: bytes = body) -> None:
            conn.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\nContent-Length: "
                + str(len(body)).encode()
                + b"\r\n\r\n"
                + body
            )

        server = Server(send)
        wire(monkeypatch, server)
        try:
            a = outbound.read("https://example.org/x", cap=1024 * 1024)
            print(name, "ANSWER", a.status, len(a.body))
        except outbound.Refused as r:
            print(name, "REFUSED", r.reason)
        server.close()


def test_redirects_reuse_checked_address_and_never_resolve_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    n = {"i": 0}

    def hop(conn: socket.socket) -> None:
        n["i"] += 1
        if n["i"] < 3:
            conn.sendall(b"HTTP/1.1 302 F\r\nLocation: /next\r\nContent-Length: 0\r\n\r\n")
        else:
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")

    server = Server(hop)
    seen = wire(monkeypatch, server)
    assert outbound.read("https://example.org/x", cap=10).body == b"ok"
    print("RESOLVED", seen["resolved"], "CONNECTED", [(h, str(a)) for h, a, _ in seen["connected"]])
    assert seen["resolved"] == ["example.org"]
    assert {str(a) for _h, a, _t in seen["connected"]} == {str(PUBLIC)}
    server.close()


@pytest.mark.parametrize(
    "location",
    [
        "http://example.org/x",
        "https://example.org:8443/x",
        "https://127.0.0.1/x",
        "https://169.254.169.254/latest/meta-data/",
        "//evil.example/x",
        "https://example.org.evil.example/x",
        "https://example.org@evil.example/x",
        "https://evil.example\\@example.org/x",
        "https://example.org./x",
        "https://[::ffff:10.0.0.1]/x",
        "ftp://example.org/x",
    ],
)
def test_redirect_elsewhere(monkeypatch: pytest.MonkeyPatch, location: str) -> None:
    def redirect(conn: socket.socket) -> None:
        conn.sendall(
            f"HTTP/1.1 302 F\r\nLocation: {location}\r\nContent-Length: 0\r\n\r\n".encode()
        )

    server = Server(redirect)
    seen = wire(monkeypatch, server)
    with pytest.raises(outbound.Refused) as refused:
        outbound.read("https://example.org/x", cap=10)
    assert refused.value.reason == "redirect_refused"
    assert len(seen["connected"]) == 1
    server.close()


# --- the real resolver on literal and local names ------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "2130706433",
        "0x7f000001",
        "0177.0.0.1",
        "0x7f.1",
        "127.1",
        "0",
        "0.0.0.0",
        "localhost",
        "LOCALHOST",
        "localhost.",
        "[::1]",
        "[::]",
        "[::ffff:10.0.0.1]",
        "[::ffff:a00:1]",
        "[::ffff:127.0.0.1]",
        "[fe80::1%25lo]",
        "[fe80::1%lo]",
        "169.254.169.254",
        "[::ffff:169.254.169.254]",
        "[64:ff9b::a9fe:a9fe]",
        "[2002:a9fe:a9fe::1]",
        "[2001:0:4136:e378:8000:63bf:56fe:5ef5]",
        "100.64.0.1",
        "[fd00::1]",
        "10.0.0.1",
        "192.168.1.1",
        "172.16.0.1",
        "224.0.0.1",
        "240.0.0.1",
        "192.0.2.1",
        "[::127.0.0.1]",
        "[0:0:0:0:0:ffff:0a00:0001]",
        "[64:ff9b:1::a00:1]",
        "[2001:db8::1]",
    ],
)
def test_real_resolver_refuses_local(monkeypatch: pytest.MonkeyPatch, host: str) -> None:
    monkeypatch.setattr(outbound, "resolver", outbound._resolve)
    called: list[Any] = []
    monkeypatch.setattr(outbound, "connector", lambda *a: called.append(a))
    with pytest.raises(outbound.Refused) as refused:
        outbound.read(f"https://{host}/x", cap=10)
    print(host, refused.value.reason)
    assert refused.value.reason in ("address_refused", "url_invalid", "unavailable")
    assert called == []


def test_ipv6_literal_host_is_mangled_into_a_port(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []

    def connect(host: str, address: Any, timeout: float) -> Any:
        seen.append(host)
        raise OSError("stop")

    monkeypatch.setattr(outbound, "resolver", lambda h: [ipaddress.ip_address("2606:4700::1111")])
    monkeypatch.setattr(outbound, "connector", connect)
    with pytest.raises(outbound.Refused):
        outbound.read("https://[2606:4700::1111]/x", cap=10)
    print("CONNECT HOST", seen)


# --- the app ---------------------------------------------------------------------------------


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)


def test_no_token_to_the_image_host(
    owner: flow.Human, monkeypatch: pytest.MonkeyPatch, make_client: ClientFactory
) -> None:

    def avatar(self: forge.Forge, repository: str) -> str:
        assert self.token is not None  # the hub holds one
        return "https://avatars.githubusercontent.com/u/1?v=4"

    def answer(conn: socket.socket) -> None:
        conn.sendall(
            b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: "
            + str(len(PNG)).encode()
            + b"\r\n\r\n"
            + PNG
        )

    server = Server(answer)
    wire(monkeypatch, server)
    monkeypatch.setattr(forge.Forge, "owner_avatar", avatar)
    reader = forge.Forge(token="ghp_SECRETTOKEN")
    monkeypatch.setattr("maity_hub.routes.project_images.reader_of", lambda _r: reader)
    flow.project(owner, "maity", repository={"url": REPO})
    got = owner.get("/projects/maintainer/maity/logo")
    print("STATUS", got.status_code, dict(got.headers))
    print("REQUEST", server.requests)
    assert got.status_code == 200
    assert got.headers["content-type"] == "image/png"
    assert all(b"SECRETTOKEN" not in r and b"uthorization" not in r for r in server.requests)
    server.close()


def test_response_headers_and_etag(owner: flow.Human) -> None:
    flow.project(owner, "maity")
    put(owner, "/projects/maintainer/maity/logo", PNG + b"<script>alert(1)</script>", "image/png")
    got = owner.get("/projects/maintainer/maity/logo")
    h = got.headers
    print("HEADERS", h.multi_items())
    assert h["content-type"] == "image/png"
    assert h["x-content-type-options"] == "nosniff"
    assert h["content-security-policy"] == "default-src 'none'; sandbox"
    assert h["cross-origin-resource-policy"] == "same-origin"
    assert h["cache-control"] == "private, max-age=21600"
    tag = h["etag"]
    for inm, expect in (
        (tag, 304),
        (f"W/{tag}", 304),
        ('"nope", ' + tag, 304),
        ("*", 304),
        ('"nope"', 200),
        (tag.strip('"'), 200),
    ):
        r = owner.client.get(
            "/api/v1/projects/maintainer/maity/logo", headers={"If-None-Match": inm}
        )
        print("INM", inm, r.status_code, len(r.content))
        assert r.status_code == expect
    missing = owner.get("/projects/maintainer/maity/banner")
    print("404 cache", missing.headers.get("cache-control"))
    assert missing.headers["cache-control"] == "no-store"


def test_declared_svg_or_mismatch(owner: flow.Human) -> None:
    flow.project(owner, "maity")
    svg_as_png = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    for data, ctype in (
        (svg_as_png, "image/png"),
        (PNG, "image/svg+xml"),
        (PNG, "image/jpeg"),
        (PNG, "IMAGE/PNG; charset=utf-8"),
        (PNG, "text/html"),
        (b"RIFF\0\0\0\0WAVEfmt ", "image/webp"),
        (b"", "image/png"),
    ):
        r = put(owner, "/projects/maintainer/maity/logo", data, ctype)
        print("PUT", ctype, data[:8], r.status_code, r.text[:120])


def test_project_isolation(owner: flow.Human, make_client: ClientFactory, migrated: Engine) -> None:
    flow.project(owner, "alpha")
    flow.project(owner, "beta")
    put(owner, "/projects/maintainer/alpha/logo", PNG, "image/png")
    assert owner.get("/projects/maintainer/beta/logo").status_code == 404
    stranger = flow.human(make_client, migrated, "stranger")
    r = stranger.get("/projects/maintainer/alpha/logo")
    print("STRANGER", r.status_code)
    assert r.status_code in (403, 404)


def test_long_poll_not_woken_by_upload(owner: flow.Human, make_client: ClientFactory) -> None:
    flow.project(owner, "maity")
    agent = flow.agent(make_client, owner)
    cursor = agent.get("/projects/maintainer/maity/events?after=latest").json()["cursor"]
    with ThreadPoolExecutor(max_workers=1) as pool:
        start = time.monotonic()
        waiting = pool.submit(agent.get, f"/projects/maintainer/maity/events?after={cursor}&wait=3")
        time.sleep(0.5)
        assert put(owner, "/projects/maintainer/maity/logo", PNG, "image/png").status_code == 200
        body = waiting.result(timeout=10).json()
    elapsed = time.monotonic() - start
    print("LONGPOLL", round(elapsed, 2), body)
    assert elapsed >= 2.8 and body["items"] == []
    plain = agent.get(f"/projects/maintainer/maity/events?after={cursor}").json()
    print("PLAIN", [e["kind"] for e in plain["items"]])
    assert "project_updated" in [e["kind"] for e in plain["items"]]


def test_read_through_amplification(owner: flow.Human, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeForge(monkeypatch)
    fake.forge_down = True
    flow.project(owner, "maity", repository={"url": REPO})
    codes = [owner.get("/projects/maintainer/maity/logo").status_code for _ in range(5)]
    print("CODES", codes, "FORGE READS", len(fake.reads), fake.reads)


def test_concurrent_first_uploads(owner: flow.Human) -> None:
    from tests.test_project_images import JPEG

    codes: list[int] = []
    for i in range(15):
        slug = f"race{i}"
        flow.project(owner, slug)
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(put, owner, f"/projects/maintainer/{slug}/logo", PNG, "image/png")
            b = pool.submit(put, owner, f"/projects/maintainer/{slug}/logo", JPEG, "image/jpeg")
            codes += [a.result().status_code, b.result().status_code]
    print("RACE", codes)
    assert set(codes) == {200}


@pytest.mark.parametrize(
    "answer",
    [
        b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n" + b"x" * 10,
        b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n64\r\n" + b"x" * 10,
    ],
)
def test_a_body_cut_short_is_refused(monkeypatch: pytest.MonkeyPatch, answer: bytes) -> None:
    # The stream ending before the declared length is no answer: the watchdog closing the
    # socket at the deadline ends a read the same way, and a part is never the body.
    def short(conn: socket.socket) -> None:
        conn.sendall(answer)
        conn.close()

    server = Server(short)
    wire(monkeypatch, server)
    with pytest.raises(outbound.Refused) as refused:
        outbound.read("https://example.org/x", cap=1024)
    server.close()
    assert refused.value.reason == "unavailable"
