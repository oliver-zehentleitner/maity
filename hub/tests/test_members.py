"""docs/api.md §6.2, §6.3, §5.3 and §10: members, profiles, pauses, credentials."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import clock
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


def _project_id(engine: Engine) -> str:
    with engine.connect() as conn:
        project_id: str = conn.execute(select(t.project.c.id)).scalar_one()
    return project_id


def _last(engine: Engine, kind: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            select(t.event).where(t.event.c.kind == kind).order_by(t.event.c.seq.desc())
        ).first()


def test_the_member_view_has_the_contract_shape(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner, role="member", areas=["hub/"], reports_to=owner.id)
    agent.resume(harness="Claude Code", model="claude-opus-5-5")
    view = owner.get(f"/projects/maintainer/maity/members/{agent.id}").json()
    assert view["name"] == f"maintainer/{view['handle']}"  # the global name (§6.3)
    [instance] = view["instances"]
    assert instance["name"] == f"{view['name']}#{instance['id']}"
    assert agent.get("/me").json()["member"]["name"] == view["name"]
    assert set(view) == {
        "id",
        "kind",
        "handle",
        "aliases",
        "name",
        "display_name",
        "avatar_url",  # null: no picture uploaded (§6.10)
        "owner_id",
        "trust",
        "role",
        "reports_to",
        "cross_owner",
        "line_consent",
        "areas",
        "capabilities",
        "harness",
        "model",
        "session",
        "last_seen_at",
        "presence",
        "paused",
        "availability",  # §6.12
        "availability_policy",
        "covered_by",
        "covering",
        "joined_at",
        "briefing",  # the owner holds members:admin
        "briefing_by",  # with it: who wrote it, its version and when (§6.2)
        "briefing_version",
        "briefing_updated_at",
        "placement",
        "owner",  # likewise, and it owns the agent (§6.2)
        "credentials",
        "shared_environment",  # likewise (§5.3)
        "owner_preferences",  # likewise (§19.4)
        "team",  # the team's rulebook and its instances (§6.17, §6.18)
        "instances",
        "keep_the_why_unconfirmed",  # §6.1: set while the commitment is open
    }
    assert (view["cross_owner"], view["line_consent"]) == (False, False)
    assert (view["kind"], view["owner_id"], view["reports_to"]) == ("agent", owner.id, owner.id)
    assert (view["harness"], view["model"], view["presence"]) == (
        "Claude Code",
        "claude-opus-5-5",
        "online",
    )
    assert set(view["session"]) == {"id", "harness", "model", "client", "started_at", "listening"}
    human = owner.get(f"/projects/maintainer/maity/members/{owner.id}").json()
    assert "owner_id" not in human and "session" not in human and "harness" not in human


def test_members_are_listed_humans_first_then_by_handle(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    flow.agent(make_client, owner, agent={"handle": "zed", "display_name": "Z"})
    flow.agent(make_client, owner, agent={"handle": "abe", "display_name": "A"})
    items = owner.get("/projects/maintainer/maity/members").json()["items"]
    assert [m["handle"] for m in items] == ["maintainer", "abe", "zed"]


def test_presence_is_computed_from_the_last_call(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    assert (
        owner.get(f"/projects/maintainer/maity/members/{agent.id}").json()["presence"] == "offline"
    )  # no session
    agent.resume()
    start = clock.now()
    for offset, expected in ((60, "online"), (121, "away"), (2 * 3600 + 1, "offline")):
        clock.set_source(lambda offset=offset: start + timedelta(seconds=offset))  # type: ignore[misc]
        view = owner.get(f"/projects/maintainer/maity/members/{agent.id}").json()
        assert view["presence"] == expected, offset


def test_a_role_change_is_a_rules_bump(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    response = owner.patch(
        f"/projects/maintainer/maity/members/{agent.id}", {"role": "reviewer", "areas": ["web/"]}
    )
    assert (response.json()["role"], response.json()["areas"]) == ("reviewer", ["web/"])
    event = _last(migrated, "member_updated")
    assert event.audience == ["all"] and event.payload["rules_version"] == 2
    with migrated.connect() as conn:
        assert conn.execute(select(t.project.c.rules_changed_seq)).scalar() == event.seq


@pytest.mark.parametrize(
    ("body", "fields"),
    [
        ({"trust": "owner"}, {"trust": "humans_only"}),
        ({"trust": "boss"}, {"trust": "unknown"}),
        ({"role": "boss"}, {"role": "unknown"}),
        ({"role": "member"}, {"role": "unknown"}),  # the old single role is gone (§2.3)
        ({"reports_to": "agt-nobody"}, {"reports_to": "not_a_member"}),
        ({"capabilities": ["deploy"]}, {"capabilities": "unknown"}),
    ],
)
def test_member_changes_are_checked(
    owner: flow.Human, make_client: ClientFactory, body: dict[str, Any], fields: dict[str, str]
) -> None:
    agent = flow.agent(make_client, owner)
    response = owner.patch(f"/projects/maintainer/maity/members/{agent.id}", body)
    assert response.json()["error"]["details"]["fields"] == fields


def test_the_last_owner_stays(owner: flow.Human) -> None:
    demote = owner.patch(f"/projects/maintainer/maity/members/{owner.id}", {"trust": "admin"})
    assert demote.json()["error"]["details"]["fields"] == {"trust": "last_owner"}
    remove = owner.delete(f"/projects/maintainer/maity/members/{owner.id}")
    assert remove.json()["error"]["details"]["fields"] == {"member": "last_owner"}


def test_only_an_owner_grants_admin_or_proxy_and_touches_an_owner(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """§2.3 "The owner's rights": a human with trust admin manages members, but never
    grants trust owner or admin or the role proxy, nor lowers or removes an owner."""
    project_id = _project_id(migrated)
    admin = flow.human(make_client, migrated, "deputy")
    factory.membership(migrated, project_id, "admin", human_id=admin.id)
    co_owner = flow.human(make_client, migrated, "partner")
    factory.membership(migrated, project_id, "owner", human_id=co_owner.id)
    agent = flow.agent(make_client, owner)
    path = "/projects/maintainer/maity/members"

    def refused(response: Any) -> None:
        assert response.status_code == 403, response.text
        assert response.json()["error"]["details"] == {"reason": "owner_only"}

    refused(admin.patch(f"{path}/{agent.id}", {"trust": "admin"}))
    refused(admin.patch(f"{path}/{agent.id}", {"trust": "admin", "role": "proxy"}))
    refused(admin.patch(f"{path}/{co_owner.id}", {"trust": "admin"}))
    refused(admin.delete(f"{path}/{co_owner.id}"))
    # Below admin it manages as before; the owner may do all of it.
    # An admin's change of the owner's agent waits for the owner's go (§6.2, "Another owner's
    # agent"); the owner changes their own agent at once.
    asked = admin.patch(f"{path}/{agent.id}", {"role": "reviewer"})
    assert asked.status_code == 202, asked.text
    assert (
        owner.post(f"/requests/{asked.json()['id']}/answer", {"reply_id": "go"}).status_code == 200
    )
    assert owner.patch(f"{path}/{agent.id}", {"trust": "admin"}).status_code == 200
    assert owner.patch(f"{path}/{co_owner.id}", {"trust": "admin"}).status_code == 200


def test_members_admin_beyond_admin_agents_is_for_human_memberships(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    # An admin agent holds members:admin within §2.3 ᵃ only (tests/test_admin_agents.py);
    # a reviewer agent none of it.
    reviewer = flow.agent(make_client, owner, role="reviewer")
    other = flow.agent(make_client, owner)
    response = reviewer.patch(
        f"/projects/maintainer/maity/members/{other.id}", {"role": "reviewer"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["details"] == {"scope": "members:admin"}


def test_a_pause_set_by_a_human_tells_reports_to_and_admins(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner, reports_to=owner.id)
    response = owner.patch(
        f"/projects/maintainer/maity/members/{agent.id}", {"paused": {"reason": "quota"}}
    )
    paused = response.json()["paused"]
    assert (paused["reason"], paused["by"]) == ("quota", owner.id)
    assert response.json()["presence"] == "paused"
    event = _last(migrated, "session_paused")
    # The member itself first: its long-poll wakes (§5.3).
    assert event.audience == [f"member:{agent.id}", f"member:{owner.id}", "trust:admin"]
    agent.resume()  # a human's pause survives the agent's resume
    assert (
        owner.get(f"/projects/maintainer/maity/members/{agent.id}").json()["paused"]["reason"]
        == "quota"
    )
    cleared = owner.patch(f"/projects/maintainer/maity/members/{agent.id}", {"paused": None})
    assert cleared.json()["paused"] is None


def test_the_agent_declares_its_own_pause(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    no_key = agent.client.patch("/api/v1/me", json={"paused": {"reason": "x"}}, headers=agent.auth)
    assert no_key.json()["error"]["details"]["fields"] == {"Idempotency-Key": "required"}
    response = agent.patch("/me", {"paused": {"reason": "waiting for the contract"}})
    # The calling instance's pause, not the membership's (§5.3).
    assert response.json()["paused"] is None
    (mine,) = response.json()["instances"]
    assert mine["paused"]["by"] == agent.id and mine["presence"] == "paused"
    assert response.json()["presence"] == "paused"
    assert agent.resume().json()["membership"]["paused"] is None  # it ends with its next session
    (mine,) = owner.get(f"/projects/maintainer/maity/members/{agent.id}").json()["instances"]
    assert mine["paused"] is None


def test_removing_a_member_revokes_releases_and_allows_a_rejoin(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    agent.resume()
    with migrated.connect() as conn:
        membership_id = conn.execute(
            select(t.membership.c.id).where(t.membership.c.agent_id == agent.id)
        ).scalar_one()
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    card = factory.card(
        migrated,
        project_id,
        membership_id,
        status="in_progress",
        claim_holder=membership_id,
        lease_until=clock.now(),
    )
    response = owner.delete(f"/projects/maintainer/maity/members/{agent.id}")
    assert response.status_code == 200 and response.json()["removed_at"]
    assert agent.get("/me").headers["Maity-Error"] == "credential_revoked"
    with migrated.connect() as conn:
        row = conn.execute(select(t.card).where(t.card.c.id == card)).one()
    assert (row.claim_holder, row.status) == (None, "open")
    assert (
        owner.get(f"/projects/maintainer/maity/members/{agent.id}").headers["Maity-Error"]
        == "not_found"
    )
    again = flow.agent(make_client, owner, agent={"id": agent.id})
    assert again.id == agent.id
    assert again.get("/me").status_code == 200


# --- §6.3 agent profiles --------------------------------------------------------------


def test_profiles_belong_to_their_human(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    created = owner.post(
        "/agents",
        {
            "handle": "agent-b",
            "display_name": "Agent B",
            "git_identity": {"name": "B", "email": "b@x.y"},
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "maintainer/agent-b"  # the global name (§6.3)
    assert set(body) == {
        "id",
        "handle",
        "aliases",
        "name",
        "display_name",
        "avatar_url",
        "avatar_source",  # the profile's owner reads it (§6.10)
        "owner_id",
        "git_identity",
        "memberships",
        "created_at",
        "deleted_at",  # null until its owner deletes it (§6.3)
    }
    assert body["git_identity"] == {"name": "B", "email": "b@x.y"}
    taken = owner.post("/agents", {"handle": "agent-b", "display_name": "Again"})
    assert taken.json()["error"]["details"]["fields"] == {"handle": "taken"}
    other = flow.human(make_client, migrated, "other")
    assert other.get(f"/agents/{body['id']}").headers["Maity-Error"] == "not_found"
    assert other.post("/agents", {"handle": "agent-b", "display_name": "Mine"}).status_code == 201
    patched = owner.patch(f"/agents/{body['id']}", {"display_name": "Bee", "git_identity": None})
    assert (patched.json()["display_name"], patched.json()["git_identity"]) == ("Bee", None)


def test_agents_have_no_profile_endpoints(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    assert agent.get("/agents").headers["Maity-Error"] == "forbidden"


# --- §10 credentials --------------------------------------------------------------------


def test_credentials_are_listed_without_values(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    agent.resume()
    items = owner.get(f"/projects/maintainer/maity/members/{agent.id}/credentials").json()["items"]
    assert set(items[0]) == {
        "id",
        "member_id",
        "client",
        "created_at",
        "resumed_at",
        "last_used_at",
        "last_used_via",
        "session_id",
        "instance",
        "replaces",
        "revoked_at",
        "revoked_by",
        "revoked_reason",
    }
    assert items[0]["id"] == agent.credential_id and items[0]["resumed_at"]
    assert agent.credential.split(".")[2] not in str(items)


def test_revoking_a_credential_ends_its_session_and_is_announced(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    agent.resume()
    response = owner.post(
        f"/projects/maintainer/maity/credentials/{agent.credential_id}/revoke",
        {"reason": "lost laptop"},
    )
    body = response.json()
    assert (body["revoked_reason"], body["revoked_by"], body["session_id"]) == (
        "lost laptop",
        owner.id,
        None,
    )
    event = _last(migrated, "credential_revoked")
    assert event.audience == [f"member:{agent.id}", "trust:owner"]
    assert agent.get("/me").headers["Maity-Error"] == "credential_revoked"
    items = owner.get(f"/projects/maintainer/maity/members/{agent.id}/credentials").json()["items"]
    assert items[0]["revoked_at"]  # revoked ones stay listed


def test_only_the_owner_of_the_agent_or_credentials_admin_manage_credentials(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner, role="admin")
    other = flow.agent(make_client, owner)
    refused = agent.get(f"/projects/maintainer/maity/members/{other.id}/credentials")
    assert refused.status_code == 403
    assert refused.json()["error"]["details"] == {"scope": "credentials:admin"}
    foreign = owner.post("/projects/maintainer/maity/credentials/crd-nobody/revoke", {})
    assert foreign.headers["Maity-Error"] == "not_found"


def test_an_agent_cannot_lift_or_replace_a_humans_pause(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    owner.patch(f"/projects/maintainer/maity/members/{agent.id}", {"paused": {"reason": "stop"}})
    for body in ({"paused": None}, {"paused": {"reason": "mine now"}}):
        response = agent.patch("/me", body)
        assert response.status_code == 403
        assert response.json()["error"]["details"] == {"reason": "paused_by_human"}
    assert (
        owner.get(f"/projects/maintainer/maity/members/{agent.id}").json()["paused"]["reason"]
        == "stop"
    )


def test_a_human_member_cannot_be_paused(owner: flow.Human) -> None:
    response = owner.patch(
        f"/projects/maintainer/maity/members/{owner.id}", {"paused": {"reason": "x"}}
    )
    assert response.json()["error"]["details"]["fields"] == {"paused": "agents_only"}


def test_removing_twice_answers_the_removed_member(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    first = owner.delete(f"/projects/maintainer/maity/members/{agent.id}")
    second = owner.delete(f"/projects/maintainer/maity/members/{agent.id}")
    assert second.status_code == 200 and second.json() == first.json()
    items = owner.get(f"/projects/maintainer/maity/members/{agent.id}/credentials").json()["items"]
    assert [(c["id"], c["revoked_reason"]) for c in items] == [
        (agent.credential_id, "member_removed")
    ]


# --- §6.2 the reports_to chain is a tree -----------------------------------------------


def test_reports_to_never_forms_a_cycle(owner: flow.Human, make_client: ClientFactory) -> None:
    a = flow.agent(make_client, owner)
    b = flow.agent(make_client, owner, reports_to=a.id)
    c = flow.agent(make_client, owner, reports_to=b.id)
    cases = [(a, a), (a, b), (a, c), (b, c)]
    for member, boss in cases:
        response = owner.patch(
            f"/projects/maintainer/maity/members/{member.id}", {"reports_to": boss.id}
        )
        assert response.status_code == 400, (member.id, boss.id)
        assert response.json()["error"]["details"]["fields"] == {"reports_to": "cycle"}
    # Across the tree is fine, and so is reporting to a human.
    assert (
        owner.patch(f"/projects/maintainer/maity/members/{c.id}", {"reports_to": a.id}).status_code
        == 200
    )
    assert (
        owner.patch(
            f"/projects/maintainer/maity/members/{a.id}", {"reports_to": owner.id}
        ).status_code
        == 200
    )


def test_a_join_for_a_member_names_its_current_reports_to(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    # The exchange keeps the membership as it is, so a join adds no edge to the
    # chain: any other reports_to is refused before the link exists (§6.2).
    a = flow.agent(make_client, owner)
    b = flow.agent(make_client, owner, reports_to=a.id)
    other = owner.post(
        "/projects/maintainer/maity/joins", {"agent": {"id": a.id}, "reports_to": b.id}
    )
    assert other.json()["error"]["details"]["fields"] == {"reports_to": "differs_from_membership"}
    same = owner.post(
        "/projects/maintainer/maity/joins",
        {"agent": {"id": b.id}, "reports_to": a.id, "replaces": b.instance},
    )
    assert same.status_code == 201, same.text


def test_removing_a_member_clears_reports_to_on_its_reports(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    boss = flow.agent(make_client, owner)
    first = flow.agent(make_client, owner, reports_to=boss.id)
    second = flow.agent(make_client, owner, reports_to=boss.id)
    other = flow.agent(make_client, owner, reports_to=owner.id)
    pending = flow.join(owner, "maity", reports_to=boss.id)
    with migrated.connect() as conn:
        before = conn.execute(select(t.event.c.seq).order_by(t.event.c.seq.desc())).scalar()
    assert owner.delete(f"/projects/maintainer/maity/members/{boss.id}").status_code == 200
    for member in (first, second):
        assert (
            owner.get(f"/projects/maintainer/maity/members/{member.id}").json()["reports_to"]
            is None
        )
    assert (
        owner.get(f"/projects/maintainer/maity/members/{other.id}").json()["reports_to"] == owner.id
    )
    with migrated.connect() as conn:
        events = conn.execute(
            select(t.event).where(t.event.c.seq > before, t.event.c.kind == "member_updated")
        ).all()
        link = conn.execute(select(t.join_link).where(t.join_link.c.id == pending["id"])).one()
    updated = sorted(e.payload["id"] for e in events)
    assert updated == sorted([boss.id, first.id, second.id])
    assert all(e.payload["reports_to"] is None for e in events if e.payload["id"] != boss.id)
    assert link.reports_to is None


def test_the_exchange_drops_a_boss_removed_in_between(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    boss = flow.agent(make_client, owner)
    created = flow.join(owner, "maity", reports_to=boss.id)
    # A removal that commits after the link was read: the link still names the boss.
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership).where(t.membership.c.agent_id == boss.id).values(active=None)
        )
    response = flow.exchange(make_client(), created)
    assert response.status_code == 201, response.text
    member = owner.get(f"/projects/maintainer/maity/members/{response.headers['Maity-Member-Id']}")
    assert member.json()["reports_to"] is None  # never a former member (§6.2)
