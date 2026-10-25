"""docs/api.md §6.3: an agent's global name `name` wherever the hub names a member besides
the member view — the resume packet's `me` and `peers`, conversation participants,
group-chat people and the onboarding `check_in_with`. A human has no `name`."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine

from tests import flow
from tests.conftest import ClientFactory

BASE = "/projects/maity/conversations"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def named(make_client: ClientFactory, owner: flow.Human, handle: str) -> flow.Agent:
    return flow.agent(make_client, owner, agent={"handle": handle, "display_name": handle})


def by_id(people: list[dict[str, Any]], member_id: str) -> dict[str, Any]:
    return next(p for p in people if p["member_id"] == member_id)


def test_the_packet_names_me_and_my_agent_peers(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = named(make_client, owner, "agent-b")
    peer = named(make_client, owner, "agent-c")
    packet = agent.resume().json()
    assert packet["me"]["name"] == "maintainer/agent-b"
    assert by_id(packet["peers"], peer.id)["name"] == "maintainer/agent-c"
    assert "name" not in by_id(packet["peers"], owner.id)  # a human's handle is the name


def test_conversation_participants_carry_the_name(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = named(make_client, owner, "agent-b")
    other = named(make_client, owner, "agent-c")
    sent = owner.post(f"{BASE}/{agent.id}/messages", {"body": "hello"})
    assert sent.status_code == 201, sent.text
    group = owner.post(BASE, {"title": "Go/no-go", "participants": [agent.id, other.id]})
    assert group.status_code == 201, group.text
    items = {i["id"]: i for i in owner.get(BASE).json()["items"]}
    direct = next(i for i in items.values() if i["id"] != group.json()["id"])
    assert by_id(direct["participants"], agent.id)["name"] == "maintainer/agent-b"
    assert "name" not in by_id(direct["participants"], owner.id)
    listed = items[group.json()["id"]]["participants"]
    assert by_id(listed, other.id)["name"] == "maintainer/agent-c"
    # The group chat's own view names its people the same way.
    view = owner.get(f"{BASE}/{group.json()['id']}").json()
    assert by_id(view["participants"], agent.id)["name"] == "maintainer/agent-b"
    assert "name" not in by_id(view["participants"], owner.id)


def test_check_in_with_names_an_agent_and_the_instruction_uses_the_long_form(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    target = named(make_client, owner, "agent-lead")
    newcomer = named(make_client, owner, "agent-new")
    owner.patch("/projects/maity", {"settings": {"onboarding": {"check_in_with": target.id}}})
    hint = newcomer.resume().json()["onboarding"]
    assert hint["check_in_with"]["name"] == "maintainer/agent-lead"
    assert "@maintainer/agent-lead " in hint["instruction"]
    # A human target keeps the short form: a human has no long one.
    owner.patch("/projects/maity", {"settings": {"onboarding": {"check_in_with": owner.id}}})
    hint = newcomer.resume().json()["onboarding"]
    assert "name" not in hint["check_in_with"]
    assert "@maintainer " in hint["instruction"]
