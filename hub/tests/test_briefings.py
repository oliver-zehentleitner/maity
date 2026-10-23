"""docs/api.md §6.2: a briefing's versions, who wrote each, and who reads them."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def history(who: Any, member_id: str) -> Any:
    return who.get(f"/projects/maity/members/{member_id}/briefings")


def latest_member_updated(engine: Engine) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            select(t.event).where(t.event.c.kind == "member_updated").order_by(t.event.c.seq.desc())
        ).first()


def test_the_join_is_version_1_by_whoever_made_it(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner, briefing="the hub")
    view = owner.get(f"/projects/maity/members/{agent.id}").json()
    assert (view["briefing"], view["briefing_version"]) == ("the hub", 1)
    assert view["briefing_by"] == {"kind": "human", "id": owner.id, "handle": "maintainer"}
    assert view["briefing_updated_at"] is not None
    [first] = history(owner, agent.id).json()["items"]
    assert (first["version"], first["text"], first["by"]["id"]) == (1, "the hub", owner.id)


def test_a_change_is_a_new_version_and_its_event_says_only_that(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner, briefing="the hub")
    changed = owner.patch(f"/projects/maity/members/{agent.id}", {"briefing": "the hub, and CI"})
    assert changed.json()["briefing_version"] == 2
    event = latest_member_updated(migrated)
    assert (event.payload["changed"], event.payload["briefing_version"]) == (["briefing"], 2)
    assert "briefing" not in event.payload and "the hub" not in str(event.payload)
    items = history(owner, agent.id).json()["items"]
    assert [(i["version"], i["text"]) for i in items] == [(2, "the hub, and CI"), (1, "the hub")]
    same = owner.patch(f"/projects/maity/members/{agent.id}", {"briefing": "the hub, and CI"})
    assert same.json()["briefing_version"] == 2  # unchanged text: no new version


def test_an_admin_agents_change_names_the_agent(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    member = flow.agent(make_client, owner)
    assert (
        admin.patch(f"/projects/maity/members/{member.id}", {"briefing": "docs"}).status_code == 200
    )
    [latest, _] = history(owner, member.id).json()["items"]
    assert latest["by"] == {"kind": "agent", "id": admin.id, "handle": latest["by"]["handle"]}


def test_who_reads_the_versions(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner, briefing="the hub")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    member = flow.human(make_client, migrated, "plain")
    factory.membership(migrated, project_id, "member", human_id=member.id)
    stranger = flow.human(make_client, migrated, "stranger")
    admin_agent = flow.agent(make_client, owner, role="admin")
    assert history(owner, agent.id).status_code == 200
    assert history(member, agent.id).json()["error"]["details"] == {"scope": "members:admin"}
    assert history(agent, agent.id).status_code == 403  # the agent reads its current text only
    assert history(admin_agent, agent.id).status_code == 403  # humans only
    assert history(stranger, agent.id).status_code == 404
    assert history(owner, member.id).status_code == 404  # a human has no briefing
    assert history(owner, "agt-nobody").status_code == 404


def test_its_owner_reads_them_without_being_a_member(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    outside = flow.human(make_client, migrated, "outside")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    theirs = factory.agent(migrated, project_id, outside.id)  # its owner is no member
    found = history(outside, theirs.agent_id)
    assert found.status_code == 200, found.text
