"""docs/api.md §2.3, "The bridge": what a bridge reads for the agents it serves — their events
with `for`, their direct conversation — and the presence it lends them (tsk-emy3a9vtqxym)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory

PROJECT = "/projects/maintainer/maity"
API = "/api/v1"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def _project(engine: Engine) -> str:
    with engine.connect() as conn:
        found: str = conn.execute(select(t.project.c.id)).scalar_one()
    return found


def _pair(
    engine: Engine, owner: flow.Human, *, served_session: bool = True
) -> tuple[factory.Agent, factory.Agent]:
    served = factory.agent(engine, _project(engine), owner.id, "coder", with_session=served_session)
    bridge = factory.agent(engine, _project(engine), owner.id, "coder", instance="brg1")
    made = owner.post(
        f"{PROJECT}/members/{served.agent_id}/bridges",
        {"bridge": bridge.agent_id, "purpose": "git for the designer"},
    )
    assert made.status_code == 201, made.text
    return served, bridge


def _get(client: Any, agent: factory.Agent, path: str, served: str | None = None) -> Any:
    headers = {"Authorization": f"Bearer {agent.value}"}
    if served is not None:
        headers["Maity-For"] = served
    return client.get(f"{API}{path}", headers=headers)


def _tell(owner: flow.Human, to: str, body: str = "for you") -> int:
    sent = owner.post(
        f"{PROJECT}/events", {"kind": "message", "type": "notice", "to": to, "body": body}
    )
    assert sent.status_code == 201, sent.text
    seq: int = sent.json()["seq"]
    return seq


def _seqs(response: Any) -> list[int]:
    assert response.status_code == 200, response.text
    return [e["seq"] for e in response.json()["items"]]


def test_for_reads_what_the_served_agent_reads_and_moves_no_cursor(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge = _pair(migrated, owner)
    seq = _tell(owner, served.agent_id)
    chat = owner.post(f"{PROJECT}/conversations/{served.agent_id}/messages", {"body": "hi"})
    assert chat.status_code == 201, chat.text
    client = make_client()
    read_for = _seqs(_get(client, bridge, f"{PROJECT}/events?for={served.agent_id}"))
    assert seq in read_for and chat.json()["seq"] in read_for
    assert seq not in _seqs(_get(client, bridge, f"{PROJECT}/events"))  # not its own
    read = _get(client, bridge, f"{PROJECT}/events?for={served.agent_id}&after={seq}")
    assert read.status_code == 200, read.text
    with migrated.connect() as conn:
        acknowledged = conn.execute(
            select(t.agent_session.c.acknowledged_seq).where(
                t.agent_session.c.id == bridge.session_id
            )
        ).scalar()
        delivered = conn.execute(select(t.message_delivery)).first()
    assert acknowledged == 0 and delivered is None  # nothing reached the served agent


def test_the_long_poll_with_for_answers_the_served_agents_wake(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge = _pair(migrated, owner)
    seq = _tell(owner, served.agent_id)
    waited = _get(make_client(), bridge, f"{PROJECT}/events?for={served.agent_id}&wait=1")
    assert seq in _seqs(waited)


def test_for_is_refused_without_a_connection_or_against_maity_for(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge = _pair(migrated, owner)
    stranger = factory.agent(migrated, _project(migrated), owner.id, "coder")
    client = make_client()
    refused = _get(client, bridge, f"{PROJECT}/events?for={stranger.agent_id}")
    assert refused.json()["error"]["details"]["reason"] == "not_your_bridge"
    mismatch = _get(client, bridge, f"{PROJECT}/events?for={stranger.agent_id}", served.agent_id)
    assert mismatch.json()["error"]["details"]["fields"] == {"for": "not_maity_for"}
    human = owner.get(f"{PROJECT}/events?for={served.agent_id}")
    assert human.json()["error"]["details"]["reason"] == "not_your_bridge"


def test_the_bridge_reads_the_direct_conversation_with_maity_for(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge = _pair(migrated, owner)
    said = owner.post(
        f"{PROJECT}/conversations/{served.agent_id}/messages", {"body": "how far are you?"}
    )
    assert said.status_code == 201, said.text
    client = make_client()
    path = f"{PROJECT}/conversations/{served.agent_id}"
    assert _get(client, bridge, path, served.agent_id).status_code == 200
    messages = _get(client, bridge, f"{path}/messages", served.agent_id)
    assert [m["body"] for m in messages.json()["items"]] == ["how far are you?"]
    assert _get(client, bridge, f"{path}/messages").status_code in (403, 404)  # as itself


def test_a_served_agent_without_a_session_is_present_through_its_bridge(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge = _pair(migrated, owner, served_session=False)
    assert _get(make_client(), bridge, "/me").status_code == 200  # the bridge is seen now
    view = owner.get(f"{PROJECT}/members/{served.agent_id}").json()
    assert view["session"] is None and view["presence"] == "online"
    loose = factory.agent(migrated, _project(migrated), owner.id, "coder", with_session=False)
    assert owner.get(f"{PROJECT}/members/{loose.agent_id}").json()["presence"] == "offline"


def test_a_request_asked_through_the_bridge_is_the_served_agents_without_an_instance(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge = _pair(migrated, owner)
    asked = make_client().post(
        f"{API}{PROJECT}/requests",
        json={"class": "decision", "title": "Which?", "to": "owner"},
        headers={
            "Authorization": f"Bearer {bridge.value}",
            "Idempotency-Key": "bridge-ask-000001",
            "Maity-For": served.agent_id,
        },
    )
    assert asked.status_code == 201, asked.text
    done = owner.post(f"{PROJECT}/requests/{asked.json()['id']}/answer", {"text": "the first"})
    assert done.status_code == 200, done.text
    with migrated.connect() as conn:
        answered = conn.execute(select(t.event).where(t.event.c.kind == "request_answered")).one()
    assert f"member:{served.agent_id}" in answered.audience
    assert not any(a.startswith(f"instance:{served.agent_id}#") for a in answered.audience)
