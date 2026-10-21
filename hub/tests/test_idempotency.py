"""docs/api.md §1.5, through a probe route: slice 1 has no agent write of its own."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine
from starlette.routing import Mount

from maity_hub import clock, idempotency
from maity_hub.deps import AnyCaller, engine_of
from tests import factory
from tests.conftest import ClientFactory

CALLS: list[dict[str, Any]] = []
KEY = {"Idempotency-Key": "k" * 16}


@pytest.fixture
def client(make_client: ClientFactory) -> Iterator[TestClient]:
    CALLS.clear()
    client = make_client()
    app = client.app

    def load(_conn: Connection, resource_id: str) -> dict[str, Any]:
        return {"id": resource_id, "loaded": True}

    idempotency.LOADERS["probe"] = load

    @app.post("/api/v1/probe")  # type: ignore[attr-defined, untyped-decorator]
    def probe(request: Request, caller: AnyCaller) -> JSONResponse:
        def action(_conn: Connection) -> idempotency.Outcome:
            CALLS.append({"by": caller.principal_id})
            return idempotency.Outcome(201, "probe", f"p-{len(CALLS)}", {"id": f"p-{len(CALLS)}"})

        return idempotency.run(engine_of(request), request, caller, action)

    @app.post("/api/v1/me/resume")  # type: ignore[attr-defined, untyped-decorator]
    def resume(request: Request, caller: AnyCaller) -> JSONResponse:
        return idempotency.run(
            engine_of(request),
            request,
            caller,
            lambda _c: idempotency.Outcome(200, None, None, {"ok": True}),
        )

    # Routes added after create_app sit behind the dashboard mount at "/"; move it last.
    routes = app.router.routes  # type: ignore[attr-defined]
    routes.sort(key=lambda route: isinstance(route, Mount))
    yield client
    idempotency.LOADERS.pop("probe", None)


@pytest.fixture
def agent(migrated: Engine) -> factory.Agent:
    project_id = factory.project(migrated)
    return factory.agent(migrated, project_id, factory.human(migrated))


def _auth(agent: factory.Agent) -> dict[str, str]:
    return {"Authorization": f"Bearer {agent.value}"}


def test_an_agent_post_without_a_key_is_invalid(client: TestClient, agent: factory.Agent) -> None:
    response = client.post("/api/v1/probe", json={"a": 1}, headers=_auth(agent))
    assert response.status_code == 400
    assert response.json()["error"]["details"]["fields"] == {"Idempotency-Key": "required"}
    assert CALLS == []


@pytest.mark.parametrize("key", ["short", "x" * 129])
def test_a_key_outside_16_to_128_characters_is_invalid(
    client: TestClient, agent: factory.Agent, key: str
) -> None:
    response = client.post(
        "/api/v1/probe", json={}, headers=_auth(agent) | {"Idempotency-Key": key}
    )
    assert response.headers["Maity-Error"] == "invalid"


def test_a_repeat_replays_status_and_current_resource(
    client: TestClient, agent: factory.Agent
) -> None:
    first = client.post("/api/v1/probe", json={"a": 1}, headers=_auth(agent) | KEY)
    assert first.status_code == 201
    assert "Idempotent-Replayed" not in first.headers
    again = client.post("/api/v1/probe", json={"a": 1}, headers=_auth(agent) | KEY)
    assert again.status_code == 201
    assert again.headers["Idempotent-Replayed"] == "true"
    assert again.json() == {"id": "p-1", "loaded": True}
    assert len(CALLS) == 1


def test_a_repeat_with_another_body_is_a_mismatch(client: TestClient, agent: factory.Agent) -> None:
    client.post("/api/v1/probe", json={"a": 1}, headers=_auth(agent) | KEY)
    response = client.post("/api/v1/probe", json={"a": 2}, headers=_auth(agent) | KEY)
    assert response.status_code == 409
    assert response.headers["Maity-Error"] == "idempotency_mismatch"
    assert len(CALLS) == 1


def test_keys_are_per_credential(
    client: TestClient, agent: factory.Agent, migrated: Engine
) -> None:
    other = factory.agent(migrated, factory.project(migrated), agent.owner_id)
    client.post("/api/v1/probe", json={"a": 1}, headers=_auth(agent) | KEY)
    response = client.post("/api/v1/probe", json={"a": 1}, headers=_auth(other) | KEY)
    assert response.status_code == 201
    assert "Idempotent-Replayed" not in response.headers
    assert len(CALLS) == 2


def test_a_key_expires_after_24_hours(client: TestClient, agent: factory.Agent) -> None:
    client.post("/api/v1/probe", json={"a": 1}, headers=_auth(agent) | KEY)
    start = clock.now()
    clock.set_source(lambda: start + timedelta(hours=24, seconds=1))
    response = client.post("/api/v1/probe", json={"a": 2}, headers=_auth(agent) | KEY)
    assert response.status_code == 201
    assert len(CALLS) == 2


def test_resume_needs_no_key(client: TestClient, agent: factory.Agent) -> None:
    response = client.post("/api/v1/me/resume", json={}, headers=_auth(agent))
    assert response.status_code == 200


def test_a_human_may_send_a_key_and_need_not(client: TestClient, migrated: Engine) -> None:
    factory.human(migrated, "maintainer")
    client.post("/api/v1/auth/login", json={"handle": "maintainer", "password": factory.PASSWORD})
    csrf = client.get("/api/v1/auth/session").json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf}
    assert client.post("/api/v1/probe", json={}, headers=headers).status_code == 201
    client.post("/api/v1/probe", json={}, headers=headers | KEY)
    replay = client.post("/api/v1/probe", json={}, headers=headers | KEY)
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert len(CALLS) == 2


def test_a_call_refused_before_it_ran_leaves_its_key_unused(
    client: TestClient, agent: factory.Agent
) -> None:
    """The CLI retries a `timestamp_skew` with the same key: that is no replay."""
    from tests.test_auth_agent import signed

    body = b'{"a": 1}'
    stale = int(clock.now().timestamp()) - 400
    headers = {"Content-Type": "application/json"} | KEY
    refused = client.post(
        "/api/v1/probe",
        content=body,
        headers=headers | signed(agent, "POST", "/api/v1/probe", body=body, timestamp=stale),
    )
    assert refused.headers["Maity-Error"] == "timestamp_skew"
    retried = client.post(
        "/api/v1/probe",
        content=body,
        headers=headers | signed(agent, "POST", "/api/v1/probe", body=body),
    )
    assert retried.status_code == 201
    assert "Idempotent-Replayed" not in retried.headers
    assert len(CALLS) == 1
