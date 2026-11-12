"""docs/api.md §9.6 "Waiting": who of a group chat's agents is admitted, who waits for its
owner's yes and what a waiting agent reads, posts and hears; the owner's add as the yes, deny
entries, and an allow entry that ends."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import chat_gate, clock, events
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory

BASE = "/projects/maintainer/maity/conversations"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def project_id(engine: Engine) -> str:
    with engine.connect() as conn:
        found: str = conn.execute(select(t.project.c.id)).scalar_one()
    return found


def other_human(make_client: ClientFactory, engine: Engine, handle: str) -> flow.Human:
    human = flow.human(make_client, engine, handle)
    factory.membership(engine, project_id(engine), "admin", human_id=human.id)
    return human


def create(who: Any, *participants: str) -> Any:
    return who.post(BASE, {"title": "Release", "participants": list(participants)})


def add(who: Any, chat_id: str, member_id: str) -> Any:
    return who.post(f"{BASE}/{chat_id}/participants", {"member_id": member_id})


def say(who: Any, chat_id: str, body: str) -> Any:
    return who.post(f"{BASE}/{chat_id}/messages", {"body": body})


def view(who: Any, chat_id: str) -> Any:
    return who.get(f"{BASE}/{chat_id}")


def item(chat: dict[str, Any], member_id: str) -> dict[str, Any]:
    [found] = [p for p in chat["participants"] if p["member_id"] == member_id]
    shown: dict[str, Any] = found
    return shown


def reason(response: Any) -> Any:
    return response.json()["error"]["details"].get("reason")


def updates(engine: Engine, chat_id: str) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            select(t.event.c.payload)
            .where(t.event.c.conversation_id == chat_id, t.event.c.kind == "conversation_updated")
            .order_by(t.event.c.seq)
        ).scalars()
        return [r["changed"] for r in rows]


def handle(engine: Engine, agent_id: str) -> str:
    with engine.connect() as conn:
        found: str = conn.execute(
            select(t.agent_profile.c.handle).where(t.agent_profile.c.id == agent_id)
        ).scalar_one()
    return found


def allow(who: flow.Human, **body: Any) -> Any:
    got = who.post("/me/chat-access/allow", body)
    assert got.status_code == 201, got.text
    return got.json()


def test_an_agent_of_another_owner_waits_and_reads_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other")
    theirs = flow.agent(make_client, other)
    created = create(owner, theirs.id)
    assert created.status_code == 201, created.text
    chat = created.json()
    assert item(chat, theirs.id)["waiting_for"] == [owner.id]
    assert "waiting_for" not in item(chat, owner.id)
    text = f"@{handle(migrated, theirs.id)} are you there?"
    said = say(owner, chat["id"], text)
    assert said.status_code == 201, said.text
    assert said.json()["mentions"] == []  # a waiting agent is not mentioned
    assert view(theirs, chat["id"]).status_code == 404
    posted = say(theirs, chat["id"], "hello")
    assert posted.status_code == 403 and reason(posted) == "waiting"
    listed = theirs.get(BASE).json()["items"]
    assert chat["id"] not in [i["id"] for i in listed]
    # Nothing of the chat reaches it, not even its creation.
    with migrated.connect() as conn:
        rows = conn.execute(select(t.event).where(t.event.c.conversation_id == chat["id"])).all()
        member = conn.execute(
            select(t.membership).where(t.membership.c.agent_id == theirs.id)
        ).one()
    assert rows and not any(events.readable_by(r, member, theirs.id) for r in rows)
    # Its owner reads along.
    along = view(other, chat["id"])
    assert along.status_code == 200 and along.json()["access"] == "observer"
    read = other.get(f"{BASE}/{chat['id']}/messages").json()["items"]
    assert [m["body"] for m in read] == [text]


def test_the_owners_yes_admits_and_the_window_starts_there(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other")
    theirs = flow.agent(make_client, other)
    chat = create(owner, theirs.id).json()
    before = say(owner, chat["id"], "said while it waited").json()["seq"]
    allow(other, agents=[theirs.id], owner_id=owner.id, their_human=True)
    shown = view(theirs, chat["id"])
    assert shown.status_code == 200, shown.text
    assert item(shown.json(), theirs.id)["waiting_for"] == []
    assert updates(migrated, chat["id"])[-1] == {
        "participants_changed": [{"member_id": theirs.id, "by": other.id, "waiting_for": []}]
    }
    assert theirs.get(f"{BASE}/{chat['id']}/messages").json()["items"] == []
    now = say(theirs, chat["id"], "here now")
    assert now.status_code == 201, now.text
    fresh = theirs.get(f"{BASE}/{chat['id']}/messages").json()
    assert [m["seq"] for m in fresh["items"]] == [now.json()["seq"]]
    history = theirs.get(f"{BASE}/{chat['id']}/messages?before={now.json()['seq']}").json()
    assert [m["seq"] for m in history["items"]] == [before]  # history, on demand
    # An allow for the agents only does not cover the human.
    other.delete(f"/me/chat-access/allow/{other.get('/me/chat-access').json()['allow'][0]['id']}")
    assert item(view(owner, chat["id"]).json(), theirs.id)["waiting_for"] == [owner.id]
    allow(other, agents=[theirs.id], owner_id=owner.id)
    assert item(view(owner, chat["id"]).json(), theirs.id)["waiting_for"] == [owner.id]


def test_a_project_entry_admits_in_that_project(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other")
    theirs = flow.agent(make_client, other)
    allow(other, agents="all", project={"owner": "maintainer", "slug": "maity"})
    chat = create(owner, theirs.id).json()
    assert item(chat, theirs.id)["waiting_for"] == []


def test_the_owners_add_is_the_yes(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other")
    theirs = flow.agent(make_client, other)
    mine = flow.agent(make_client, owner)
    chat = create(owner, other.id, mine.id).json()  # the creator adds its own agent
    assert item(chat, mine.id)["waiting_for"] == []
    added = add(other, chat["id"], theirs.id)
    assert added.status_code == 200, added.text
    shown = view(owner, chat["id"]).json()
    assert item(shown, theirs.id)["waiting_for"] == []
    [entry] = other.get("/me/chat-access").json()["allow"]
    assert entry["agents"] == [theirs.id] and entry["owner_id"] == owner.id
    assert entry["their_agents"] == [mine.id] and entry["their_human"] is True
    assert entry["duration"] is None and entry["by"] == other.id


def test_someone_not_covered_joins_and_the_agent_waits(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other")
    late = other_human(make_client, migrated, "late")
    mine = flow.agent(make_client, owner)
    chat = create(owner, other.id, mine.id).json()
    assert add(owner, chat["id"], late.id).status_code == 200
    assert item(view(owner, chat["id"]).json(), mine.id)["waiting_for"] == [late.id]
    assert updates(migrated, chat["id"])[-1]["participants_changed"] == [
        {"member_id": mine.id, "by": owner.id, "waiting_for": [late.id]}
    ]
    # The one it waited for leaves: it is admitted again.
    gone = late.delete(f"{BASE}/{chat['id']}/participants/{late.id}")
    assert gone.status_code == 200, gone.text
    assert item(view(owner, chat["id"]).json(), mine.id)["waiting_for"] == []


def test_a_deny_refuses_the_add_and_a_denied_joiner_makes_it_leave(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other")
    late = other_human(make_client, migrated, "late")
    theirs = flow.agent(make_client, other)
    denied = other.post("/me/chat-access/deny", {"agents": [theirs.id], "human_id": late.id})
    assert denied.status_code == 201, denied.text
    room = create(late, other.id).json()
    refused = add(other, room["id"], theirs.id)
    assert refused.status_code == 403 and reason(refused) == "chat_denied"
    assert "late" not in refused.text
    chat = create(other, owner.id, theirs.id).json()
    assert item(chat, theirs.id)["waiting_for"] == []
    assert add(owner, chat["id"], late.id).status_code == 200
    shown = view(owner, chat["id"]).json()
    assert theirs.id not in [p["member_id"] for p in shown["participants"]]
    removed = updates(migrated, chat["id"])[-1]["participants_removed"]
    assert removed == [{"member_id": theirs.id, "by": None, "reason": "denied_participant"}]


def test_an_allow_that_ends_lets_the_agent_wait_again(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other")
    theirs = flow.agent(make_client, other)
    entry = allow(other, agents=[theirs.id], owner_id=owner.id, their_human=True, duration="hour")
    chat = create(owner, theirs.id).json()
    assert item(chat, theirs.id)["waiting_for"] == []
    assert chat_gate.sweep(migrated) == 0  # not yet
    with migrated.begin() as conn:
        conn.execute(
            update(t.chat_access)
            .where(t.chat_access.c.id == entry["id"])
            .values(until=clock.now() - timedelta(minutes=1))
        )
    assert chat_gate.sweep(migrated) == 1
    assert chat_gate.sweep(migrated) == 0  # once
    assert item(view(owner, chat["id"]).json(), theirs.id)["waiting_for"] == [owner.id]
    assert updates(migrated, chat["id"])[-1]["participants_changed"] == [
        {"member_id": theirs.id, "by": None, "waiting_for": [owner.id]}
    ]
    renewed = other.patch(f"/me/chat-access/allow/{entry['id']}", {"duration": "day"})
    assert renewed.status_code == 200, renewed.text
    assert item(view(owner, chat["id"]).json(), theirs.id)["waiting_for"] == []
