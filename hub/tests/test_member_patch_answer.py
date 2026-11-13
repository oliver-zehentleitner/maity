"""docs/api.md §6.2: the `200` of `PATCH …/members/{id}` is the member view exactly as
`GET …/members/{id}` gives it to the same caller (tsk-vbd33mrjj81d) — with `owner`,
`credentials`, `manages`, `owner_preferences` and `shared_environment` where that caller
would get them, and without them, or the briefing, where it would not."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_bridge_calls import API, Calls, _pair

PROJECT = "/projects/maintainer/maity"
DETAILS = {"owner", "credentials", "shared_environment"}


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def _project_id(engine: Engine) -> str:
    with engine.connect() as conn:
        found: str = conn.execute(select(t.project.c.id)).scalar_one()
    return found


def _set(engine: Engine, membership_id: int, **values: Any) -> None:
    with engine.begin() as conn:
        conn.execute(update(t.membership).where(t.membership.c.id == membership_id).values(values))


def _member_id(engine: Engine, principal: str) -> int:
    with engine.connect() as conn:
        found: int = conn.execute(
            select(t.membership.c.id).where(
                (t.membership.c.agent_id == principal) | (t.membership.c.human_id == principal)
            )
        ).scalar_one()
    return found


def _member_human(make_client: ClientFactory, engine: Engine, handle: str, trust: str) -> Any:
    human = flow.human(make_client, engine, handle)
    factory.membership(engine, _project_id(engine), "coder", trust=trust, human_id=human.id)
    return human


def as_read(who: Any, member_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """The PATCH answer and the GET that follows by the same caller; they must be equal."""
    path = f"{PROJECT}/members/{member_id}"
    patched = who.patch(path, body)
    assert patched.status_code == 200, patched.text
    read = who.get(path)
    assert read.status_code == 200, read.text
    answer: dict[str, Any] = patched.json()
    assert answer == read.json()
    return answer


Case = Callable[[flow.Human, ClientFactory, Engine], tuple[Any, str, dict[str, Any]]]


def _admin_on_own_agent(owner: flow.Human, make: ClientFactory, engine: Engine) -> Any:
    agent = flow.agent(make, owner)
    return owner, agent.id, {"areas": ["web/"], "briefing": "The web."}


def _admin_on_a_human(owner: flow.Human, make: ClientFactory, engine: Engine) -> Any:
    colleague = _member_human(make, engine, "colleague", "member")
    return owner, colleague.id, {"areas": ["docs/"]}


def _co_admin_on_own_agent(owner: flow.Human, make: ClientFactory, engine: Engine) -> Any:
    admin = _member_human(make, engine, "deputy", "admin")
    agent = factory.agent(engine, _project_id(engine), admin.id, "coder")
    return admin, agent.agent_id, {"areas": ["web/"]}


def _owner_member_preferences(owner: flow.Human, make: ClientFactory, engine: Engine) -> Any:
    human = _member_human(make, engine, "member", "member")
    agent = factory.agent(engine, _project_id(engine), human.id, "coder")
    return human, agent.agent_id, {"owner_preferences": True}


def _owner_member_role(owner: flow.Human, make: ClientFactory, engine: Engine) -> Any:
    human = _member_human(make, engine, "member", "member")
    agent = factory.agent(engine, _project_id(engine), human.id, "coder")
    return human, agent.agent_id, {"role": "reviewer"}


def _owner_member_reports_to(owner: flow.Human, make: ClientFactory, engine: Engine) -> Any:
    human = _member_human(make, engine, "member", "member")
    agent = factory.agent(engine, _project_id(engine), human.id, "coder")
    return human, agent.agent_id, {"reports_to": human.id}


def _owner_member_subagents(owner: flow.Human, make: ClientFactory, engine: Engine) -> Any:
    human = _member_human(make, engine, "member", "member")
    agent = factory.agent(engine, _project_id(engine), human.id, "coder")
    return human, agent.agent_id, {"subagents": True, "subagents_language": "en"}


def _owner_member_expert(owner: flow.Human, make: ClientFactory, engine: Engine) -> Any:
    human = _member_human(make, engine, "member", "member")
    agent = factory.agent(engine, _project_id(engine), human.id, "expert")
    return human, agent.agent_id, {"expert_for": "The hub's events.", "expert_sources": ["hub/"]}


def _owner_member_team(owner: flow.Human, make: ClientFactory, engine: Engine) -> Any:
    human = _member_human(make, engine, "member", "member")
    agent = factory.agent(engine, _project_id(engine), human.id, "coder")
    return human, agent.agent_id, {"team": {"distribution": "round_robin"}}


def _owner_member_dormant(owner: flow.Human, make: ClientFactory, engine: Engine) -> Any:
    human = _member_human(make, engine, "member", "member")
    agent = factory.agent(engine, _project_id(engine), human.id, "coder")
    return human, agent.agent_id, {"dormant": True, "instance": agent.instance}


def _owner_member_lifts_a_managers_pause(
    owner: flow.Human, make: ClientFactory, engine: Engine
) -> Any:
    human = _member_human(make, engine, "member", "member")
    manager = flow.agent(make, owner, role="manager", reports_to=owner.id)
    agent = factory.agent(engine, _project_id(engine), human.id, "coder")
    lead = _member_id(engine, manager.id)
    _set(engine, agent.membership_id, reports_to=lead, line_consent=True)
    paused = manager.patch(f"{PROJECT}/members/{agent.agent_id}", {"paused": {"reason": "x"}})
    assert paused.status_code == 200, paused.text
    return human, agent.agent_id, {"paused": None}


def _human_on_own_policy(owner: flow.Human, make: ClientFactory, engine: Engine) -> Any:
    human = _member_human(make, engine, "member", "member")
    return human, human.id, {"availability_policy": {"grace_minutes": 0}}


def _manager_on_its_reach(owner: flow.Human, make: ClientFactory, engine: Engine) -> Any:
    manager = flow.agent(make, owner, role="manager", reports_to=owner.id)
    below = flow.agent(make, owner, reports_to=manager.id, briefing="Below the manager.")
    return manager, below.id, {"areas": ["web/"]}


def _manager_on_another_owners_agent(owner: flow.Human, make: ClientFactory, engine: Engine) -> Any:
    manager = flow.agent(make, owner, role="manager", reports_to=owner.id)
    stranger = factory.human(engine, "stranger")
    theirs = factory.agent(engine, _project_id(engine), stranger, "coder")
    lead = _member_id(engine, manager.id)
    _set(engine, theirs.membership_id, reports_to=lead, line_consent=True)
    return manager, theirs.agent_id, {"areas": ["docs/"]}


def _admin_agent_on_a_member_agent(owner: flow.Human, make: ClientFactory, engine: Engine) -> Any:
    admin = flow.agent(make, owner, role="admin")
    member = flow.agent(make, owner, briefing="A member agent.")
    return admin, member.id, {"areas": ["web/"]}


CASES: dict[str, Case] = {
    "admin_on_own_agent": _admin_on_own_agent,
    "admin_on_a_human": _admin_on_a_human,
    "co_admin_on_own_agent": _co_admin_on_own_agent,
    "owner_member_preferences": _owner_member_preferences,
    "owner_member_role": _owner_member_role,
    "owner_member_reports_to": _owner_member_reports_to,
    "owner_member_subagents": _owner_member_subagents,
    "owner_member_expert": _owner_member_expert,
    "owner_member_team": _owner_member_team,
    "owner_member_dormant": _owner_member_dormant,
    "owner_member_lifts_a_managers_pause": _owner_member_lifts_a_managers_pause,
    "human_on_own_policy": _human_on_own_policy,
    "manager_on_its_reach": _manager_on_its_reach,
    "manager_on_another_owners_agent": _manager_on_another_owners_agent,
    "admin_agent_on_a_member_agent": _admin_agent_on_a_member_agent,
}
# What GET gives each caller (§6.2): the details to members:admin and the agent's owner,
# the briefing to members:admin and the member itself, `manages` to everyone.
DETAILED = {
    "admin_on_own_agent",
    "admin_on_a_human",
    "co_admin_on_own_agent",
    "owner_member_preferences",
    "owner_member_role",
    "owner_member_reports_to",
    "owner_member_subagents",
    "owner_member_expert",
    "owner_member_team",
    "owner_member_dormant",
    "owner_member_lifts_a_managers_pause",
}
BRIEFED = {"admin_on_own_agent", "admin_on_a_human", "co_admin_on_own_agent", "human_on_own_policy"}


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_patch_answer_is_the_view_get_gives_the_same_caller(
    case: str, owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    who, member_id, body = CASES[case](owner, make_client, migrated)
    answer = as_read(who, member_id, body)
    assert "manages" in answer
    assert (answer.keys() >= DETAILS) == (case in DETAILED), case
    agent = answer["kind"] == "agent"
    assert ("owner_preferences" in answer) == (agent and case in DETAILED), case
    assert ("briefing" in answer) == (case in BRIEFED), case


def test_a_bridge_changes_no_member_so_there_is_no_answer_to_compare(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """A bridge calls as the agent it serves, under no governance scope (§2.3): even for an
    admin agent it changes no member, so it has no answer to compare."""
    served, bridge, _ = _pair(migrated, owner, trust="admin")
    member = flow.agent(make_client, owner)
    calls = Calls(make_client(), bridge)
    path = f"{API}{PROJECT}/members/{member.id}"
    refused = calls.client.patch(
        path, json={"areas": ["web/"]}, headers=calls.headers(served.agent_id)
    )
    assert refused.status_code == 403, refused.text


def test_a_replay_answers_the_view_get_gives_the_caller(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The same `Idempotency-Key` replays the view as `GET` gives it now (§1.5)."""
    admin = flow.agent(make_client, owner, role="admin")
    member = flow.agent(make_client, owner)
    path = f"/api/v1{PROJECT}/members/{member.id}"
    headers = admin.auth | {"Idempotency-Key": "replay-member-patch-0001"}
    first = admin.client.patch(path, json={"areas": ["web/"]}, headers=headers)
    assert first.status_code == 200, first.text
    again = admin.client.patch(path, json={"areas": ["web/"]}, headers=headers)
    assert again.headers.get("Idempotent-Replayed") == "true"
    assert again.json() == admin.get(f"{PROJECT}/members/{member.id}").json() == first.json()
    assert "briefing" not in again.json() and "owner" not in again.json()
