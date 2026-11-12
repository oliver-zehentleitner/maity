"""docs/api.md §1 and §2.2's credential filter: what every request and response obeys."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest
from fastapi import Request
from sqlalchemy import Engine, select
from starlette.routing import Mount

from maity_hub import body as body_reader
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory

SERVER_TIME = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")


def test_every_response_carries_the_server_time_and_no_store(make_client: ClientFactory) -> None:
    client = make_client()
    for path in ("/api/v1/health", "/api/v1/help", "/api/v1/nope"):
        response = client.get(path)
        assert SERVER_TIME.match(response.headers["Maity-Server-Time"]), path
        assert response.headers["Cache-Control"] == "no-store", path
        assert response.headers["X-Content-Type-Options"] == "nosniff", path
    # The app shell is the one answer that is `no-cache`: small, and it follows a deploy.
    shell = client.get("/")
    assert SERVER_TIME.match(shell.headers["Maity-Server-Time"])
    assert shell.headers["Cache-Control"] == "no-cache"
    assert shell.headers["X-Content-Type-Options"] == "nosniff"


def test_html_gets_the_content_security_policy_and_json_does_not(
    make_client: ClientFactory,
) -> None:
    client = make_client()
    assert client.get("/").headers["Content-Security-Policy"] == "default-src 'self'"
    assert "Content-Security-Policy" not in client.get("/api/v1/health").headers


def test_an_unknown_path_is_the_not_found_envelope(make_client: ClientFactory) -> None:
    response = make_client().get("/api/v1/nope")
    assert response.status_code == 404
    assert response.headers["Maity-Error"] == "not_found"
    assert response.json() == {
        "error": {"code": "not_found", "message": "no such resource", "details": {}}
    }


def test_unknown_fields_are_invalid_with_the_field_named(make_client: ClientFactory) -> None:
    response = make_client().post(
        "/api/v1/auth/login", json={"email": "x", "password": "y", "extra": 1}
    )
    assert response.status_code == 400
    assert response.headers["Maity-Error"] == "invalid"
    assert response.json()["error"]["details"]["fields"] == {"extra": "extra_forbidden"}


def test_a_validation_error_never_quotes_the_input(make_client: ClientFactory) -> None:
    response = make_client().post("/api/v1/auth/login", json={"email": "", "password": "s3cr3t"})
    assert response.status_code == 400
    assert "s3cr3t" not in response.text


def test_a_body_over_64_kib_is_refused(make_client: ClientFactory) -> None:
    response = make_client().post(
        "/api/v1/auth/login",
        content=b"x" * (64 * 1024 + 1),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.headers["Maity-Error"] == "payload_too_large"


def test_a_body_to_an_api_path_nothing_serves_is_404_unread(make_client: ClientFactory) -> None:
    client = make_client()
    big = client.post(
        "/api/v1/projects/maintainer/maity/nothing-serves-this",
        content=b"x" * (64 * 1024 + 1),
        headers={"Content-Type": "application/octet-stream"},
    )
    assert (big.status_code, big.headers["Maity-Error"]) == (404, "not_found")
    # The known path with another method stays routed: the cap answers first (405 after).
    wrong_method = client.put(
        "/api/v1/auth/login", content=b"x" * (64 * 1024 + 1), headers={"Content-Type": "x/y"}
    )
    assert wrong_method.status_code == 413
    # A path that differs by its trailing slash is routed: the router redirects it.
    for slashed in ("/api/v1/health/", "/api/v1/health//"):
        slash = client.get(slashed, follow_redirects=False)
        assert slash.status_code == 307, slashed

    async def never_read() -> dict[str, object]:
        raise AssertionError("the body of an unrouted path was read")

    sent: list[dict[str, object]] = []

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    scope = {
        "type": "http", "http_version": "1.1", "method": "POST", "scheme": "https",
        "path": "/api/v1/nowhere", "raw_path": b"/api/v1/nowhere", "root_path": "",
        "query_string": b"", "server": ("hub.example", 443), "client": ("203.0.113.7", 1),
        "headers": [(b"host", b"hub.example"), (b"content-length", b"1000000000")],
    }  # fmt: skip
    flow.drive(client, scope, never_read, send)
    assert sent[0]["status"] == 404


def test_a_body_that_does_not_arrive_in_time_is_request_timeout(
    make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(body_reader, "BODY_SECONDS", 0.2)
    client = make_client()
    chunks = 0

    async def slow() -> dict[str, object]:
        nonlocal chunks
        chunks += 1
        if chunks > 1:
            await asyncio.sleep(0.15)  # each chunk in time, all of them not
        # Ends after three: a deadline per chunk would let it through and answer otherwise.
        return {"type": "http.request", "body": b"{", "more_body": chunks < 3}

    sent: list[dict[str, object]] = []

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    scope = {
        "type": "http", "http_version": "1.1", "method": "POST", "scheme": "https",
        "path": "/api/v1/auth/login", "raw_path": b"/api/v1/auth/login", "root_path": "",
        "query_string": b"", "server": ("hub.example", 443), "client": ("203.0.113.7", 1),
        "headers": [(b"host", b"hub.example"), (b"content-type", b"application/json")],
    }  # fmt: skip
    flow.drive(client, scope, slow, send)
    headers = dict(sent[0]["headers"])  # type: ignore[call-overload]
    assert (sent[0]["status"], headers[b"maity-error"]) == (408, b"request_timeout")
    assert headers[b"connection"] == b"close"
    assert chunks >= 2  # a chunk in time does not restart the clock


def test_a_steady_body_inside_the_deadline_is_read_whole(
    make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(body_reader, "BODY_SECONDS", 1.0)
    client = make_client()
    parts = [b'{"email": "x@example.org", ', b'"password": "y"', b"}"]

    async def steady() -> dict[str, object]:
        await asyncio.sleep(0.05)
        part = parts.pop(0)
        return {"type": "http.request", "body": part, "more_body": bool(parts)}

    sent: list[dict[str, object]] = []

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    scope = {
        "type": "http", "http_version": "1.1", "method": "POST", "scheme": "https",
        "path": "/api/v1/auth/login", "raw_path": b"/api/v1/auth/login", "root_path": "",
        "query_string": b"", "server": ("hub.example", 443), "client": ("203.0.113.7", 1),
        "headers": [(b"host", b"hub.example"), (b"content-type", b"application/json")],
    }  # fmt: skip
    flow.drive(client, scope, steady, send)
    headers = dict(sent[0]["headers"])  # type: ignore[call-overload]
    # The whole body reached the route: a wrong login, not a timeout.
    assert (sent[0]["status"], headers[b"maity-error"]) == (401, b"unauthenticated")


def test_a_body_at_the_cap_passes_the_cap(make_client: ClientFactory) -> None:
    body = b'{"email": "x", "password": "' + b"y" * (64 * 1024 - 39) + b'"}'
    response = make_client().post(
        "/api/v1/auth/login", content=body, headers={"Content-Type": "application/json"}
    )
    assert response.headers["Maity-Error"] == "invalid"  # too long a password, not too large


def test_a_credential_shaped_string_is_refused_without_excerpt(
    make_client: ClientFactory,
) -> None:
    fake = "mty1.crd-unknown.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    client = make_client()
    for response in (
        client.post("/api/v1/auth/login", json={"email": fake, "password": "x"}),
        client.get(f"/api/v1/health?note={fake}"),
    ):
        assert response.status_code == 400
        assert response.headers["Maity-Error"] == "credential_in_payload"
        assert "mty1" not in response.text
        assert "crd-unknown" not in response.text


def test_a_real_credential_in_a_payload_is_revoked_and_reported(
    make_client: ClientFactory, migrated: Engine
) -> None:
    project_id = factory.project(migrated)
    owner = factory.human(migrated)
    factory.membership(migrated, project_id, human_id=owner)
    agent = factory.agent(migrated, project_id, owner)

    response = make_client().post(
        "/api/v1/auth/login", json={"email": "x", "password": f"see {agent.value} here"}
    )
    assert response.status_code == 400
    assert response.headers["Maity-Error"] == "credential_in_payload"

    with migrated.connect() as conn:
        credential = conn.execute(
            select(t.credential).where(t.credential.c.id == agent.credential_id)
        ).one()
        assert credential.revoked_at is not None
        assert credential.revoked_reason == "leaked_in_payload"
        live = conn.execute(
            select(t.agent_session.c.live).where(t.agent_session.c.id == agent.session_id)
        ).scalar()
        assert live is None
        # Not the start of the app counting the hub's text for a project made before it (§6.9).
        events = conn.execute(
            select(t.event).where(t.event.c.kind != "rules_changed").order_by(t.event.c.seq)
        ).all()
    assert [e.kind for e in events] == ["credential_revoked", "credential_in_payload"]
    assert events[0].audience == [f"member:{agent.agent_id}", "trust:owner"]
    assert events[1].audience == [f"member:{owner}", "trust:owner", "trust:admin"]
    secret = agent.value.split(".")[2]
    for event in events:
        assert secret not in str(event.payload)
        assert event.payload["credential_id"] == agent.credential_id


def test_a_public_id_with_a_guessed_secret_revokes_nothing(
    make_client: ClientFactory, migrated: Engine
) -> None:
    project_id = factory.project(migrated)
    owner = factory.human(migrated)
    agent = factory.agent(migrated, project_id, owner)
    guess = f"mty1.{agent.credential_id}.{'B' * 43}"
    response = make_client().post("/api/v1/auth/login", json={"email": guess, "password": "x"})
    assert response.headers["Maity-Error"] == "credential_in_payload"
    with migrated.connect() as conn:
        revoked = conn.execute(
            select(t.credential.c.revoked_at).where(t.credential.c.id == agent.credential_id)
        ).scalar()
        assert revoked is None
        # Nothing of the leak; the start of the app counts the hub's text once (§6.9).
        kinds = conn.execute(select(t.event.c.kind)).scalars().all()
        assert set(kinds) <= {"rules_changed"}


def test_health_says_database_unavailable_without_driver_text(
    make_client: ClientFactory, tmp_path: Path
) -> None:
    from maity_hub.db import make_engine

    client = make_client()
    client.app.state.health_engine = make_engine(  # type: ignore[attr-defined]
        f"sqlite:///{tmp_path / 'missing' / 'dir' / 'hub.db'}"
    )
    response = client.get("/api/v1/health")
    assert response.status_code == 503
    assert response.headers["Maity-Error"] == "database_unavailable"
    assert response.headers["Retry-After"] == "5"
    assert response.json()["error"]["details"] == {}
    assert "sqlite" not in response.text.lower()


def test_any_call_that_needs_the_database_answers_database_unavailable(
    make_client: ClientFactory, migrated: Engine, tmp_path: Path
) -> None:
    from maity_hub.db import make_engine

    project_id = factory.project(migrated)
    agent = factory.agent(migrated, project_id, factory.human(migrated))
    client = make_client()
    client.app.state.engine = make_engine(  # type: ignore[attr-defined]
        f"sqlite:///{tmp_path / 'missing' / 'dir' / 'hub.db'}"
    )
    response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {agent.value}"})
    assert response.status_code == 503
    assert response.headers["Maity-Error"] == "database_unavailable"
    assert response.headers["Retry-After"] == "5"
    assert "sqlite" not in response.text.lower()


def test_a_wrong_method_is_405_with_allow(make_client: ClientFactory) -> None:
    response = make_client().delete("/api/v1/me")
    assert response.status_code == 405
    assert response.headers["Maity-Error"] == "method_not_allowed"
    assert response.headers["Allow"] == "GET"


def test_a_body_full_of_fake_credentials_costs_one_bounded_lookup(
    make_client: ClientFactory, migrated: Engine
) -> None:
    from sqlalchemy import event as sa_event

    statements: list[str] = []
    listener = lambda *args: statements.append(args[2])  # noqa: E731
    sa_event.listen(migrated, "before_cursor_execute", listener)
    try:
        fakes = " ".join(f"mty1.crd-{i}.x" for i in range(6000))
        response = make_client().post(
            "/api/v1/auth/login", json={"email": "x", "password": fakes[:60000]}
        )
    finally:
        sa_event.remove(migrated, "before_cursor_execute", listener)
    assert response.headers["Maity-Error"] == "credential_in_payload"
    lookups = [s for s in statements if "FROM credential" in s]
    assert len(lookups) == 1
    assert lookups[0].count("?") + lookups[0].count("%(") <= 16


def test_a_credential_in_the_decoded_query_is_refused(make_client: ClientFactory) -> None:
    response = make_client().get("/api/v1/health?note=mty1%2Ecrd-x%2EAAAAAAAAAAAAAAAA")
    assert response.headers["Maity-Error"] == "credential_in_payload"


def test_a_plus_in_the_query_is_a_literal_plus(make_client: ClientFactory) -> None:
    client = make_client()
    app = client.app

    @app.get("/api/v1/echo")  # type: ignore[attr-defined, untyped-decorator]
    def echo(request: Request) -> dict[str, str]:
        return dict(request.query_params)

    app.router.routes.sort(key=lambda route: isinstance(route, Mount))  # type: ignore[attr-defined]
    assert client.get("/api/v1/echo?q=a+b&s=a%20b&p=a%2Bb").json() == {
        "q": "a+b",
        "s": "a b",
        "p": "a+b",
    }


def test_the_request_log_has_method_path_status_time_and_route_and_no_secret(
    make_client: ClientFactory, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    with caplog.at_level(logging.INFO, logger="maity_hub.access"):
        make_client().get("/api/v1/join/SECRET-TOKEN?code=Q7MD-3XPL", headers={"X-Thing": "hdr"})
        make_client().get("/join/SECRET-TOKEN")
        make_client().get("/invite/SECRET-TOKEN")
    lines = [r.getMessage() for r in caplog.records if r.name == "maity_hub.access"]
    assert re.fullmatch(r"GET /api/v1/join/… 404 ms=\d+ route=\S+", lines[0])
    assert lines[1].startswith("GET /join/… ")
    assert re.fullmatch(r"GET /invite/… 200 ms=\d+ route=\S+", lines[2])
    assert not any("SECRET" in line or "Q7MD" in line or "hdr" in line for line in lines)


async def _tail_of(status: int, envelope: object, *, encoded: bool = False) -> str:
    """The request log's tail for an answer with this status and body (§1.1)."""
    import json

    from maity_hub.middleware import _noting_refusal, _refusal_tail

    async def send(_message: object) -> None:
        return None

    state: dict[str, object] = {}
    body = json.dumps(envelope).encode()
    headers = [(b"content-type", b"application/json"), (b"maity-error", b"forbidden")]
    if encoded:
        headers.append((b"content-encoding", b"gzip"))
    wrapped = _noting_refusal(send, state)
    await wrapped({"type": "http.response.start", "status": status, "headers": headers})
    await wrapped({"type": "http.response.body", "body": body[:10], "more_body": True})
    await wrapped({"type": "http.response.body", "body": body[10:]})
    return _refusal_tail({"state": state}, status)


def _envelope(details: object, code: str = "forbidden") -> dict[str, object]:
    return {"error": {"code": code, "message": "m", "details": details}}


@pytest.mark.parametrize(
    ("status", "details", "tail"),
    [
        (403, {"scope": "members:admin"}, " error=forbidden scope=members:admin"),
        (403, {"reason": "owner_only"}, " error=forbidden reason=owner_only"),
        (403, {}, " error=forbidden"),
        (403, {"reason": None}, " error=forbidden"),
        (409, {"reason": "spent"}, " error=forbidden reason=spent"),
        (409, {}, ""),
        (400, {"fields": {"handle": "taken"}}, ""),
        (404, {}, ""),
        # Never a text or a value: a reason that is not a short code token is `?`.
        (403, {"reason": "not yours"}, " error=forbidden reason=?"),
        (403, {"reason": "x" * 65}, " error=forbidden reason=?"),
        (403, {"reason": "x" * 64}, " error=forbidden reason=" + "x" * 64),
        (403, {"reason": "Owner"}, " error=forbidden reason=?"),
        (403, {"reason": {"nested": "dict"}}, " error=forbidden reason=?"),
    ],
)
def test_a_refusal_names_its_code_and_reason_or_scope_in_the_request_log(
    status: int, details: object, tail: str
) -> None:
    """tsk-5d8hdtqhje26: a 403, and another 4xx with a reason or scope, names its code and that
    reason or scope; nothing else of the body reaches the line."""
    assert asyncio.run(_tail_of(status, _envelope(details))) == tail


def test_the_request_log_reads_no_body_it_cannot_parse() -> None:
    """A compressed answer, or one that is no envelope, still names its code for a 403."""
    encoded = _tail_of(403, _envelope({"reason": "owner_only"}), encoded=True)
    assert asyncio.run(encoded) == " error=forbidden"
    assert asyncio.run(_tail_of(403, ["not", "an", "envelope"])) == " error=forbidden"
    assert asyncio.run(_tail_of(200, {"ok": True})) == ""
    assert asyncio.run(_tail_of(500, _envelope({"reason": "x"}))) == ""


@pytest.mark.parametrize(
    ("chunks", "named"),
    [
        ([16 * 1024 * 1024], False),  # one chunk over the cap: nothing is copied
        ([10 * 1024, 10 * 1024], False),  # the second chunk would cross the cap
        ([16 * 1024 - 100, 100, 1], False),  # one byte past the cap, in the last chunk
        ([16 * 1024], True),  # exactly the cap: still read
        ([8 * 1024, 8 * 1024], True),
    ],
)
def test_the_refusal_note_never_copies_more_than_its_cap(
    monkeypatch: pytest.MonkeyPatch, chunks: list[int], named: bool
) -> None:
    """The copy of a refusal's body stays within 16 KiB at every point, also for a single large
    chunk; a body that would pass the cap is not read, and is still passed on whole."""
    import json

    from maity_hub import middleware

    largest = [0]

    class Measured(bytearray):
        def __iadd__(self, other: bytes) -> Measured:  # type: ignore[override, misc]
            result = super().__iadd__(other)
            largest[0] = max(largest[0], len(self))
            return result

    monkeypatch.setattr(middleware, "bytearray", Measured, raising=False)
    total = sum(chunks)
    envelope = json.dumps(_envelope({"reason": "owner_only"})).encode()
    body = envelope + b" " * (total - len(envelope))  # JSON allows trailing whitespace
    pieces, start = [], 0
    for size in chunks:
        pieces.append(body[start : start + size])
        start += size
    sent: list[object] = []

    async def send(message: object) -> None:
        sent.append(message)

    state: dict[str, object] = {}
    wrapped = middleware._noting_refusal(send, state)
    headers = [(b"content-type", b"application/json"), (b"maity-error", b"forbidden")]
    messages: list[dict[str, object]] = [
        {"type": "http.response.start", "status": 403, "headers": headers}
    ] + [
        {"type": "http.response.body", "body": piece, "more_body": i < len(pieces) - 1}
        for i, piece in enumerate(pieces)
    ]

    async def run() -> None:
        for message in messages:
            await wrapped(message)

    asyncio.run(run())
    assert largest[0] <= middleware._REFUSAL_BODY_MAX
    assert all(out is given for out, given in zip(sent, messages, strict=True))
    tail = middleware._refusal_tail({"state": state}, 403)
    assert tail == (" error=forbidden reason=owner_only" if named else " error=forbidden")


@pytest.mark.parametrize(
    ("status", "headers"),
    [
        (200, [(b"content-type", b"text/event-stream")]),  # a long-poll or event stream
        (200, [(b"content-type", b"application/octet-stream")]),  # a download
        (304, []),
        (500, [(b"maity-error", b"internal")]),
        # A refusal larger than the envelope cap is still passed on unchanged, only not read.
        (403, [(b"maity-error", b"forbidden")]),
    ],
)
def test_the_refusal_note_passes_every_answer_on_unchanged(
    status: int, headers: list[tuple[bytes, bytes]]
) -> None:
    """The send path of every answer: each message goes on at once and byte for byte, nothing
    is held back or buffered for anything but a 4xx refusal, and that only as a copy."""
    from maity_hub.middleware import _noting_refusal

    sent: list[object] = []

    async def send(message: object) -> None:
        sent.append(message)

    chunks = [bytes([i % 256]) * 65536 for i in range(16)]  # 1 MiB in 64 KiB chunks
    messages: list[dict[str, object]] = [
        {"type": "http.response.start", "status": status, "headers": headers}
    ] + [
        {"type": "http.response.body", "body": chunk, "more_body": i < len(chunks) - 1}
        for i, chunk in enumerate(chunks)
    ]
    state: dict[str, object] = {}
    wrapped = _noting_refusal(send, state)

    async def run() -> None:
        for count, message in enumerate(messages, 1):
            await wrapped(message)
            assert len(sent) == count  # passed on before the next one arrives

    asyncio.run(run())
    assert sent == messages
    assert all(out is given for out, given in zip(sent, messages, strict=True))  # same objects
    assert b"".join(m["body"] for m in sent[1:]) == b"".join(chunks)  # type: ignore[index]
    assert ("refusal" in state) == (status == 403)
    assert state.get("refusal", {}) in ({}, {"code": "forbidden"})


def test_the_engine_hides_statement_parameters(migrated: Engine) -> None:
    assert migrated.hide_parameters
