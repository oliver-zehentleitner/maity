"""docs/api.md §2.3: no agent takes over, assigns away or releases a card a human holds,
lease or no lease; humans keep their rights over it."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_claims import _claim, _later
from tests.test_tasks import task

LEASE = 7200


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def reason(response: Any) -> Any:
    return response.json()["error"]["details"].get("reason")


def holder(engine: Engine, card_id: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(select(t.card.c.claim_holder).where(t.card.c.id == card_id)).scalar()


@pytest.mark.parametrize("expired", [False, True])
def test_no_agent_moves_a_humans_claim(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, expired: bool
) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    member = flow.agent(make_client, owner)
    card = task(owner)
    assert _claim(owner, card).status_code == 200
    held = holder(migrated, card["id"])
    if expired:
        _later(LEASE + 1)
    url = f"/projects/maity/tasks/{card['id']}"
    attempts = [
        admin.post(f"{url}/assign", {"assignee": member.id}),
        admin.post(f"{url}/release", {}),
        admin.patch(url, {"assigned_to": member.id}),
    ]
    for attempt in attempts:
        assert (attempt.status_code, reason(attempt)) == (403, "humans_only"), attempt.text
    assert holder(migrated, card["id"]) == held


def test_assigning_a_humans_card_to_that_human_is_no_move(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    card = task(owner)
    _claim(owner, card)
    url = f"/projects/maity/tasks/{card['id']}"
    assert admin.patch(url, {"assigned_to": owner.id}).status_code == 200


def test_a_human_admin_still_moves_an_expired_human_claim(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = flow.human(make_client, migrated, "other")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "member", human_id=other.id)
    member = flow.agent(make_client, owner)
    card = task(other)
    assert _claim(other, card).status_code == 200
    _later(LEASE + 1)
    moved = owner.post(f"/projects/maity/tasks/{card['id']}/assign", {"assignee": member.id})
    assert moved.status_code == 200, moved.text
    assert moved.json()["claim"]["holder"] == member.id


def test_an_admin_agent_still_releases_an_agents_expired_claim(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    member = flow.agent(make_client, owner)
    card = task(owner)
    assert _claim(member, card).status_code == 200
    _later(LEASE + 1)
    released = admin.post(f"/projects/maity/tasks/{card['id']}/release", {})
    assert released.status_code == 200, released.text
