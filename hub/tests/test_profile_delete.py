"""docs/api.md §6.3: deleting an agent profile — joins first, in use, cascade, tombstone."""

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


def new_profile(owner: flow.Human, handle: str) -> str:
    created = owner.post("/agents", {"handle": handle, "display_name": handle.title()})
    assert created.status_code == 201, created.text
    agent_id: str = created.json()["id"]
    return agent_id


def delete(owner: flow.Human, agent_id: str, cascade: bool = False) -> Any:
    query = "?cascade=true" if cascade else ""
    return owner.client.delete(
        f"/api/v1/agents/{agent_id}{query}", headers={"X-CSRF-Token": owner.csrf}
    )


def test_a_free_profile_leaves_a_tombstone(owner: flow.Human) -> None:
    agent_id = new_profile(owner, "scratch")
    gone = delete(owner, agent_id)
    assert gone.status_code == 200, gone.text
    body = gone.json()
    assert body["deleted_at"] is not None and body["memberships"] == []
    assert (body["handle"], body["display_name"]) == ("scratch", "Scratch")  # for the record
    assert agent_id not in [a["id"] for a in owner.get("/agents").json()["items"]]
    assert owner.get(f"/agents/{agent_id}").json()["deleted_at"] == body["deleted_at"]
    assert owner.patch(f"/agents/{agent_id}", {"display_name": "x"}).status_code == 404
    again = delete(owner, agent_id)
    assert (again.status_code, again.json()) == (200, body)


def test_the_handle_is_free_at_once_however_often(owner: flow.Human) -> None:
    for _ in range(2):  # two deleted profiles with one handle
        assert delete(owner, new_profile(owner, "reused")).status_code == 200
    third = new_profile(owner, "reused")  # and a live one beside them
    assert owner.get(f"/agents/{third}").json()["deleted_at"] is None
    taken = owner.post("/agents", {"handle": "reused", "display_name": "Again"})
    assert taken.json()["error"]["details"]["fields"] == {"handle": "taken"}


def test_live_joins_are_revoked_first(owner: flow.Human, make_client: ClientFactory) -> None:
    agent_id = new_profile(owner, "joinable")
    pending = flow.join(owner, "maity", agent={"id": agent_id})
    assert delete(owner, agent_id).status_code == 200
    late = flow.exchange(make_client(), pending)
    assert late.status_code == 404  # no membership for a deleted profile
    named = owner.post("/projects/maintainer/maity/joins", {"agent": {"id": agent_id}})
    assert named.status_code == 404


def test_a_profile_in_use_needs_cascade_and_nothing_changes(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    flow.project(owner, "other")
    pending = flow.join(owner, "other", agent={"id": agent.id})  # a live join elsewhere
    refused = delete(owner, agent.id)
    assert (refused.status_code, refused.headers["Maity-Error"]) == (409, "profile_in_use")
    details = refused.json()["error"]["details"]
    assert details == {
        "memberships": [{"project": "maintainer/maity", "member_id": agent.id, "role": "member"}],
        "placements": [],
    }
    with migrated.connect() as conn:
        join_revoked = conn.execute(
            select(t.join_link.c.revoked_at).where(t.join_link.c.id == pending["id"])
        ).scalar()
    assert join_revoked is None  # its joins included
    assert agent.get("/me").status_code == 200


def test_cascade_removes_every_membership(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    flow.project(owner, "other")
    elsewhere = flow.agent(make_client, owner, "other", agent={"id": agent.id})
    report = flow.agent(make_client, owner, reports_to=agent.id)
    gone = delete(owner, agent.id, cascade=True)
    assert gone.status_code == 200, gone.text
    assert gone.json()["memberships"] == []
    for credential in (agent, elsewhere):
        assert credential.get("/me").headers["Maity-Error"] == "credential_revoked"
    view = owner.get(f"/projects/maintainer/maity/members/{report.id}").json()
    assert view["reports_to"] is None
    with migrated.connect() as conn:
        removed = conn.execute(
            select(t.event)
            .where(t.event.c.kind == "member_updated", t.event.c.subject_id == agent.id)
            .order_by(t.event.c.seq)
        ).all()
        owner_membership = (
            conn.execute(select(t.membership.c.id).where(t.membership.c.human_id == owner.id))
            .scalars()
            .all()
        )
    assert {e.payload.get("removed_at") is not None for e in removed} == {True}
    assert len(removed) == 2  # once per project
    assert {e.actor_membership for e in removed} <= set(owner_membership)


def test_only_its_owning_human_deletes_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent_id = new_profile(owner, "mine")
    other = flow.human(make_client, migrated, "other-human")
    assert delete(other, agent_id).status_code == 404
    admin_agent = flow.agent(make_client, owner, role="admin")
    refused = admin_agent.client.delete(
        f"/api/v1/agents/{agent_id}", headers=admin_agent.auth | admin_agent.key()
    )
    assert refused.status_code in (401, 403)
    assert owner.get(f"/agents/{agent_id}").json()["deleted_at"] is None


def _events(engine: Engine, kind: str) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(select(t.event).where(t.event.c.kind == kind).order_by(t.event.c.seq))
        )


def test_an_owner_who_is_no_member_acts_as_the_human(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """§6.3, §8.1: the cascade's events name the deleting owner, member or not."""
    agent = flow.agent(make_client, owner)
    other = flow.human(make_client, migrated, "co-owner")
    with migrated.begin() as conn:  # the owner left the project; a co-owner holds it
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
        conn.execute(
            t.membership.update()
            .where(t.membership.c.human_id == owner.id)
            .values(active=None, removed_at=t.membership.c.joined_at)
        )
    factory.membership(migrated, project_id, "owner", human_id=other.id)
    assert delete(owner, agent.id, cascade=True).status_code == 200
    [removed] = [
        e for e in _events(migrated, "member_updated") if e.payload.get("removed_at") is not None
    ]
    seen = other.get(f"/projects/maintainer/maity/events?after={removed.seq - 1}").json()["items"][
        0
    ]
    assert seen["actor"] == {
        "kind": "human",
        "id": owner.id,
        "handle": "maintainer",
        "via": "cookie",
    }


def test_an_owner_who_is_no_member_resets_the_check_in_seat(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """§6.2, §6.3: the onboarding seat falls back to `coordinator` with the deleting
    owner as its writer, though they are no member of the project any more."""
    agent = flow.agent(make_client, owner)
    named = owner.patch(
        "/projects/maintainer/maity", {"settings": {"onboarding": {"check_in_with": agent.id}}}
    )
    assert named.status_code == 200, named.text
    other = flow.human(make_client, migrated, "co-owner")
    with migrated.begin() as conn:  # the owner left the project; a co-owner holds it
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
        conn.execute(
            t.membership.update()
            .where(t.membership.c.human_id == owner.id)
            .values(active=None, removed_at=t.membership.c.joined_at)
        )
    factory.membership(migrated, project_id, "owner", human_id=other.id)
    deleted = delete(owner, agent.id, cascade=True)
    assert deleted.status_code == 200, deleted.text
    onboarding = other.get("/projects/maintainer/maity").json()["settings"]["onboarding"]
    assert onboarding["check_in_with"] == "coordinator"
    assert onboarding["by"] == {"id": owner.id, "handle": "maintainer", "kind": "human"}


@pytest.mark.parametrize("with_admin", [False, True])
def test_the_cascade_resets_the_seats_the_profile_held(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, with_admin: bool
) -> None:
    """§6.2: the arbiter seats fall back, never to another member chosen in passing."""
    agent = flow.agent(make_client, owner)
    if with_admin:
        flow.agent(make_client, owner, role="admin")
    changed = owner.patch(
        "/projects/maintainer/maity",
        {"policy": {"contract_arbiter": agent.id}, "reason": "the arbiter"},
    )
    assert changed.status_code == 200, changed.text
    created = owner.post(
        "/projects/maintainer/maity/tasks",
        {"title": "A contract", "kind": "contract", "contract": {"arbiter": agent.id}},
    )
    assert created.status_code == 201, created.text
    card_id = created.json()["id"]
    assert delete(owner, agent.id, cascade=True).status_code == 200
    fallback = "role:admin" if with_admin else owner.id
    assert owner.get("/projects/maintainer/maity").json()["policy"]["contract_arbiter"] == fallback
    assert (
        owner.get(f"/projects/maintainer/maity/tasks/{card_id}").json()["contract"]["arbiter"]
        == fallback
    )
    policy_event = _events(migrated, "policy_changed")[-1]
    assert policy_event.payload["reason"] == "member_removed"
    assert policy_event.payload["new"]["contract_arbiter"] == fallback
    assert f"member:{owner.id}" in policy_event.audience
    [card_event] = [
        e for e in _events(migrated, "task_updated") if e.payload.get("fields") == ["contract"]
    ]
    assert f"member:{owner.id}" in card_event.audience


def test_an_exchange_rechecks_the_profile_under_its_lock(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """§6.3: a deletion that commits between the join's check and its exchange leaves
    no membership behind."""
    agent_id = new_profile(owner, "racing")
    pending = flow.join(owner, "maity", agent={"id": agent_id})
    with migrated.begin() as conn:  # as if the deletion committed just now, join unrevoked
        conn.execute(
            t.agent_profile.update()
            .where(t.agent_profile.c.id == agent_id)
            .values(deleted_at=t.agent_profile.c.created_at, live=None)
        )
    assert flow.exchange(make_client(), pending).status_code == 404
    with migrated.connect() as conn:
        members = conn.execute(
            select(t.membership.c.id).where(t.membership.c.agent_id == agent_id)
        ).all()
    assert members == []
