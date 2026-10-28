"""docs/api.md §3.1 "Bringing your own agent", §3.3 and §6.1 `member_agents`: a human with
trust member creates joins for agents of their own, within the limits."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, insert, select

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.codes import digest, new_code, new_token
from maity_hub.errors import ApiError
from maity_hub.events import lock_project
from maity_hub.ids import new_id
from maity_hub.routes.joins import _require_slot
from tests import factory, flow
from tests.concurrency import finished, race, waiting
from tests.conftest import ClientFactory

JOINS = "/projects/maintainer/maity/joins"
PROJECT = "/projects/maintainer/maity"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


def _project_id(engine: Engine) -> str:
    with engine.connect() as conn:
        project_id: str = conn.execute(select(t.project.c.id)).scalar_one()
    return project_id


@pytest.fixture
def friend(make_client: ClientFactory, migrated: Engine, owner: flow.Human) -> flow.Human:
    """A human invited into the owner's project with trust member."""
    friend = flow.human(make_client, migrated, "friend")
    factory.membership(migrated, _project_id(migrated), "member", human_id=friend.id)
    return friend


def _new(n: int) -> dict[str, Any]:
    return {"agent": {"handle": f"friend-agent-{n}", "display_name": f"Agent {n}"}}


def _bring(friend: flow.Human, n: int = 1, **body: Any) -> Any:
    return friend.post(JOINS, {**_new(n), **body})


def _policy(owner: flow.Human, **change: Any) -> None:
    response = owner.patch(PROJECT, {"policy": change, "reason": "test"})
    assert response.status_code == 200, response.text


def _two_instances(owner_of_agent: flow.Human, agent_id: str) -> None:
    response = owner_of_agent.patch(f"{PROJECT}/members/{agent_id}", {"team": {"max_instances": 3}})
    assert response.status_code == 200, response.text


def _refused(response: Any, field: str) -> None:
    assert response.status_code == 403, response.text
    details = response.json()["error"]["details"]
    assert details == {"reason": "member_join_limit", "field": field}


def test_a_member_brings_an_agent_that_reports_to_them(
    friend: flow.Human, make_client: ClientFactory, owner: flow.Human
) -> None:
    created = _bring(friend)
    assert created.status_code == 201, created.text
    response = flow.exchange(make_client(), created.json())
    assert response.status_code == 201, response.text
    agent_id = response.headers["Maity-Member-Id"]
    view = owner.get(f"{PROJECT}/members/{agent_id}").json()
    assert (view["trust"], view["role"]) == ("member", "coder")
    assert view["reports_to"] == friend.id
    assert view["areas"] == [] and view["capabilities"] == []


def test_each_limit_is_named(friend: flow.Human, owner: flow.Human) -> None:
    _refused(_bring(friend, trust="admin"), "trust")
    _refused(_bring(friend, trust="owner"), "trust")
    _refused(_bring(friend, role="proxy"), "role")
    _refused(_bring(friend, role="ops"), "role")
    _refused(_bring(friend, reports_to=owner.id), "reports_to")
    _refused(_bring(friend, areas=["hub/"]), "areas")
    _refused(_bring(friend, capabilities=["merge"]), "capabilities")
    owners_agent = flow.join(owner, "maity")["agent_id"]
    _refused(friend.post(JOINS, {"agent": {"id": owners_agent}}), "agent")
    # Within the limits, said explicitly: a reviewer reporting to the caller.
    assert _bring(friend, role="reviewer", reports_to=friend.id).status_code == 201
    assert _bring(friend, 2, trust="guest", role="tester").status_code == 201
    assert _bring(friend, 3, role="writer").status_code == 201
    # `manager` is in the contract (#541) but not in this hub yet: unknown, not a limit.
    unknown = _bring(friend, 4, role="manager")
    assert unknown.status_code == 400
    assert unknown.json()["error"]["details"]["fields"] == {"role": "unknown"}


def test_an_agent_raised_beyond_the_limits_gets_instances_only_from_an_admin(
    friend: flow.Human, make_client: ClientFactory, owner: flow.Human
) -> None:
    created = _bring(friend).json()
    agent_id = flow.exchange(make_client(), created).headers["Maity-Member-Id"]
    raised = owner.patch(f"{PROJECT}/members/{agent_id}", {"trust": "admin"})
    assert raised.status_code == 200, raised.text
    _refused(friend.post(JOINS, {"agent": {"id": agent_id}, "new_instance": True}), "agent")


def test_off_refuses_new_joins_and_keeps_the_open_ones(
    friend: flow.Human, make_client: ClientFactory, owner: flow.Human
) -> None:
    pending = _bring(friend, 1).json()
    _policy(owner, member_agents="off")
    refused = _bring(friend, 2)
    assert refused.status_code == 403
    assert refused.json()["error"]["details"] == {"scope": "members:admin"}
    # Still listed, still revocable, and the open join still exchanges (§3.3).
    assert [j["id"] for j in friend.get(JOINS).json()["items"]] == [pending["id"]]
    assert flow.exchange(make_client(), pending).status_code == 201


def test_member_agents_is_a_humans_project_admin_field(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    for change in ({"member_agents": "off"}, {"member_agents_max": 5}):
        response = admin.patch(PROJECT, {"policy": change, "reason": "test"})
        assert response.status_code == 403
        assert response.json()["error"]["details"]["reason"] == "humans_only"
    bad = owner.patch(PROJECT, {"policy": {"member_agents_max": 21}, "reason": "test"})
    assert bad.json()["error"]["details"]["fields"] == {"policy.member_agents_max": "out_of_range"}
    bad = owner.patch(PROJECT, {"policy": {"member_agents": "maybe"}, "reason": "test"})
    assert bad.json()["error"]["details"]["fields"] == {"policy.member_agents": "unknown"}
    # A preset change keeps both (§6.1).
    _policy(owner, member_agents="off", member_agents_max=7)
    _policy(owner, preset="solo")
    policy = owner.get(PROJECT).json()["policy"]
    assert (policy["member_agents"], policy["member_agents_max"]) == ("off", 7)


def test_guests_and_agents_never_bring_agents(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    response = agent.post(JOINS, _new(9))
    assert response.status_code == 403
    visitor = flow.human(make_client, migrated, "visitor")
    factory.membership(migrated, _project_id(migrated), "coder", trust="guest", human_id=visitor.id)
    refused = visitor.post(JOINS, _new(8))
    assert refused.status_code == 403
    assert refused.json()["error"]["details"] == {"scope": "members:admin"}


def test_a_creator_lowered_to_guest_voids_the_join(
    friend: flow.Human, make_client: ClientFactory, owner: flow.Human
) -> None:
    pending = _bring(friend).json()
    lowered = owner.patch(f"{PROJECT}/members/{friend.id}", {"trust": "guest"})
    assert lowered.status_code == 200, lowered.text
    assert flow.exchange(make_client(), pending).status_code == 404


def test_the_limit_counts_distinct_profiles_and_never_an_instance(
    friend: flow.Human, make_client: ClientFactory, owner: flow.Human
) -> None:
    _policy(owner, member_agents_max=1)
    first = _bring(friend, 1).json()
    over = _bring(friend, 2)
    assert over.status_code == 403
    assert over.json()["error"]["details"] == {"reason": "member_agents_max", "max": 1}
    # The same profile's second open join counts once.
    again = friend.post(JOINS, {"agent": {"id": first["agent_id"]}})
    assert again.status_code == 201, again.text
    response = flow.exchange(make_client(), first)
    assert response.status_code == 201
    instance = response.headers["Maity-Instance"]
    _two_instances(friend, first["agent_id"])
    # At the limit, a new instance or a replacement still goes through.
    extra = friend.post(JOINS, {"agent": {"id": first["agent_id"]}, "new_instance": True})
    assert extra.status_code == 201, extra.text
    swap = friend.post(JOINS, {"agent": {"id": first["agent_id"]}, "replaces": instance})
    assert swap.status_code == 201, swap.text
    # A revoked or expired join frees the slot again.
    assert _bring(friend, 3).status_code == 403
    _policy(owner, member_agents_max=0)
    assert _bring(friend, 3).json()["error"]["details"]["max"] == 0


def test_a_member_lists_and_revokes_only_their_own_joins(
    friend: flow.Human, owner: flow.Human
) -> None:
    mine = _bring(friend).json()
    theirs = flow.join(owner, "maity")
    assert [j["id"] for j in friend.get(JOINS).json()["items"]] == [mine["id"]]
    assert {j["id"] for j in owner.get(JOINS).json()["items"]} == {mine["id"], theirs["id"]}
    assert friend.delete(f"{JOINS}/{theirs['id']}").status_code == 404
    revoked = friend.delete(f"{JOINS}/{mine['id']}")
    assert revoked.status_code == 200 and revoked.json()["revoked_at"] is not None
    # The revoked join frees the slot.
    _policy(owner, member_agents_max=1)
    assert _bring(friend, 2).status_code == 201


# --- §3.3 the exchange checks again -------------------------------------------------------


def _remove(owner: flow.Human, member: str) -> None:
    response = owner.delete(f"{PROJECT}/members/{member}")
    assert response.status_code in (200, 204), response.text


def test_a_removed_creator_voids_the_join(
    friend: flow.Human, make_client: ClientFactory, owner: flow.Human
) -> None:
    pending = _bring(friend).json()
    _remove(owner, friend.id)
    assert flow.exchange(make_client(), pending).status_code == 404


def test_a_creator_raised_to_admin_keeps_the_join(
    friend: flow.Human, make_client: ClientFactory, owner: flow.Human
) -> None:
    pending = _bring(friend).json()
    raised = owner.patch(f"{PROJECT}/members/{friend.id}", {"trust": "admin"})
    assert raised.status_code == 200, raised.text
    _policy(owner, member_agents_max=0)  # an admin's join is not counted
    assert flow.exchange(make_client(), pending).status_code == 201


def test_an_instance_join_is_void_once_an_admin_raised_the_agent(
    friend: flow.Human, make_client: ClientFactory, owner: flow.Human
) -> None:
    created = _bring(friend).json()
    agent_id = flow.exchange(make_client(), created).headers["Maity-Member-Id"]
    _two_instances(friend, agent_id)
    extra = friend.post(JOINS, {"agent": {"id": agent_id}, "new_instance": True}).json()
    owner.patch(f"{PROJECT}/members/{agent_id}", {"trust": "admin"})
    assert flow.exchange(make_client(), extra).status_code == 404


def test_two_exchanges_in_a_row_at_the_limit(
    friend: flow.Human, make_client: ClientFactory, owner: flow.Human
) -> None:
    """Two open first joins, then the limit lowered to one: the count at the exchange
    is the count at creation, so neither fits until the member revokes one; then the
    other exchanges and a third does not."""
    first, second = _bring(friend, 1).json(), _bring(friend, 2).json()
    _policy(owner, member_agents_max=1)
    assert flow.exchange(make_client(), first).status_code == 404
    friend.delete(f"{JOINS}/{second['id']}")
    assert flow.exchange(make_client(), first).status_code == 201
    _policy(owner, member_agents_max=2)
    third = _bring(friend, 3).json()
    _policy(owner, member_agents_max=1)
    assert flow.exchange(make_client(), third).status_code == 404


# --- two joins for the last slot, on two real connections ---------------------------------


def _profile(engine: Engine, owner_id: str) -> str:
    agent_id = new_id("agent")
    with engine.begin() as conn:
        conn.execute(
            insert(t.agent_profile).values(
                id=agent_id,
                owner_id=owner_id,
                handle=agent_id,
                display_name="An agent",
                created_at=clock.now(),
            )
        )
    return agent_id


def _open_join(conn: Connection, project_id: str, creator: str, agent_id: str) -> None:
    now = clock.now()
    conn.execute(
        insert(t.join_link).values(
            id=new_id("join"),
            project_id=project_id,
            token_hash=digest(new_token()),
            code_hash=digest(new_code()),
            agent_id=agent_id,
            role="member",
            areas=[],
            capabilities=[],
            created_by=creator,
            created_at=now,
            expires_at=now + timedelta(minutes=15),
            failed_attempts=0,
            member_rule=True,
        )
    )


def test_two_joins_for_the_last_slot_create_exactly_one(migrated: Engine) -> None:
    project_id = factory.project(migrated, member_agents_max=1)
    creator = factory.human(migrated)
    factory.membership(migrated, project_id, "member", human_id=creator)
    one, two = _profile(migrated, creator), _profile(migrated, creator)
    with race(migrated) as r:
        project = lock_project(r.first, project_id)
        _require_slot(r.first, project, creator, one)
        _open_join(r.first, project_id, creator, one)

        def second() -> None:
            project = lock_project(r.second, project_id)
            _require_slot(r.second, project, creator, two)

        step = r.run(r.second, second)
        assert waiting(step)  # blocked on the project lock the first holds
        r.first.commit()
        with pytest.raises(ApiError) as refused:
            finished(step)
    assert refused.value.details == {"reason": "member_agents_max", "max": 1}


@pytest.mark.parametrize("lowered", [0, 1])
def test_two_open_joins_for_one_profile_do_not_lift_a_lowered_maximum(
    friend: flow.Human, make_client: ClientFactory, owner: flow.Human, lowered: int
) -> None:
    """Two open first joins name the same new profile; the maximum is lowered below what
    the member would hold: the exchange voids the join, the other open join no exemption."""
    if lowered:
        _bring(friend, 9)  # a second profile already held, so one slot is too few
    first = _bring(friend, 1).json()
    friend.post(JOINS, {"agent": {"id": first["agent_id"]}})  # the same profile again
    _policy(owner, member_agents_max=lowered)
    assert flow.exchange(make_client(), first).status_code == 404
