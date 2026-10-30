"""docs/api.md §1 and §2.2's credential filter: what every request and response obeys."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest
from fastapi import Request
from sqlalchemy import Engine, select
from starlette.routing import Mount

from maity_hub import tables as t
from tests import factory
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
        "/api/v1/auth/login", json={"handle": "x", "password": "y", "extra": 1}
    )
    assert response.status_code == 400
    assert response.headers["Maity-Error"] == "invalid"
    assert response.json()["error"]["details"]["fields"] == {"extra": "extra_forbidden"}


def test_a_validation_error_never_quotes_the_input(make_client: ClientFactory) -> None:
    response = make_client().post("/api/v1/auth/login", json={"handle": "", "password": "s3cr3t"})
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
    asyncio.run(client.app(scope, never_read, send))  # type: ignore[arg-type]
    assert sent[0]["status"] == 404


def test_a_body_at_the_cap_passes_the_cap(make_client: ClientFactory) -> None:
    body = b'{"handle": "x", "password": "' + b"y" * (64 * 1024 - 40) + b'"}'
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
        client.post("/api/v1/auth/login", json={"handle": fake, "password": "x"}),
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
        "/api/v1/auth/login", json={"handle": "x", "password": f"see {agent.value} here"}
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
        events = conn.execute(select(t.event).order_by(t.event.c.seq)).all()
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
    response = make_client().post("/api/v1/auth/login", json={"handle": guess, "password": "x"})
    assert response.headers["Maity-Error"] == "credential_in_payload"
    with migrated.connect() as conn:
        revoked = conn.execute(
            select(t.credential.c.revoked_at).where(t.credential.c.id == agent.credential_id)
        ).scalar()
        assert revoked is None
        assert conn.execute(select(t.event)).first() is None


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
            "/api/v1/auth/login", json={"handle": "x", "password": fakes[:60000]}
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


def test_the_engine_hides_statement_parameters(migrated: Engine) -> None:
    assert migrated.hide_parameters
