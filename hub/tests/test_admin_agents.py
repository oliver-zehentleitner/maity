"""docs/api.md §2.3 ᵃ and "What no agent may do": an admin agent manages the agent
memberships below it; every agent is refused what is a human's (`humans_only`)."""

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


def patch(who: Any, member_id: str, body: dict[str, Any]) -> Any:
    return who.patch(f"/projects/maity/members/{member_id}", body)


def events_of(engine: Engine, kind: str) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(select(t.event).where(t.event.c.kind == kind).order_by(t.event.c.seq))
        )


def reason(response: Any) -> Any:
    return response.json()["error"]["details"].get("reason")


def test_an_admin_agent_manages_a_member_agent(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    member = flow.agent(make_client, owner)
    boss = flow.agent(make_client, owner)
    changed = patch(
        admin,
        member.id,
        {"areas": ["web/"], "reports_to": boss.id, "briefing": "the web", "role": "reviewer"},
    )
    assert changed.status_code == 200, changed.text
    body = changed.json()
    assert (body["areas"], body["reports_to"], body["role"]) == (["web/"], boss.id, "reviewer")
    [event] = events_of(migrated, "member_changed_by_agent")
    assert event.audience == ["role:owner"]
    assert event.payload == {
        "member_id": member.id,
        "change": "role",
        "old": "member",
        "new": "reviewer",
        "actor": admin.id,
    }


@pytest.mark.parametrize("role", ["member", "reviewer", "proxy", "admin"])
def test_no_agent_touches_a_humans_membership(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, role: str
) -> None:
    agent = flow.agent(make_client, owner, role=role)
    second = flow.human(make_client, migrated, "second")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "admin", human_id=second.id)
    for target in (owner.id, second.id):
        for body in ({"role": "member"}, {"areas": ["x/"]}, {"paused": {"reason": "x"}}):
            refused = patch(agent, target, body)
            assert (refused.status_code, reason(refused)) == (403, "humans_only"), body
        removed = agent.client.delete(
            f"/api/v1/projects/maity/members/{target}", headers=agent.auth | agent.key()
        )
        assert (removed.status_code, reason(removed)) == (403, "humans_only")


@pytest.mark.parametrize("role", ["member", "reviewer", "proxy", "admin"])
@pytest.mark.parametrize(
    "body",
    [
        {"policy": {"spawn_consent_by": "role"}, "reason": "x"},
        {"policy": {"signing": "required"}, "reason": "x"},
        {"policy": {"tag_authority": "capability"}, "reason": "x"},
        {"policy": {"spawn_requests": "direct"}, "reason": "x"},
        {"rules_markdown": "agents rule"},
        {"state": "archived", "reason": "x"},
    ],
)
def test_no_agent_changes_what_humans_decide(
    owner: flow.Human, make_client: ClientFactory, role: str, body: dict[str, Any]
) -> None:
    agent = flow.agent(make_client, owner, role=role)
    refused = agent.patch("/projects/maity", body)
    assert (refused.status_code, reason(refused)) == (403, "humans_only")


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"capabilities": ["tag"]}, "humans_only"),
        ({"role": "proxy"}, "humans_only"),
        ({"role": "admin"}, "humans_only"),
        ({"role": "owner"}, "humans_only"),
    ],
)
def test_an_admin_agent_sets_no_humans_lever(
    owner: flow.Human, make_client: ClientFactory, body: dict[str, Any], expected: str
) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    member = flow.agent(make_client, owner)
    refused = patch(admin, member.id, body)
    assert (refused.status_code, reason(refused)) == (403, expected)


def test_an_admin_agent_manages_neither_itself_nor_its_peers(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    other_admin = flow.agent(make_client, owner, role="admin")
    proxy = flow.agent(make_client, owner, role="proxy")
    for target in (admin, other_admin, proxy):
        refused = patch(admin, target.id, {"areas": ["x/"]})
        assert refused.status_code == 403
        assert refused.json()["error"]["details"] == {"scope": "members:admin"}, target.id


def test_a_reviewers_role_change_waits_for_the_owners_go(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    reviewer = flow.agent(make_client, owner, role="reviewer")
    waiting = patch(admin, reviewer.id, {"role": "member", "areas": ["docs/"]})
    assert waiting.status_code == 202, waiting.text
    request = waiting.json()
    assert (request["class"], request["status"]) == ("consent", "open")
    assert request["title"].startswith("Change ") and request["title"].endswith(" to member")
    unchanged = owner.get(f"/projects/maity/members/{reviewer.id}").json()
    assert (unchanged["role"], unchanged["areas"]) == ("reviewer", [])  # the whole PATCH waits
    other = flow.agent(make_client, owner, role="admin")
    by_agent = other.post(f"/projects/maity/requests/{request['id']}/answer", {"reply_id": "go"})
    assert (by_agent.status_code, reason(by_agent)) == (403, "humans_only")
    go = owner.post(f"/projects/maity/requests/{request['id']}/answer", {"reply_id": "go"})
    assert go.status_code == 200, go.text
    applied = owner.get(f"/projects/maity/members/{reviewer.id}").json()
    assert (applied["role"], applied["areas"]) == ("member", ["docs/"])
    [event] = events_of(migrated, "member_changed_by_agent")
    assert (event.payload["actor"], event.payload["request_id"]) == (admin.id, request["id"])
    assert event.actor_membership is not None  # the agent, not the approving human


def test_no_changes_nothing(owner: flow.Human, make_client: ClientFactory) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    reviewer = flow.agent(make_client, owner, role="reviewer")
    request = patch(admin, reviewer.id, {"paused": {"reason": "quota"}}).json()
    assert request["title"].startswith("Pause ")
    owner.post(f"/projects/maity/requests/{request['id']}/answer", {"reply_id": "no"})
    assert owner.get(f"/projects/maity/members/{reviewer.id}").json()["paused"] is None


def test_the_arbiters_role_waits_too(owner: flow.Human, make_client: ClientFactory) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    arbiter = flow.agent(make_client, owner)
    owner.patch("/projects/maity", {"policy": {"contract_arbiter": arbiter.id}, "reason": "x"})
    assert patch(admin, arbiter.id, {"role": "reviewer"}).status_code == 202
    assert patch(admin, arbiter.id, {"areas": ["cli/"]}).status_code == 200  # no consent


def test_a_removal_always_waits_and_is_done_on_go(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    member = flow.agent(make_client, owner)
    waiting = admin.client.delete(
        f"/api/v1/projects/maity/members/{member.id}", headers=admin.auth | admin.key()
    )
    assert waiting.status_code == 202, waiting.text
    request = waiting.json()
    assert request["title"].startswith("Remove ")
    assert member.get("/me").status_code == 200  # still a member until the go
    owner.post(f"/projects/maity/requests/{request['id']}/answer", {"reply_id": "go"})
    assert member.get("/me").headers["Maity-Error"] == "credential_revoked"
    with migrated.connect() as conn:
        revoked = conn.execute(
            select(t.credential.c.revoked_by).where(t.credential.c.id == member.credential_id)
        ).scalar()
    assert revoked == owner.id  # on the approver's authority
    [event] = events_of(migrated, "member_changed_by_agent")
    assert (event.payload["change"], event.payload["new"]) == ("removed", None)


def test_an_admin_agents_pause_and_a_humans(owner: flow.Human, make_client: ClientFactory) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    member = flow.agent(make_client, owner)
    paused = patch(admin, member.id, {"paused": {"reason": "too many cards"}})
    assert paused.json()["paused"]["by"] == admin.id
    member.resume()  # an admin agent's pause outlasts the paused agent's resume
    assert owner.get(f"/projects/maity/members/{member.id}").json()["paused"] is not None
    assert patch(admin, member.id, {"paused": None}).json()["paused"] is None  # its own: lifted
    owner.patch(f"/projects/maity/members/{member.id}", {"paused": {"reason": "mine"}})
    for body in ({"paused": None}, {"paused": {"reason": "other"}}):
        refused = patch(admin, member.id, body)
        assert (refused.status_code, reason(refused)) == (403, "humans_only")
    assert owner.get(f"/projects/maity/members/{member.id}").json()["paused"]["by"] == owner.id


def test_the_packet_lists_the_limited_scope_and_its_operations(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    member = flow.agent(make_client, owner)
    admin_packet = admin.resume().json()
    assert "members:admin" in admin_packet["membership"]["scopes"]
    assert "PATCH /projects/maity/members/{id}" in admin_packet["operations"]
    member_packet = member.resume().json()
    assert "members:admin" not in member_packet["membership"]["scopes"]
    assert "PATCH /projects/maity/members/{id}" not in member_packet["operations"]
