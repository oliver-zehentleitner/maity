"""docs/api.md §8.4, §8.5, §9: messages, redaction, conversations."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_tasks import task


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


def say(who: Any, **body: Any) -> Any:
    return who.post(
        "/projects/maity/events", {"kind": "message", "type": "notice", "body": "hi", **body}
    )


def chat(who: Any, agent_id: str, body: str) -> Any:
    return who.post(f"/projects/maity/conversations/{agent_id}/messages", {"body": body})


# --- §8.4 messages ----------------------------------------------------------------------


def test_a_message_is_an_event_to_its_addressees_and_its_sender(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    card = task(owner)
    response = say(
        agent, type="blocker", to="role:admin", body="the contract is unclear", task_id=card["id"]
    )
    assert response.status_code == 201
    event = response.json()
    assert event["kind"] == "message"
    assert event["audience"] == ["role:admin", f"member:{agent.id}"]
    assert event["payload"] == {
        "type": "blocker",
        "to": "role:admin",
        "body": "the contract is unclear",
        "conversation_id": None,
        "task_id": card["id"],
    }
    assert event["actor"]["member_id"] == agent.id
    assert event["subject"] == {"type": "task", "id": card["id"]}


@pytest.mark.parametrize(
    ("body", "fields"),
    [
        ({"type": "status"}, {"type": "unknown"}),
        ({"to": "agt-nobody"}, {"to": "not_a_member"}),
        ({"to": "role:boss"}, {"to": "unknown_role"}),
        ({}, {"to": "required"}),
        ({"to": "all", "conversation_id": "agt-x"}, {"conversation_id": "chat_only"}),
        ({"type": "chat"}, {"conversation_id": "required_for_chat"}),
        ({"to": "all", "task_id": "tsk-nope"}, {"task_id": "unknown_task"}),
    ],
)
def test_messages_are_checked(
    owner: flow.Human, body: dict[str, Any], fields: dict[str, str]
) -> None:
    assert say(owner, **body).json()["error"]["details"]["fields"] == fields


def test_only_messages_may_be_posted(owner: flow.Human) -> None:
    response = owner.post(
        "/projects/maity/events",
        {"kind": "task_created", "type": "notice", "to": "all", "body": "x"},
    )
    assert response.headers["Maity-Error"] == "invalid"


def test_everyone_with_events_post_may_message_all(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    assert say(agent, to="all").json()["audience"] == ["all", f"member:{agent.id}"]


# --- §8.5 redaction --------------------------------------------------------------------------


def test_redaction_replaces_the_payload_and_is_itself_recorded(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    leaked = say(agent, to="all", body="a secret that got in").json()
    response = owner.post(f"/projects/maity/events/{leaked['seq']}/redact", {"reason": "a secret"})
    assert response.status_code == 200
    body = response.json()
    assert body["redacted"] is True and body["seq"] == leaked["seq"] and body["kind"] == "message"
    assert body["payload"] | {"at": None} == {
        "redacted": True,
        "reason": "a secret",
        "by": owner.id,
        "at": None,
    }
    assert body["audience"] == leaked["audience"]
    with migrated.connect() as conn:
        tomb = conn.execute(select(t.event).where(t.event.c.kind == "event_redacted")).one()
    assert tomb.audience == ["role:owner", "role:admin"]
    assert tomb.payload == {"seq": leaked["seq"], "reason": "a secret"}
    again = owner.post(f"/projects/maity/events/{leaked['seq']}/redact", {"reason": "twice"})
    assert again.json()["payload"]["reason"] == "a secret"  # the first tombstone stands


def test_redaction_is_for_human_admins_and_this_project(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    admin_agent = flow.agent(make_client, owner, role="admin")
    event = say(owner, to="all").json()
    refused = admin_agent.post(f"/projects/maity/events/{event['seq']}/redact", {"reason": "x"})
    assert refused.status_code == 403 and refused.json()["error"]["details"] == {
        "scope": "events:admin"
    }
    flow.project(owner, "other")
    elsewhere = owner.post(f"/projects/other/events/{event['seq']}/redact", {"reason": "x"})
    assert elsewhere.headers["Maity-Error"] == "not_found"


# --- §9 conversations ------------------------------------------------------------------------


def test_the_human_and_its_agent_chat_and_nobody_else_sees_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    admin = flow.agent(make_client, owner, role="admin")
    sent = chat(owner, agent.id, "How far is the contract?")
    assert sent.status_code == 201
    message = sent.json()
    assert set(message) == {
        "id",
        "seq",
        "conversation_id",
        "from",
        "to",
        "body",
        "sent_at",
        "delivered_at",
    }
    assert (message["from"], message["to"], message["conversation_id"]) == (
        owner.id,
        agent.id,
        agent.id,
    )
    assert message["id"] == f"evt-{message['seq']}" and message["delivered_at"] is None
    with migrated.connect() as conn:
        event = conn.execute(select(t.event).where(t.event.c.seq == message["seq"])).one()
    assert event.audience == [f"member:{agent.id}", f"member:{owner.id}"]
    seen_by_admin = admin.get("/projects/maity/events?after=0").json()["items"]
    assert message["seq"] not in [e["seq"] for e in seen_by_admin]  # admins included: nobody else
    assert chat(admin, agent.id, "me too").status_code == 403


def test_delivery_is_the_first_time_the_recipient_got_it(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    message = chat(owner, agent.id, "ping").json()
    owner.get(
        f"/projects/maity/conversations/{agent.id}/messages"
    )  # the sender reading: no delivery
    mine = owner.get(f"/projects/maity/conversations/{agent.id}/messages").json()["items"]
    assert mine[0]["delivered_at"] is None
    agent.resume(cursor=0)  # through the resume packet
    delivered = owner.get(f"/projects/maity/conversations/{agent.id}/messages").json()["items"][0]
    assert delivered["delivered_at"] is not None
    agent.get("/projects/maity/events?after=0")
    again = owner.get(f"/projects/maity/conversations/{agent.id}/messages").json()["items"][0]
    assert again["delivered_at"] == delivered["delivered_at"]  # the first time stands
    assert message["seq"] == delivered["seq"]


def test_the_agent_answers_in_the_conversation(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    chat(owner, agent.id, "status?")
    reply = chat(agent, agent.id, "contract drafted").json()
    assert (reply["from"], reply["to"]) == (agent.id, owner.id)
    via_events = say(agent, type="chat", conversation_id=agent.id, body="and tested").json()
    assert via_events["payload"]["to"] == owner.id
    items = owner.get(f"/projects/maity/conversations/{agent.id}/messages").json()["items"]
    assert [m["body"] for m in items] == ["status?", "contract drafted", "and tested"]
    later = owner.get(
        f"/projects/maity/conversations/{agent.id}/messages?after={items[0]['seq']}"
    ).json()
    assert [m["body"] for m in later["items"]] == ["contract drafted", "and tested"]
    assert later["cursor"] == items[-1]["seq"]


def test_the_list_counts_unread_for_the_human(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner, agent={"handle": "agent-b", "display_name": "B"})
    other = flow.agent(make_client, owner, agent={"handle": "agent-c", "display_name": "C"})
    chat(agent, agent.id, "one")
    chat(agent, agent.id, "two")
    listed = owner.get("/projects/maity/conversations").json()["items"]
    assert [(c["agent_id"], c["unread"]) for c in listed] == [(agent.id, 2), (other.id, 0)]
    assert listed[0]["last_message_at"] is not None and listed[1]["last_message_at"] is None
    owner.get(f"/projects/maity/conversations/{agent.id}/messages")
    assert owner.get("/projects/maity/conversations").json()["items"][0]["unread"] == 0
    assert [c["agent_id"] for c in agent.get("/projects/maity/conversations").json()["items"]] == [
        agent.id
    ]


def test_someone_elses_agent_has_no_conversation_with_me(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    stranger = flow.human(make_client, migrated, "stranger")
    flow.project(stranger, "theirs")
    agent = flow.agent(make_client, owner)
    assert chat(stranger, agent.id, "x").status_code in (403, 404)
    assert (
        owner.get("/projects/maity/conversations/agt-nobody/messages").headers["Maity-Error"]
        == "not_found"
    )


def test_a_redacted_chat_message_has_no_body(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    message = chat(agent, agent.id, "my token is …").json()
    owner.post(f"/projects/maity/events/{message['seq']}/redact", {"reason": "a token"})
    items = owner.get(f"/projects/maity/conversations/{agent.id}/messages").json()["items"]
    assert items[0]["body"] is None
