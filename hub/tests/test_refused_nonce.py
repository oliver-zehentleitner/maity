"""docs/api.md §2.2: a signed request refused after its nonce was spent keeps the nonce spent,
whatever refused it, on every engine; and a `Maity-On-Request` that is not a request id is
refused before the canonical string is built (hub/context/auth.md fbc8c3e0)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.auth import credentials
from maity_hub.ids import new_id
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_runners import paired

API = "/api/v1"
PROJECT = "/projects/maintainer/maity"
LOW = 60  # the lowest read limit the setting takes (tests/test_read_limits.py)
# A minute's start after the process started, as tests/test_read_limits.py takes it: a signed
# call's timestamp is refused before the process started (`caller.PROCESS_STARTED`).
BASE = float((int(time.time()) // 60 + 2) * 60)


def _sign(
    holder: Any,
    method: str,
    path: str,
    *,
    for_member: str | None = None,
    on_request: str | None = None,
) -> dict[str, str]:
    """The headers of one signed request, the canonical string as §2.2 builds it. The request
    is sent again by sending these same headers again."""
    secret = holder.value.split(".")[2]
    key = hashlib.sha256(secret.encode()).digest()
    stamp, nonce = str(int(clock.now().timestamp())), secrets.token_urlsafe(16)
    target, _, query = path.partition("?")
    canonical = credentials.canonical_string(
        method, target.encode(), query.encode(), stamp, nonce, b"", for_member, on_request
    )
    headers = {
        "Authorization": f"Maity-HMAC {holder.credential_id}",
        "Maity-Timestamp": stamp,
        "Maity-Nonce": nonce,
        "Maity-Signature": hmac.new(key, canonical.encode(), "sha256").hexdigest(),
    }
    if for_member is not None:
        headers["Maity-For"] = for_member
    if on_request is not None:
        headers["Maity-On-Request"] = on_request
    return headers


def _code(response: Any) -> str:
    code: str = response.headers.get("Maity-Error", "")
    return code


def _reused(response: Any) -> None:
    assert (response.status_code, _code(response)) == (401, "nonce_reused"), response.text


def _project_id(engine: Engine, slug: str = "maity") -> str:
    with engine.connect() as conn:
        found: str = conn.execute(
            select(t.project.c.id).where(t.project.c.slug == slug)
        ).scalar_one()
    return found


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


@pytest.fixture
def agent(owner: flow.Human, migrated: Engine) -> factory.Agent:
    return factory.agent(migrated, _project_id(migrated), owner.id, "coder")


def _isolate(engine: Engine, agent: factory.Agent, on: bool) -> None:
    with engine.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == agent.agent_id)
            .values(
                isolated_since=clock.now() if on else None,
                isolated_reason="a test" if on else None,
                isolated_by="x" if on else None,
            )
        )


# --- a refusal after the nonce was spent --------------------------------------------------


def test_an_isolated_agents_refused_request_keeps_its_nonce_spent(
    agent: factory.Agent, make_client: ClientFactory, migrated: Engine
) -> None:
    client = make_client()
    _isolate(migrated, agent, True)
    headers = _sign(agent, "GET", f"{API}{PROJECT}/tasks")
    refused = client.get(f"{API}{PROJECT}/tasks", headers=headers)
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"]["reason"] == "isolated"
    _isolate(migrated, agent, False)  # the refusal's condition ends
    _reused(client.get(f"{API}{PROJECT}/tasks", headers=headers))
    fresh = _sign(agent, "GET", f"{API}{PROJECT}/tasks")
    assert client.get(f"{API}{PROJECT}/tasks", headers=fresh).status_code == 200


def test_a_rate_limited_request_keeps_its_nonce_spent(
    agent: factory.Agent, make_client: ClientFactory
) -> None:
    moment = [BASE + 30]
    clock.set_source(lambda: datetime.fromtimestamp(moment[0], UTC))  # conftest resets it
    client = make_client(max_reads_per_minute=LOW)
    bearer = {"Authorization": f"Bearer {agent.value}"}
    for n in range(LOW):  # the credential's reads, counted whatever presents it
        got = client.get(f"{API}/me", headers=bearer)
        assert got.status_code == 200, (n, got.text)
    headers = _sign(agent, "GET", f"{API}/me")
    refused = client.get(f"{API}/me", headers=headers)
    assert (refused.status_code, _code(refused)) == (429, "rate_limited"), refused.text
    moment[0] = BASE + 150  # two windows on, nothing counts; within the timestamp's window
    _reused(client.get(f"{API}/me", headers=headers))
    assert client.get(f"{API}/me", headers=_sign(agent, "GET", f"{API}/me")).status_code == 200


def test_a_request_refused_for_another_project_keeps_its_nonce_spent(
    owner: flow.Human, agent: factory.Agent, make_client: ClientFactory
) -> None:
    flow.project(owner, "other")
    client = make_client()
    path = f"{API}/projects/maintainer/other/tasks"
    headers = _sign(agent, "GET", path)
    refused = client.get(path, headers=headers)
    assert (refused.status_code, _code(refused)) == (404, "not_found"), refused.text
    _reused(client.get(path, headers=headers))


def test_a_bridge_call_refused_for_an_agent_it_does_not_serve_keeps_its_nonce_spent(
    owner: flow.Human, agent: factory.Agent, make_client: ClientFactory, migrated: Engine
) -> None:
    stranger = factory.agent(migrated, _project_id(migrated), owner.id, "coder", instance="str1")
    client = make_client()
    path = f"{API}{PROJECT}/tasks"
    headers = _sign(agent, "GET", path, for_member=stranger.agent_id)
    refused = client.get(path, headers=headers)
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"]["reason"] == "not_your_bridge"
    _reused(client.get(path, headers=headers))


def test_a_runner_call_refused_outside_its_routes_keeps_its_nonce_spent(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    runner = paired(make_client, owner)
    client = make_client()
    headers = _sign(runner, "GET", f"{API}/me")
    refused = client.get(f"{API}/me", headers=headers)
    assert (refused.status_code, _code(refused)) == (403, "forbidden"), refused.text
    _reused(client.get(f"{API}/me", headers=headers))


def test_a_refused_request_leaves_its_nonce_in_the_shared_table(
    agent: factory.Agent, make_client: ClientFactory, migrated: Engine
) -> None:
    """On PostgreSQL the nonce is a row; the refusal's rollback took it, and it is back."""
    if migrated.dialect.name != "postgresql":
        pytest.skip("SQLite and MariaDB keep the nonce window in the process")
    _isolate(migrated, agent, True)
    headers = _sign(agent, "GET", f"{API}{PROJECT}/tasks")
    assert make_client().get(f"{API}{PROJECT}/tasks", headers=headers).status_code == 403
    with migrated.connect() as conn:
        spent = conn.execute(select(t.request_nonce.c.credential_id, t.request_nonce.c.nonce)).all()
    assert [tuple(row) for row in spent] == [(agent.credential_id, headers["Maity-Nonce"])]


# --- Maity-On-Request has a request id's shape --------------------------------------------


@pytest.mark.parametrize(
    "value", ["for:{agent}", "req-a", "req-0012", "REQ-0123456789AB", "req-0123456789ab-"]
)
def test_an_on_request_that_is_not_a_request_id_is_refused(
    agent: factory.Agent, make_client: ClientFactory, value: str
) -> None:
    value = value.format(agent=agent.agent_id)
    headers = _sign(agent, "GET", f"{API}/me", on_request=value)
    refused = make_client().get(f"{API}/me", headers=headers)
    assert (refused.status_code, _code(refused)) == (401, "signature_invalid"), refused.text
    assert refused.json()["error"]["message"] == "Maity-On-Request is not a request id"


def test_an_on_request_never_signs_like_a_for_line(
    owner: flow.Human, agent: factory.Agent, make_client: ClientFactory, migrated: Engine
) -> None:
    """`Maity-On-Request: for:<id>` would make the canonical string of `Maity-For: <id>`; it is
    refused before that string is built, so the signature of the one is never taken for the
    other."""
    served = factory.agent(migrated, _project_id(migrated), owner.id, "coder", instance="srv1")
    path = f"{API}{PROJECT}/tasks"
    as_for = _sign(agent, "GET", path, for_member=served.agent_id)
    swapped = {k: v for k, v in as_for.items() if k != "Maity-For"}
    swapped["Maity-On-Request"] = f"for:{served.agent_id}"
    refused = make_client().get(path, headers=swapped)
    assert (refused.status_code, _code(refused)) == (401, "signature_invalid"), refused.text
    assert refused.json()["error"]["message"] == "Maity-On-Request is not a request id"


def test_an_on_request_with_a_request_ids_shape_signs_as_before(
    agent: factory.Agent, make_client: ClientFactory
) -> None:
    headers = _sign(agent, "GET", f"{API}/me", on_request=new_id("request"))
    assert make_client().get(f"{API}/me", headers=headers).status_code == 200
    other = _sign(agent, "GET", f"{API}/me", on_request=new_id("request"))
    other["Maity-On-Request"] = new_id("request")  # signed for another id
    assert _code(make_client().get(f"{API}/me", headers=other)) == "signature_invalid"
