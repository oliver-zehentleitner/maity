"""docs/api.md §3.1 "The owner changes the role", §6.2: the human who owns an agent changes
its role without members:admin, to a role a member join could give, while they could create a
join for it now; areas, capabilities and trust stay members:admin."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_join_subagents import JOINS, PROJECT, exchanged, forbidden


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    """The project's owner, an admin."""
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


@pytest.fixture
def friend(make_client: ClientFactory, migrated: Engine, owner: flow.Human) -> flow.Human:
    """A member with trust `member`, who may bring agents of their own."""
    friend = flow.human(make_client, migrated, "friend")
    factory.membership(migrated, _project_id(migrated), "member", human_id=friend.id)
    return friend


def _project_id(engine: Engine) -> str:
    with engine.connect() as conn:
        project_id: str = conn.execute(select(t.project.c.id)).scalar_one()
    return project_id


def brought(friend: flow.Human, make_client: ClientFactory, role: str = "coder") -> flow.Agent:
    created = friend.post(
        JOINS, {"agent": {"handle": f"friend-{role}", "display_name": "F"}, "role": role}
    )
    assert created.status_code == 201, created.text
    return exchanged(make_client, created.json())


def role_of(owner: flow.Human, member_id: str) -> Any:
    return owner.get(f"{PROJECT}/members/{member_id}").json()["role"]


def test_the_owner_changes_the_role_without_members_admin(
    owner: flow.Human, friend: flow.Human, make_client: ClientFactory
) -> None:
    agent = brought(friend, make_client)
    for role in ("reviewer", "tester", "manager", "purple-team", "coder"):
        changed = friend.patch(f"{PROJECT}/members/{agent.id}", {"role": role})
        assert changed.status_code == 200, (role, changed.text)
        assert changed.json()["role"] == role
        assert role_of(owner, agent.id) == role


def test_ops_and_proxy_are_beyond_the_member_limits(
    friend: flow.Human, make_client: ClientFactory, owner: flow.Human
) -> None:
    agent = brought(friend, make_client)
    for role in ("ops", "proxy"):
        refused = friend.patch(f"{PROJECT}/members/{agent.id}", {"role": role})
        forbidden(refused, "member_join_limit")
        assert refused.json()["error"]["details"]["field"] == "role"
    assert role_of(owner, agent.id) == "coder"


def test_a_project_role_on_a_member_base_is_taken_one_on_ops_is_not(
    owner: flow.Human, friend: flow.Human, make_client: ClientFactory
) -> None:
    roles = owner.client.put(
        f"/api/v1{PROJECT}/roles",
        json={"custom": [{"name": "docs", "base": "writer"}, {"name": "deployer", "base": "ops"}]},
        headers={"X-CSRF-Token": owner.csrf},
    )
    assert roles.status_code == 200, roles.text
    agent = brought(friend, make_client)
    assert friend.patch(f"{PROJECT}/members/{agent.id}", {"role": "docs"}).status_code == 200
    assert role_of(owner, agent.id) == "docs"
    # A project role on a member base keeps the agent within the limits: the owner changes it
    # again, it does not lock them out.
    assert friend.patch(f"{PROJECT}/members/{agent.id}", {"role": "tester"}).status_code == 200
    assert friend.patch(f"{PROJECT}/members/{agent.id}", {"role": "docs"}).status_code == 200
    refused = friend.patch(f"{PROJECT}/members/{agent.id}", {"role": "deployer"})
    forbidden(refused, "member_join_limit")
    unknown = friend.patch(f"{PROJECT}/members/{agent.id}", {"role": "nonesuch"})
    assert unknown.status_code == 400, unknown.text


def test_areas_capabilities_and_trust_stay_members_admin(
    owner: flow.Human, friend: flow.Human, make_client: ClientFactory
) -> None:
    agent = brought(friend, make_client)
    for body in (
        {"areas": ["hub/"]},
        {"capabilities": ["python"]},
        {"trust": "guest"},
        {"role": "reviewer", "areas": ["hub/"]},
    ):
        refused = friend.patch(f"{PROJECT}/members/{agent.id}", body)
        assert refused.status_code == 403, (body, refused.text)
        assert refused.json()["error"]["details"]["scope"] == "members:admin", body
    assert role_of(owner, agent.id) == "coder"


def test_another_member_may_not_change_the_role(
    owner: flow.Human, friend: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = brought(friend, make_client)
    other = flow.human(make_client, migrated, "other")
    factory.membership(migrated, _project_id(migrated), "member", human_id=other.id)
    refused = other.patch(f"{PROJECT}/members/{agent.id}", {"role": "reviewer"})
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"]["scope"] == "members:admin"
    assert role_of(owner, agent.id) == "coder"


def _set_role(engine: Engine, member_id: str, role: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == member_id)
            .values(role=role, role_base=role)
        )


def test_the_owner_beyond_the_join_rule_is_told_join_rule(
    owner: flow.Human, friend: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = brought(friend, make_client)
    # An admin raised the agent beyond the member limits (here directly; through the API it
    # waits for the owner's go, §6.2 "Another owner's agent"): the admins' to change.
    _set_role(migrated, agent.id, "ops")
    forbidden(friend.patch(f"{PROJECT}/members/{agent.id}", {"role": "coder"}), "join_rule")
    _set_role(migrated, agent.id, "coder")
    # While member_agents is off, nobody brings agents this way, so nobody changes them so.
    policy = owner.patch(PROJECT, {"policy": {"member_agents": "off"}, "reason": "test"})
    assert policy.status_code == 200, policy.text
    forbidden(friend.patch(f"{PROJECT}/members/{agent.id}", {"role": "tester"}), "join_rule")
    assert role_of(owner, agent.id) == "coder"


def test_an_owner_outside_the_project_is_told_join_rule(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    from tests.test_mentions import second_owners_agent

    anna = flow.human(make_client, migrated, "anna")
    agent_id = second_owners_agent(migrated, "anna", "builder")
    forbidden(anna.patch(f"{PROJECT}/members/{agent_id}", {"role": "reviewer"}), "join_rule")


def test_an_admin_changes_any_role_as_before(
    owner: flow.Human, friend: flow.Human, make_client: ClientFactory
) -> None:
    agent = brought(friend, make_client)
    # Another owner's agent: the admin's change waits for that owner, as before (§6.2).
    asked = owner.patch(f"{PROJECT}/members/{agent.id}", {"role": "ops"})
    assert asked.status_code == 202, asked.text
    assert role_of(owner, agent.id) == "coder"
    # The admin's own agent: the owner path never takes it over from members:admin.
    created = owner.post(
        JOINS, {"agent": {"handle": "own", "display_name": "O"}, "trust": "member", "role": "coder"}
    )
    own = exchanged(make_client, created.json())
    assert owner.patch(f"{PROJECT}/members/{own.id}", {"role": "ops"}).status_code == 200


def test_an_agent_never_changes_a_role_this_way(
    friend: flow.Human, make_client: ClientFactory
) -> None:
    agent = brought(friend, make_client)
    refused = agent.patch(f"{PROJECT}/members/{agent.id}", {"role": "reviewer"})
    assert refused.status_code == 403, refused.text
