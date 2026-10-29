"""docs/api.md §1.5, through a probe route: slice 1 has no agent write of its own."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, insert, update
from starlette.routing import Mount

from maity_hub import clock, idempotency
from maity_hub import tables as t
from maity_hub.deps import AnyCaller, engine_of
from maity_hub.errors import ApiError
from tests import factory, flow
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

    idempotency.LOADERS["probe"] = idempotency.plain(load)

    @app.post("/api/v1/probe")  # type: ignore[attr-defined, untyped-decorator]
    def probe(request: Request, caller: AnyCaller) -> JSONResponse:
        def action(_conn: Connection) -> idempotency.Outcome:
            CALLS.append({"by": caller.principal_id})
            return idempotency.Outcome(201, "probe", f"p-{len(CALLS)}", {"id": f"p-{len(CALLS)}"})

        return idempotency.run(engine_of(request), request, caller, action)

    @app.post("/api/v1/conflict")  # type: ignore[attr-defined, untyped-decorator]
    def conflict(request: Request, caller: AnyCaller) -> JSONResponse:
        def action(conn: Connection) -> idempotency.Outcome:
            CALLS.append({"conflict": True})
            # A unique violation inside the action itself, as a second release
            # in flight would be: it must surface once, not run twice.
            conn.execute(
                insert(t.idempotency_key).values(
                    caller="x", idem_key="dup", body_hash="0", status_code=1, created_at=clock.now()
                )
            )
            conn.execute(
                insert(t.idempotency_key).values(
                    caller="x", idem_key="dup", body_hash="0", status_code=1, created_at=clock.now()
                )
            )
            return idempotency.Outcome(201, None, None, {})

        return idempotency.run(engine_of(request), request, caller, action)

    @app.post("/api/v1/failing")  # type: ignore[attr-defined, untyped-decorator]
    def failing(request: Request, caller: AnyCaller) -> JSONResponse:
        def action(_conn: Connection) -> idempotency.Outcome:
            CALLS.append({"failing": True})
            raise ApiError(409, "already_claimed", "held")

        return idempotency.run(engine_of(request), request, caller, action)

    @app.post("/api/v1/race")  # type: ignore[attr-defined, untyped-decorator]
    def race(request: Request, caller: AnyCaller) -> JSONResponse:
        engine = engine_of(request)

        def action(_conn: Connection) -> idempotency.Outcome:
            CALLS.append({"race": True})
            # Another request with the same key commits while this one runs.
            with engine.begin() as other:
                other.execute(
                    insert(t.idempotency_key).values(
                        caller=caller.idempotency_caller,
                        idem_key=KEY["Idempotency-Key"],
                        body_hash=idempotency.fingerprint(other, request),
                        status_code=201,
                        resource_type="probe",
                        resource_id="p-other",
                        created_at=clock.now(),
                    )
                )
            return idempotency.Outcome(201, "probe", "p-mine", {"id": "p-mine"})

        return idempotency.run(engine, request, caller, action)

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


def test_a_key_stored_before_the_call_hash_is_a_mismatch(
    client: TestClient, agent: factory.Agent, migrated: Engine
) -> None:
    """A key stored with the body's hash alone, as before the call's hash (§1.5), answers
    `idempotency_mismatch` on every repeat until it expires."""
    client.post("/api/v1/probe", json={"a": 1}, headers=_auth(agent) | KEY)
    with migrated.begin() as conn:
        conn.execute(
            update(t.idempotency_key).values(body_hash=hashlib.sha256(b'{"a":1}').hexdigest())
        )
    again = client.post("/api/v1/probe", json={"a": 1}, headers=_auth(agent) | KEY)
    assert again.status_code == 409
    assert again.headers["Maity-Error"] == "idempotency_mismatch"
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
    response = client.post("/api/v1/me/resume", json={"client": "curl"}, headers=_auth(agent))
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


def test_a_conflict_inside_the_action_runs_once_and_is_the_internal_envelope(
    client: TestClient, agent: factory.Agent
) -> None:
    response = client.post("/api/v1/conflict", json={}, headers=_auth(agent) | KEY)
    assert response.status_code == 500
    assert response.headers["Maity-Error"] == "internal"
    assert response.json()["error"] == {
        "code": "internal",
        "message": "an unexpected failure",
        "details": {},
    }
    assert response.headers["Cache-Control"] == "no-store"
    assert len(CALLS) == 1


def test_a_failed_call_stores_nothing_and_may_be_repeated(
    client: TestClient, agent: factory.Agent
) -> None:
    for _ in range(2):
        response = client.post("/api/v1/failing", json={}, headers=_auth(agent) | KEY)
        assert response.headers["Maity-Error"] == "already_claimed"
        assert "Idempotent-Replayed" not in response.headers
    assert len(CALLS) == 2


def test_losing_the_race_for_a_key_replays_the_winner(
    client: TestClient, agent: factory.Agent, migrated: Engine
) -> None:
    if migrated.dialect.name == "sqlite":
        pytest.skip("SQLite takes the write lock at BEGIN: a second writer cannot interleave")
    response = client.post("/api/v1/race", json={"a": 1}, headers=_auth(agent) | KEY)
    assert response.status_code == 201
    assert response.headers["Idempotent-Replayed"] == "true"
    assert response.json() == {"id": "p-other", "loaded": True}


def _create(owner: flow.Human, project: str) -> Any:
    """The same card, with the same key, in `project`."""
    return owner.client.post(
        f"/api/v1/projects/{project}/tasks",
        json={"title": "Same card"},
        headers={"X-CSRF-Token": owner.csrf} | KEY,
    )


def test_a_key_used_again_in_another_project_is_a_mismatch(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """A human's key spans their projects: the second project's call must not replay
    the card the first one made (§1.5)."""
    owner = flow.human(make_client, migrated)
    flow.project(owner, "one")
    flow.project(owner, "two")
    assert _create(owner, "maintainer/one").status_code == 201
    other = _create(owner, "maintainer/two")
    assert other.status_code == 409, other.text
    assert other.headers["Maity-Error"] == "idempotency_mismatch"
    assert owner.get("/projects/maintainer/two/tasks").json()["items"] == []


def test_a_key_on_another_route_is_a_mismatch(client: TestClient, agent: factory.Agent) -> None:
    client.post("/api/v1/probe", json={"a": 1}, headers=_auth(agent) | KEY)
    response = client.post("/api/v1/failing", json={"a": 1}, headers=_auth(agent) | KEY)
    assert response.headers["Maity-Error"] == "idempotency_mismatch"
    assert [{"by": agent.agent_id}] == CALLS


def test_an_old_name_of_the_project_replays_the_same_call(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """The project counts by its id: the call through an alias (§6.25) is the same."""
    owner = flow.human(make_client, migrated)
    project = flow.project(owner, "maity")
    with migrated.begin() as conn:
        conn.execute(
            insert(t.project_alias).values(
                project_id=project["id"], owner_id=owner.id, slug="old", created_at=clock.now()
            )
        )
    first = _create(owner, "maintainer/maity")
    assert first.status_code == 201, first.text
    again = _create(owner, "maintainer/old")
    assert again.status_code == 201, again.text
    assert again.headers["Idempotent-Replayed"] == "true"
    assert again.json()["id"] == first.json()["id"]
