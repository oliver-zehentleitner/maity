"""docs/api.md §6.1 `own_approvals`, `own_agents`; §2.3 "Own approvals": the two policy fields
and the record of an agent that joined while its owner was no member (tsk-3ggnhdmgmkf3, PR 1).
The gate that reads them comes in the next pull request."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import tables as t
from maity_hub.routes import joins
from tests import factory, flow
from tests.conftest import ClientFactory

PROJECT = "/projects/maintainer/maity"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def _project(engine: Engine) -> str:
    with engine.connect() as conn:
        found: str = conn.execute(select(t.project.c.id)).scalar_one()
    return found


def _set(who: flow.Human | flow.Agent, **policy: Any) -> Any:
    return who.patch(PROJECT, {"policy": policy, "reason": "own approvals"})


def _fields(response: Any) -> dict[str, Any]:
    assert response.status_code == 400, response.text
    fields: dict[str, Any] = response.json()["error"]["details"]["fields"]
    return fields


def _member(make_client: ClientFactory, engine: Engine, handle: str, trust: str = "member") -> Any:
    human = flow.human(make_client, engine, handle)
    factory.membership(engine, _project(engine), "coder", trust=trust, human_id=human.id)
    return human


# --- own_approvals --------------------------------------------------------------------------


def test_own_approvals_is_a_number_of_at_least_one(owner: flow.Human) -> None:
    for wrong in (0, -1, "2", True, 1.5, None):
        assert _fields(_set(owner, own_approvals=wrong)) == {"own_approvals": "out_of_range"}
    done = _set(owner, own_approvals=3)
    assert done.status_code == 200, done.text
    assert done.json()["policy"]["own_approvals"] == 3
    assert _set(owner, own_approvals=1000).status_code == 200  # no upper bound (§6.1)


def test_a_preset_change_keeps_both_fields(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    _member(make_client, migrated, "other")
    assert _set(owner, own_approvals=2, own_agents={"owners_of": ["other"]}).status_code == 200
    changed = _set(owner, preset="solo")
    assert changed.status_code == 200, changed.text
    shown = changed.json()["policy"]
    assert shown["own_approvals"] == 2 and shown["own_agents"] == {"owners_of": ["other"]}


# --- own_agents -----------------------------------------------------------------------------


def test_own_agents_takes_owners_members_or_named_members(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    _member(make_client, migrated, "picked")
    flow.human(make_client, migrated, "stranger")  # no membership
    for value in ("owners", "members"):
        done = _set(owner, own_agents=value)
        assert done.status_code == 200 and done.json()["policy"]["own_agents"] == value
    assert _fields(_set(owner, own_agents="everyone")) == {"own_agents": "unknown"}
    assert _fields(_set(owner, own_agents={"owners_of": "picked"})) == {"own_agents": "unknown"}
    assert _fields(_set(owner, own_agents={"owners_of": [], "x": 1})) == {"own_agents": "unknown"}
    assert _fields(_set(owner, own_agents={"owners_of": ["nobody-here"]})) == {
        "own_agents": "unknown_handle"
    }
    assert _fields(_set(owner, own_agents={"owners_of": ["stranger"]})) == {
        "own_agents": "not_a_member"
    }
    done = _set(owner, own_agents={"owners_of": ["picked", "picked"]})
    assert done.status_code == 200, done.text
    assert done.json()["policy"]["own_agents"] == {"owners_of": ["picked"]}
    assert owner.get(PROJECT).json()["policy"]["own_agents"] == {"owners_of": ["picked"]}


def test_a_picked_member_who_left_stays_and_a_list_read_back_passes(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    picked = _member(make_client, migrated, "picked")
    _member(make_client, migrated, "second")
    assert _set(owner, own_agents={"owners_of": ["picked"]}).status_code == 200
    assert owner.delete(f"{PROJECT}/members/{picked.id}").status_code == 200
    shown = owner.get(PROJECT).json()["policy"]["own_agents"]
    assert shown == {"owners_of": ["picked"]}  # the hub does not remove the handle (§6.1)
    sent_back = _set(owner, own_agents={"owners_of": [*shown["owners_of"], "second"]})
    assert sent_back.status_code == 200, sent_back.text
    assert sent_back.json()["policy"]["own_agents"] == {"owners_of": ["picked", "second"]}
    # A write of `members` drops the stored list: the one who left is new again, and refused.
    assert _set(owner, own_agents="members").status_code == 200
    assert _fields(_set(owner, own_agents={"owners_of": ["picked"]})) == {
        "own_agents": "not_a_member"
    }


def test_own_agents_is_the_owners_call(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    admin = _member(make_client, migrated, "admin-human", trust="admin")
    refused = _set(admin, own_agents="owners")
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"]["reason"] == "owner_only"
    assert _set(admin, own_approvals=2).status_code == 200  # project:admin sets this one
    lead = flow.agent(make_client, owner, role="admin")
    for field, value in (("own_approvals", 2), ("own_agents", "owners")):
        by_agent = _set(lead, **{field: value})
        assert by_agent.status_code == 403
        assert by_agent.json()["error"]["details"]["reason"] in ("humans_only", "owner_only")


def test_a_policy_change_names_the_picked_people_by_handle(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    _member(make_client, migrated, "picked")
    assert _set(owner, own_agents={"owners_of": ["picked"]}).status_code == 200
    with migrated.connect() as conn:
        changed = conn.execute(
            select(t.event.c.payload)
            .where(t.event.c.kind == "policy_changed")
            .order_by(t.event.c.seq.desc())
        ).first()
        stored = conn.execute(select(t.project.c.own_agents)).scalar_one()
    assert changed is not None
    assert changed.payload["new"]["own_agents"] == {"owners_of": ["picked"]}
    assert changed.payload["old"]["own_agents"] == "members"
    assert stored["owners_of"][0].startswith("hum-")  # kept by id, shown by handle


# --- joined_outside -------------------------------------------------------------------------


def test_an_agent_joining_while_its_owner_is_a_member_is_not_marked(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    with migrated.connect() as conn:
        marked = conn.execute(
            select(t.membership.c.joined_outside).where(t.membership.c.agent_id == agent.id)
        ).scalar_one()
    assert marked is False


def test_the_exchange_marks_an_agent_whose_owner_holds_no_membership(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The exchange's check, read under the project lock (§2.3): an owner who holds no
    membership marks the agent, and a profile nobody can find counts as outside too."""
    stranger = flow.human(make_client, migrated, "stranger")
    member = _member(make_client, migrated, "member-owner")
    project_id = _project(migrated)
    outside = factory.agent(migrated, project_id, stranger.id, "coder").agent_id
    inside = factory.agent(migrated, project_id, member.id, "coder").agent_id
    with migrated.connect() as conn:
        assert joins._owner_outside(conn, project_id, outside) is True
        assert joins._owner_outside(conn, project_id, inside) is False
        assert joins._owner_outside(conn, project_id, "agt-gone") is True
