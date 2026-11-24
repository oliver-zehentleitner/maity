"""docs/api.md §2.2: a credential in the query string is refused and a real one revoked on
every request, also where the hub answers early: an unknown API path, a maintenance window
(§16.12), the operator's route limit (§1.7), a body declared over its cap (§1.7) and the forge
webhook (§17.4). A clean query gets each of those answers as before."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import middleware
from maity_hub import tables as t
from maity_hub.config import RouteLimit
from tests import flow
from tests.conftest import ClientFactory
from tests.test_large_body_precheck import _drive
from tests.test_maintenance import Clock, admin, now, put, running  # noqa: F401  (fixtures)

DUMMY = "mty1.crd-dummy.abc_DEF-9"
# Matches no credential: a single dot after the prefix.
CLEAN = "q=ok&x=mty1.only"
WEBHOOK = "/api/v1/projects/maintainer/maity/forge/webhook"
OVER_CAP = middleware.BODY_CAP + 1


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


def _revoked(engine: Engine, credential_id: str) -> str | None:
    """The credential's `revoked_reason`, None while it is live."""
    with engine.connect() as conn:
        row = conn.execute(
            select(t.credential.c.revoked_at, t.credential.c.revoked_reason).where(
                t.credential.c.id == credential_id
            )
        ).one()
    assert (row.revoked_at is None) == (row.revoked_reason is None)
    return None if row.revoked_reason is None else str(row.revoked_reason)


def _refused(response: Any) -> tuple[int, str | None]:
    return response.status_code, response.headers.get("Maity-Error")


@pytest.mark.parametrize("encoded", [False, True])
def test_a_credential_in_the_query_of_an_unknown_api_path_is_revoked(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, encoded: bool
) -> None:
    agent = flow.agent(make_client, owner)
    value = agent.credential.replace(".", "%2E") if encoded else agent.credential
    response = make_client().get(f"/api/v1/no-such-route?x={value}")
    assert _refused(response) == (400, "credential_in_payload"), response.text
    assert _revoked(migrated, agent.credential_id) == "leaked_in_payload"


def test_a_credential_in_the_query_during_a_maintenance_window_is_revoked(
    admin: flow.Human,  # noqa: F811
    now: Clock,  # noqa: F811
    make_client: ClientFactory,
    migrated: Engine,
) -> None:
    flow.project(admin, "maity")
    agent = flow.agent(make_client, admin)
    assert put(admin).status_code == 200
    running(now)
    client = make_client()
    assert _refused(client.get("/api/v1/projects")) == (503, "maintenance")  # the window runs
    response = client.get(f"/api/v1/projects?x={agent.credential}")
    assert _refused(response) == (400, "credential_in_payload"), response.text
    assert _revoked(migrated, agent.credential_id) == "leaked_in_payload"


def test_a_credential_in_the_query_of_a_limited_route_past_its_limit_is_revoked(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    client = make_client(route_limits=(RouteLimit("GET", "/api/v1/health", 1, 60),))
    assert client.get("/api/v1/health").status_code == 200
    assert _refused(client.get("/api/v1/health")) == (429, "rate_limited")  # past the limit
    response = client.get(f"/api/v1/health?x={agent.credential}")
    assert _refused(response) == (400, "credential_in_payload"), response.text
    assert _revoked(migrated, agent.credential_id) == "leaked_in_payload"


def test_a_credential_in_the_query_with_a_body_declared_over_the_cap_is_revoked_unread(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    query = f"x={agent.credential}".encode()
    refused = _drive(owner.client, "PATCH", "/api/v1/me", [], query, size=OVER_CAP)
    assert refused == (400, "credential_in_payload", 0)  # the body is never asked for
    assert _revoked(migrated, agent.credential_id) == "leaked_in_payload"


def test_a_credential_in_the_query_of_the_forge_webhook_is_revoked(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    response = make_client().post(f"{WEBHOOK}?x={agent.credential}", content=b"{}")
    assert _refused(response) == (400, "credential_in_payload"), response.text
    assert _revoked(migrated, agent.credential_id) == "leaked_in_payload"


def _unknown_path(make_client: ClientFactory, **_: Any) -> tuple[int, str | None, str | None]:
    response = make_client().get(f"/api/v1/no-such-route?{CLEAN}")
    return (*_refused(response), None)


def _maintenance(
    make_client: ClientFactory, human: flow.Human, clock: Clock, **_: Any
) -> tuple[int, str | None, str | None]:
    assert put(human).status_code == 200
    running(clock)
    response = make_client().get(f"/api/v1/projects?{CLEAN}")
    return (*_refused(response), response.headers.get("Retry-After"))


def _route_limit(make_client: ClientFactory, **_: Any) -> tuple[int, str | None, str | None]:
    client = make_client(route_limits=(RouteLimit("GET", "/api/v1/health", 1, 60),))
    assert client.get("/api/v1/health").status_code == 200
    response = client.get(f"/api/v1/health?{CLEAN}")
    return (*_refused(response), response.headers.get("Retry-After"))


def _over_cap(human: flow.Human, **_: Any) -> tuple[int, str | None, str | None]:
    status, code, asked = _drive(
        human.client, "PATCH", "/api/v1/me", [], CLEAN.encode(), size=OVER_CAP
    )
    assert asked == 0
    return status, code, None


def _webhook(make_client: ClientFactory, **_: Any) -> tuple[int, str | None, str | None]:
    response = make_client().post(f"{WEBHOOK}?{CLEAN}", content=b"{}")
    return (*_refused(response), None)


EarlyAnswer = Callable[..., tuple[int, str | None, str | None]]


@pytest.mark.parametrize(
    ("early", "expected"),
    [
        (_unknown_path, (404, "not_found", None)),
        (_maintenance, (503, "maintenance", "set")),
        (_route_limit, (429, "rate_limited", "set")),
        (_over_cap, (413, "payload_too_large", None)),
        (_webhook, (401, "webhook_signature", None)),
    ],
    ids=["unknown-path", "maintenance", "route-limit", "over-cap", "webhook"],
)
def test_a_clean_query_keeps_each_early_answer(
    admin: flow.Human,  # noqa: F811
    now: Clock,  # noqa: F811
    make_client: ClientFactory,
    early: EarlyAnswer,
    expected: tuple[int, str, str | None],
) -> None:
    flow.project(admin, "maity")
    status, code, retry_after = early(make_client=make_client, human=admin, clock=now)
    assert (status, code) == expected[:2]
    assert (retry_after is not None) == (expected[2] is not None)


def test_a_dummy_in_the_query_of_an_early_answer_is_refused_and_revokes_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    response = make_client().get(f"/api/v1/no-such-route?x={DUMMY}")
    assert _refused(response) == (400, "credential_in_payload"), response.text
    assert _revoked(migrated, agent.credential_id) is None
    assert agent.get("/me").status_code == 200
