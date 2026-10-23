"""The shared mechanism for changes that wait for a human's go (`maity_hub.proposals`)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, select

from maity_hub import proposals
from maity_hub import tables as t
from maity_hub.access import membership
from maity_hub.auth.caller import Caller
from maity_hub.events import Actor, transaction
from maity_hub.routes.requests import file_consent
from tests import flow
from tests.conftest import ClientFactory

settled: list[tuple[str, str, dict[str, Any]]] = []


def _settle(
    conn: Connection,
    request: Any,
    proposal: dict[str, Any],
    outcome: str,
    actor: Actor | None,
    by: str | None,
) -> None:
    settled.append((request.id, outcome, proposal))


@pytest.fixture(autouse=True)
def _kind() -> Iterator[None]:
    proposals.register("test", _settle, humans_only=True)
    settled.clear()
    yield
    proposals.KINDS.pop("test", None)


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def _file(migrated: Engine, agent: flow.Agent) -> str:
    with transaction(migrated) as conn:
        row = conn.execute(select(t.membership).where(t.membership.c.agent_id == agent.id)).one()
        caller = Caller(
            kind="agent",
            via="bearer",
            agent_id=agent.id,
            credential_id=agent.credential_id,
            membership_id=row.id,
            project_id=row.project_id,
        )
        mine = membership(conn, caller, "maity")
        return file_consent(
            conn, mine, caller, "Test it", "why", proposal={"kind": "test", "value": 7}
        )


def test_a_proposal_is_settled_on_its_answer(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    request_id = _file(migrated, admin)
    other = flow.agent(make_client, owner, role="admin")
    refused = other.post(f"/projects/maity/requests/{request_id}/answer", {"reply_id": "go"})
    assert refused.json()["error"]["details"] == {"reason": "humans_only"}
    assert settled == []
    go = owner.post(f"/projects/maity/requests/{request_id}/answer", {"reply_id": "go"})
    assert go.status_code == 200, go.text
    assert settled == [(request_id, "go", {"kind": "test", "value": 7})]


def test_a_withdrawn_proposal_is_settled_as_withdrawn(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    request_id = _file(migrated, admin)
    admin.post(f"/projects/maity/requests/{request_id}/withdraw", {"reason": "no longer"})
    assert [(i, o) for i, o, _ in settled] == [(request_id, "withdrawn")]
