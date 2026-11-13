"""docs/api.md §6.2 "Isolation", §2.3 "The bridge", §6.16, §6.4: a reader's hidden windows hold for
every read path. A bridge reading for an agent is held to its own windows beside the agent's;
the notes, the card search and a restricted text's entries hide what lies in the reader's
windows; a bridge never reads a mention from a chat across projects (tsk-1w2n2t4e70qq)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import events
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_isolation import isolate
from tests.test_restricted_text import _set
from tests.test_restricted_text import get as get_restricted
from tests.test_restricted_text import put as put_restricted

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


def _pair(engine: Engine, owner: flow.Human) -> tuple[factory.Agent, factory.Agent]:
    served = factory.agent(engine, _project(engine), owner.id, "coder", instance="wk2e")
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


def _lift(owner: flow.Human, member_id: str) -> dict[str, int]:
    done = owner.client.request(
        "DELETE",
        f"{API}{PROJECT}/members/{member_id}/isolate",
        json={"hide_isolation_events": True},
        headers={"X-CSRF-Token": owner.csrf},
    )
    assert done.status_code == 200, done.text
    [window] = done.json()["isolation_windows"]
    return dict(window)


def _tell(owner: flow.Human, to: str, body: str) -> int:
    sent = owner.post(
        f"{PROJECT}/events", {"kind": "message", "type": "notice", "to": to, "body": body}
    )
    assert sent.status_code == 201, sent.text
    seq: int = sent.json()["seq"]
    return seq


def _seqs(response: Any) -> list[int]:
    assert response.status_code == 200, response.text
    return [e["seq"] for e in response.json()["items"]]


def _isolated_bridge_window(
    owner: flow.Human, bridge: factory.Agent, served: factory.Agent
) -> tuple[list[int], dict[str, int]]:
    """Messages to the served agent and to `all` while the bridge was isolated, then a lift
    that hides its window."""
    assert isolate(owner, bridge.agent_id).status_code == 200
    meanwhile = [
        _tell(owner, served.agent_id, "for the agent while its bridge was out"),
        _tell(owner, "all", "for everyone while the bridge was out"),
    ]
    chat = owner.post(f"{PROJECT}/conversations/{served.agent_id}/messages", {"body": "hidden"})
    assert chat.status_code == 201, chat.text
    meanwhile.append(chat.json()["seq"])
    window = _lift(owner, bridge.agent_id)
    assert all(window["from_seq"] <= seq <= window["to_seq"] for seq in meanwhile)
    return meanwhile, window


def test_a_carried_read_of_events_hides_the_bridges_own_window(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge = _pair(migrated, owner)
    before = _tell(owner, served.agent_id, "before")
    meanwhile, window = _isolated_bridge_window(owner, bridge, served)
    after = _tell(owner, served.agent_id, "after")
    client = make_client()
    for path, header in (
        (f"{PROJECT}/events?after=0&limit=200&for={served.agent_id}", None),
        (f"{PROJECT}/events?after=0&limit=200", served.agent_id),
        (f"{PROJECT}/events?after={before}&wait=1&for={served.agent_id}", None),
    ):
        read = _seqs(_get(client, bridge, path, header))
        assert after in read
        assert not any(window["from_seq"] <= seq <= window["to_seq"] for seq in read), path
    for seq in meanwhile:
        one = _get(client, bridge, f"{PROJECT}/events/{seq}", served.agent_id)
        assert one.status_code == 404, one.text
    listed = _seqs(_get(client, bridge, f"{PROJECT}/messages", served.agent_id))
    assert after in listed and not set(meanwhile) & set(listed)
    # The agent itself reads its window-free history in full.
    own = _seqs(_get(client, served, f"{PROJECT}/events?after=0&limit=200"))
    assert set(meanwhile) <= set(own)


def test_a_carried_read_of_the_direct_conversation_hides_the_bridges_own_window(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge = _pair(migrated, owner)
    said = owner.post(f"{PROJECT}/conversations/{served.agent_id}/messages", {"body": "early"})
    assert said.status_code == 201, said.text
    _isolated_bridge_window(owner, bridge, served)
    late = owner.post(f"{PROJECT}/conversations/{served.agent_id}/messages", {"body": "late"})
    assert late.status_code == 201, late.text
    client = make_client()
    path = f"{PROJECT}/conversations/{served.agent_id}"
    messages = _get(client, bridge, f"{path}/messages", served.agent_id)
    assert messages.status_code == 200, messages.text
    assert [m["body"] for m in messages.json()["items"]] == ["early", "late"]
    one = _get(client, bridge, path, served.agent_id)
    assert one.status_code == 200, one.text
    assert one.json()["last_message"]["body"] == "late"
    listed = _get(client, bridge, f"{PROJECT}/conversations", served.agent_id).json()["items"]
    [direct] = [c for c in listed if c.get("agent_id") == served.agent_id]
    assert direct["last_message"]["body"] == "late"
    # The agent's own read keeps the message.
    own = _get(client, served, f"{path}/messages")
    assert "hidden" in [m["body"] for m in own.json()["items"]]


def test_a_carried_read_of_a_cards_history_hides_the_bridges_own_window(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge = _pair(migrated, owner)
    card = owner.post(f"{PROJECT}/tasks", {"title": "A card"}).json()
    assert isolate(owner, bridge.agent_id).status_code == 200
    changed = owner.patch(f"{PROJECT}/tasks/{card['id']}", {"title": "Zebra rename"})
    assert changed.status_code == 200, changed.text
    _lift(owner, bridge.agent_id)
    client = make_client()
    path = f"{PROJECT}/tasks/{card['id']}/history"
    carried = _get(client, bridge, path, served.agent_id).json()["items"]
    own = _get(client, served, path).json()["items"]
    assert len(own) == len(carried) + 1


def test_a_bridge_neither_reads_nor_wakes_on_a_mention_across_projects(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge = _pair(migrated, owner)
    before = _tell(owner, served.agent_id, "before")
    project = _project(migrated)
    with events.transaction(migrated) as conn:
        seq = events.emit(
            conn,
            project,
            "cross_chat_mention",
            [f"member:{served.agent_id}"],
            {"conversation": {"id": "x", "kind": "group", "title": "private"}, "seq": 1},
            subject=("member", served.agent_id),
        )
    client = make_client()
    carried = f"{PROJECT}/events?for={served.agent_id}"
    assert seq not in _seqs(_get(client, bridge, f"{carried}&after=0"))
    assert seq not in _seqs(_get(client, bridge, f"{carried}&after={before}&wait=1"))
    assert _get(client, bridge, f"{PROJECT}/events/{seq}", served.agent_id).status_code == 404
    assert seq in _seqs(_get(client, served, f"{PROJECT}/events?after=0"))


def test_notes_of_the_window_are_neither_listed_nor_searched(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner, role="admin")
    card = owner.post(f"{PROJECT}/tasks", {"title": "A card"}).json()
    notes = f"{PROJECT}/tasks/{card['id']}/notes"
    assert owner.post(notes, {"body": "visible remark"}).status_code == 201
    isolate(owner, agent.id)
    assert owner.post(notes, {"body": "quokka remark"}).status_code == 201
    assert _lift_flow(owner, agent)
    assert owner.post(notes, {"body": "later remark"}).status_code == 201
    mine = [n["body"] for n in agent.get(f"{notes}?state=all").json()["items"]]
    assert mine == ["visible remark", "later remark"]
    theirs = [n["body"] for n in owner.get(f"{notes}?state=all").json()["items"]]
    assert "quokka remark" in theirs
    assert agent.get(f"{PROJECT}/tasks?q=quokka").json()["items"] == []
    assert [c["id"] for c in owner.get(f"{PROJECT}/tasks?q=quokka").json()["items"]] == [card["id"]]
    assert [c["id"] for c in agent.get(f"{PROJECT}/tasks?q=later").json()["items"]] == [card["id"]]


def test_a_restricted_texts_entries_of_the_window_are_hidden(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    writer = flow.agent(make_client, owner)
    card = owner.post(f"{PROJECT}/tasks", {"title": "A card"}).json()
    _set(migrated, "nobody_except", [agent.id, writer.id])
    assert put_restricted(writer, card["id"], {"text": "one", "base_version": 0}).status_code == 200
    isolate(owner, agent.id)
    assert put_restricted(writer, card["id"], {"text": "two", "base_version": 1}).status_code == 200
    assert _lift_flow(owner, agent)
    read = get_restricted(agent, card["id"])
    assert read.status_code == 200, read.text
    assert read.json()["text"] == "two"  # the state it finds
    assert [e["version"] for e in read.json()["history"]] == [1]
    full = get_restricted(writer, card["id"]).json()["history"]
    assert [e["version"] for e in full] == [2, 1]


def _lift_flow(owner: flow.Human, agent: flow.Agent) -> bool:
    done = owner.client.request(
        "DELETE",
        f"{API}{PROJECT}/members/{agent.id}/isolate",
        json={"hide_isolation_events": True},
        headers={"X-CSRF-Token": owner.csrf},
    )
    return bool(done.status_code == 200 and done.json()["isolation_windows"])
