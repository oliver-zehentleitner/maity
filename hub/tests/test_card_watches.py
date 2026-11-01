"""Watching a card, agents included (docs/api.md §6.4, §8.2, §8.4): what wakes a watcher, the
private list fixed when an event is written, and watches that come with a dependency."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import events
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory

TASKS = "/projects/maintainer/maity/tasks"
EVENTS = "/projects/maintainer/maity/events"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def _watch(agent: flow.Agent, card: dict[str, Any]) -> Any:
    return agent.client.put(f"/api/v1{TASKS}/{card['id']}/watch", headers=agent.auth)


def _unwatch(agent: flow.Agent, card: dict[str, Any]) -> Any:
    return agent.client.delete(f"/api/v1{TASKS}/{card['id']}/watch", headers=agent.auth)


def _seqs(reader: Any) -> set[int]:
    got = reader.get(EVENTS, params={"after": 0, "limit": 200})
    assert got.status_code == 200, got.text
    return {e["seq"] for e in got.json()["items"]}


def _woken(migrated: Engine, agent: flow.Agent) -> set[int]:
    with migrated.connect() as conn:
        member = conn.execute(select(t.membership).where(t.membership.c.agent_id == agent.id)).one()
        rows, _ = events.read_waking(
            conn,
            member.project_id,
            member,
            agent.id,
            0,
            200,
            instance=agent.instance,
            credential_id=agent.credential_id,
        )
    return {r.seq for r in rows}


def _last(migrated: Engine, kind: str) -> Any:
    with migrated.connect() as conn:
        return conn.execute(
            select(t.event).where(t.event.c.kind == kind).order_by(t.event.c.seq.desc()).limit(1)
        ).one()


def test_an_agent_watches_and_stops(make_client: ClientFactory, owner: flow.Human) -> None:
    agent = flow.agent(make_client, owner)
    card = owner.post(TASKS, {"title": "Watched"}).json()
    assert _watch(agent, card).json()["watching"] is True
    assert _watch(agent, card).json()["watching"] is True  # idempotent
    assert agent.get(f"{TASKS}/{card['id']}").json()["watching"] is True
    assert owner.get(f"{TASKS}/{card['id']}").json()["watching"] is False
    assert _unwatch(agent, card).json()["watching"] is False
    assert _unwatch(agent, card).json()["watching"] is False


def test_a_status_change_wakes_a_watcher_and_an_edit_does_not(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    watcher, other = flow.agent(make_client, owner), flow.agent(make_client, owner)
    card = owner.post(TASKS, {"title": "Watched"}).json()
    assert _watch(watcher, card).status_code == 200
    assert owner.patch(f"{TASKS}/{card['id']}", {"title": "Renamed"}).status_code == 200
    edit = _last(migrated, "task_updated")
    assert f"watchers:{card['id']}" not in edit.audience
    moved = owner.patch(f"{TASKS}/{card['id']}", {"status": "cancelled"})
    assert moved.status_code == 200, moved.text
    change = _last(migrated, "task_updated")
    assert "status" in change.payload["fields"] and change.seq != edit.seq
    assert f"watchers:{card['id']}" in change.audience
    assert change.seq in _seqs(watcher) and change.seq in _woken(migrated, watcher)
    assert edit.seq not in _woken(migrated, watcher)
    assert change.seq not in _seqs(other) and change.seq not in _woken(migrated, other)


def test_an_update_message_needs_a_card_and_reaches_its_watchers(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    holder, watcher = flow.agent(make_client, owner), flow.agent(make_client, owner)
    other = flow.agent(make_client, owner)
    card = owner.post(TASKS, {"title": "Watched"}).json()
    _watch(watcher, card)
    say = {"kind": "message", "type": "update", "body": "half way"}
    refused = holder.post(EVENTS, say)
    assert refused.json()["error"]["details"]["fields"] == {"task_id": "required_for_update"}
    sent = holder.post(EVENTS, {**say, "task_id": card["id"]})
    assert sent.status_code in (200, 201), sent.text
    event = sent.json()
    assert event["audience"] == [f"member:{holder.id}", f"watchers:{card['id']}"]
    assert event["seq"] in _woken(migrated, watcher)
    assert event["seq"] not in _woken(migrated, holder)
    assert event["seq"] not in _seqs(other)
    # Another type on the card is no news for its watchers.
    notice = holder.post(EVENTS, {**say, "type": "notice", "to": "all", "task_id": card["id"]})
    assert f"watchers:{card['id']}" not in notice.json()["audience"]


def test_the_list_is_fixed_when_the_event_is_written(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    early, late = flow.agent(make_client, owner), flow.agent(make_client, owner)
    card = owner.post(TASKS, {"title": "Watched"}).json()
    _watch(early, card)
    owner.patch(f"{TASKS}/{card['id']}", {"status": "cancelled"})
    change = _last(migrated, "task_updated")
    _unwatch(early, card)
    _watch(late, card)
    assert change.seq in _seqs(early) and change.seq in _woken(migrated, early)
    assert change.seq not in _seqs(late)


def test_no_reader_learns_who_watches(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    """Token and wakes alike: the owner reads every event and sees no watcher, with a team's
    wake rule narrowing the event too; the list is never served."""
    watcher = flow.agent(make_client, owner)
    team = {"wake": "lead", "lead_instance": watcher.instance}
    assert (
        owner.patch(f"/projects/maintainer/maity/members/{watcher.id}", {"team": team}).status_code
        == 200
    )
    card = owner.post(TASKS, {"title": "Watched"}).json()
    _watch(watcher, card)
    owner.patch(f"{TASKS}/{card['id']}", {"status": "cancelled"})
    change = _last(migrated, "task_updated")
    assert watcher.id in (change.wakes or {})

    def served(reader: Any) -> dict[str, Any]:
        items = reader.get(EVENTS, params={"after": 0, "limit": 200}).json()["items"]
        return next(e for e in items if e["seq"] == change.seq)

    seen = served(owner)
    assert watcher.id not in str(seen)
    assert f"watchers:{card['id']}" in seen["audience"] and "wakes" not in seen
    assert served(watcher)["wakes"] == []  # its own entry: the lead does not listen in this test


def test_a_dependency_watches_by_itself_while_it_stands(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    awaited = owner.post(TASKS, {"title": "Awaited"}).json()
    mine = owner.post(TASKS, {"title": "Mine", "depends_on": [awaited["id"]]}).json()
    assert agent.get(f"{TASKS}/{awaited['id']}").json()["watching"] is False
    assert agent.post(f"{TASKS}/{mine['id']}/claim", {}).status_code == 200
    assert agent.get(f"{TASKS}/{awaited['id']}").json()["watching"] is True
    refused = _unwatch(agent, awaited)
    assert refused.status_code == 400 and refused.json()["error"]["details"]["reason"] == "implied"
    owner.patch(f"{TASKS}/{awaited['id']}", {"status": "cancelled"})
    assert _last(migrated, "task_updated").seq in _woken(migrated, agent)
    # It ends with the dependent card, without an event.
    assert owner.patch(f"{TASKS}/{mine['id']}", {"status": "cancelled"}).status_code == 200
    assert agent.get(f"{TASKS}/{awaited['id']}").json()["watching"] is False
    assert _unwatch(agent, awaited).status_code == 200
