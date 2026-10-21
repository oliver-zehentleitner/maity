"""docs/api.md §1 and §2.2's credential filter: what every request and response obeys."""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import Engine, select

from maity_hub import tables as t
from tests import factory
from tests.conftest import ClientFactory

SERVER_TIME = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")


def test_every_response_carries_the_server_time_and_no_store(make_client: ClientFactory) -> None:
    client = make_client()
    for path in ("/api/v1/health", "/api/v1/help", "/api/v1/nope", "/"):
        response = client.get(path)
        assert SERVER_TIME.match(response.headers["Maity-Server-Time"]), path
        assert response.headers["Cache-Control"] == "no-store", path
        assert response.headers["X-Content-Type-Options"] == "nosniff", path


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
    assert events[0].audience == [f"member:{agent.agent_id}", "role:owner"]
    assert events[1].audience == [f"member:{owner}", "role:owner", "role:admin"]
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
    client.app.state.engine = make_engine(  # type: ignore[attr-defined]
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
