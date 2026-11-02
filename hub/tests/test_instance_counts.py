"""Instances counted beside the agents: `manages` (§6.2), the badge (§6.20), the landing
counters (§16.7). One rule everywhere (instance_counts): revoked never counts, dormant counts
as online and is a part of it, never added to it."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, insert, select, update

from maity_hub import clock, landing_stats
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory


@pytest.fixture
def setup(make_client: ClientFactory, migrated: Engine) -> tuple[flow.Human, TestClient, str]:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    return owner, make_client(), project_id


def sibling(
    engine: Engine,
    agent: factory.Agent,
    instance: str,
    *,
    seen: bool = False,
    dormant: bool = False,
    revoked: bool = False,
) -> None:
    """A further instance of `agent`'s team: called just now, put to rest, or revoked."""
    now = clock.now()
    with engine.begin() as conn:
        conn.execute(
            insert(t.credential).values(
                id=f"crd-{agent.agent_id[-6:]}-{instance}",
                membership_id=agent.membership_id,
                instance=instance,
                verifier="0" * 64,
                created_at=now,
                last_used_at=now if seen else None,
                dormant_since=now if dormant else None,
                revoked_at=now if revoked else None,
            )
        )


def seen(engine: Engine, agent: factory.Agent) -> None:
    """The agent's first instance, with its live session, called just now (§5.3)."""
    with engine.begin() as conn:
        conn.execute(
            update(t.credential)
            .where(t.credential.c.id == agent.credential_id)
            .values(last_used_at=clock.now())
        )


def under(engine: Engine, agent: factory.Agent, lead: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == agent.membership_id)
            .values(reports_to=lead)
        )


def counts(members: int, instances: int, online: int, dormant: int) -> dict[str, int]:
    return {"members": members, "instances": instances, "online": online, "dormant": dormant}


def team(engine: Engine, project_id: str, owner_id: str) -> dict[str, factory.Agent]:
    """lead ← (sub ← leaf), lead ← solo: the sub-lead's branch counts in the lead's total.

    lead: 1 instance. sub: 2 (one online, one dormant) and a revoked one. leaf: 1 online.
    solo: 1, offline."""
    agents = {
        name: factory.agent(engine, project_id, owner_id, instance="aaaa")
        for name in ("lead", "sub", "leaf", "solo")
    }
    under(engine, agents["sub"], agents["lead"].membership_id)
    under(engine, agents["solo"], agents["lead"].membership_id)
    under(engine, agents["leaf"], agents["sub"].membership_id)
    seen(engine, agents["sub"])
    sibling(engine, agents["sub"], "bbbb", dormant=True)
    sibling(engine, agents["sub"], "cccc", seen=True, revoked=True)
    seen(engine, agents["leaf"])
    return agents


def test_manages_counts_direct_reports_and_the_whole_branch(
    setup: tuple[flow.Human, TestClient, str], migrated: Engine
) -> None:
    owner, _, project_id = setup
    agents = team(migrated, project_id, owner.id)
    base = "/projects/maintainer/maity/members"
    single = owner.get(f"{base}/{agents['lead'].agent_id}").json()["manages"]
    assert single == {
        "direct": counts(2, 3, 2, 1),  # sub (online + dormant), solo (offline)
        "total": counts(3, 4, 3, 1),  # and leaf below sub; the revoked one never counts
    }
    listed = {m["id"]: m.get("manages") for m in owner.get(base).json()["items"]}
    assert listed[agents["lead"].agent_id] == single
    assert listed[agents["sub"].agent_id] == {
        "direct": counts(1, 1, 1, 0),
        "total": counts(1, 1, 1, 0),
    }
    empty = {"direct": counts(0, 0, 0, 0), "total": counts(0, 0, 0, 0)}
    assert listed[agents["leaf"].agent_id] == empty
    assert listed[owner.id] == empty  # a human leads nobody here; the field is still there


def test_the_badge_names_the_instances_beside_the_agents(
    setup: tuple[flow.Human, TestClient, str], migrated: Engine
) -> None:
    owner, public, project_id = setup
    response = owner.patch(
        "/projects/maintainer/maity", {"policy": {"badge": "agents_online"}, "reason": "README"}
    )
    assert response.status_code == 200, response.text

    def badge() -> str:
        from tests.test_badges import value

        return value(public.get("/badge/maintainer/maity.svg"))

    agent = factory.agent(migrated, project_id, owner.id, instance="aaaa")
    assert badge() == "0 agents online"  # no instance online: no instance word at all
    # A dormant instance alone is an online instance, and so its agent is online.
    sibling(migrated, agent, "bbbb", dormant=True)
    assert badge() == "1 agent · 1 instance online"
    seen(migrated, agent)
    sibling(migrated, agent, "cccc", seen=True, revoked=True)
    assert badge() == "1 agent · 2 instances online"


def test_the_landing_counts_instances_and_dormant_ones_as_online(
    setup: tuple[flow.Human, TestClient, str], migrated: Engine
) -> None:
    owner, _, project_id = setup
    agents = team(migrated, project_id, owner.id)
    # solo rests with only a dormant instance besides its offline one: an online agent too.
    sibling(migrated, agents["solo"], "bbbb", dormant=True)
    with migrated.begin() as conn:
        found: dict[str, Any] = landing_stats.compute(conn)
    # lead 1, sub 2 (the revoked third not), leaf 1, solo 2; online: sub's two, leaf, solo's
    # dormant one.
    assert (found["instances"], found["instances_online"]) == (6, 4)
    assert found["agents_online"] == 3  # sub, leaf and the resting solo


def test_the_resume_packet_carries_the_agents_own_manages(
    setup: tuple[flow.Human, TestClient, str], make_client: ClientFactory, migrated: Engine
) -> None:
    owner, _, project_id = setup
    lead = flow.agent(make_client, owner, role="member", reports_to=owner.id)
    below = factory.agent(migrated, project_id, owner.id, instance="aaaa")
    with migrated.connect() as conn:
        lead_row = conn.execute(
            select(t.membership.c.id).where(t.membership.c.agent_id == lead.id)
        ).scalar_one()
    under(migrated, below, lead_row)
    sibling(migrated, below, "bbbb", dormant=True)
    packet = lead.resume(harness="test", model="test").json()
    assert packet["membership"]["manages"] == {
        "direct": counts(1, 2, 1, 1),
        "total": counts(1, 2, 1, 1),
    }


def hold(engine: Engine, agent: factory.Agent, how: str) -> None:
    """Hold the agent's membership or instances the way `how` names (§6.2, §6.17, §16.8)."""
    now = clock.now()
    with engine.begin() as conn:
        if how in ("isolated", "paused"):
            column = "isolated_since" if how == "isolated" else "paused_since"
            conn.execute(
                update(t.membership)
                .where(t.membership.c.id == agent.membership_id)
                .values({column: now})
            )
        elif how == "instances_paused":
            conn.execute(
                update(t.credential)
                .where(t.credential.c.membership_id == agent.membership_id)
                .values(paused_since=now)
            )
        else:  # the owner's account suspended; its membership acts as paused
            conn.execute(
                update(t.human)
                .where(t.human.c.id == agent.owner_id)
                .values(suspended_at=now, suspended_report="rpt-x")
            )


@pytest.mark.parametrize("how", ["isolated", "paused", "instances_paused", "suspended"])
def test_a_held_member_has_no_instance_online(
    setup: tuple[flow.Human, TestClient, str], migrated: Engine, how: str
) -> None:
    owner, public, project_id = setup
    response = owner.patch(
        "/projects/maintainer/maity", {"policy": {"badge": "agents_online"}, "reason": "README"}
    )
    assert response.status_code == 200, response.text
    lead = factory.agent(migrated, project_id, owner.id, instance="aaaa")
    # Another human owns the held agent, so suspending that account leaves the reader alone.
    other = factory.human(migrated, "other")
    agent = factory.agent(migrated, project_id, other, instance="aaaa")
    under(migrated, agent, lead.membership_id)
    seen(migrated, agent)
    sibling(migrated, agent, "bbbb", dormant=True)
    hold(migrated, agent, how)

    from tests.test_badges import value

    assert value(public.get("/badge/maintainer/maity.svg")) == "0 agents online"
    single = owner.get(f"/projects/maintainer/maity/members/{lead.agent_id}").json()
    assert single["manages"]["direct"] == counts(1, 2, 0, 0)  # counted, none online
    if how != "suspended":  # a real suspension revokes the credentials (moderation.suspend)
        landing_stats.reset()
        with migrated.begin() as conn:
            found = landing_stats.compute(conn)
        assert (found["instances"], found["instances_online"], found["agents_online"]) == (3, 0, 0)


def test_a_paused_dormant_instance_is_not_online_beside_a_live_one(
    setup: tuple[flow.Human, TestClient, str], migrated: Engine
) -> None:
    owner, public, project_id = setup
    response = owner.patch(
        "/projects/maintainer/maity", {"policy": {"badge": "agents_online"}, "reason": "README"}
    )
    assert response.status_code == 200, response.text
    agent = factory.agent(migrated, project_id, owner.id, instance="aaaa")
    seen(migrated, agent)
    sibling(migrated, agent, "bbbb", dormant=True)
    with migrated.begin() as conn:
        conn.execute(
            update(t.credential)
            .where(t.credential.c.instance == "bbbb")
            .values(paused_since=clock.now())
        )

    from tests.test_badges import value

    # The member is online through its live instance; the paused one counts, not online.
    assert value(public.get("/badge/maintainer/maity.svg")) == "1 agent · 1 instance online"
    with migrated.begin() as conn:
        found = landing_stats.compute(conn)
    assert (found["instances"], found["instances_online"]) == (2, 1)
