"""docs/api.md §9.2 "The unread nudge", §8.2: what humans write in a group chat without a
mention reaches an agent participant once per read cycle as `chat_unread`, `DELAY` after the
oldest such message, while one of its instances listens."""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import chat_unread, clock, listening, not_listening
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory

PROJECT = "/projects/maintainer/maity"
CHATS = f"{PROJECT}/conversations"


class Room:
    """The owner, a second human and two agents in one group chat, the clock in hand."""

    def __init__(self, engine: Engine, owner: flow.Human, guest: flow.Human) -> None:
        self.engine, self.owner, self.guest = engine, owner, guest
        self.agents: list[flow.Agent] = []
        self.chat = ""
        self.now = clock.now()
        self.waits: list[tuple[str, str]] = []

    def at(self, minutes: float) -> None:
        moment = self.now + timedelta(minutes=minutes)
        clock.set_source(lambda: moment)

    def listen(self, agent: flow.Agent) -> None:
        session_id = agent.resume().json()["session"]["id"]
        self.waits.append((session_id, listening.opened(session_id)))

    def say(self, who: Any, body: str) -> int:
        response = who.post(f"{CHATS}/{self.chat}/messages", {"body": body})
        assert response.status_code == 201, response.text
        return int(response.json()["seq"])

    def read(self, who: Any) -> None:
        response = who.get(f"{CHATS}/{self.chat}/messages")
        assert response.status_code == 200, response.text

    def nudges(self, agent: flow.Agent | None = None) -> list[Any]:
        with self.engine.connect() as conn:
            rows = list(
                conn.execute(
                    select(t.event).where(t.event.c.kind == "chat_unread").order_by(t.event.c.seq)
                )
            )
        if agent is None:
            return rows
        return [r for r in rows if f"member:{agent.id}" in r.audience]

    def handle(self, agent: flow.Agent) -> str:
        with self.engine.connect() as conn:
            found: str = conn.execute(
                select(t.agent_profile.c.handle).where(t.agent_profile.c.id == agent.id)
            ).scalar_one()
        return found


@pytest.fixture
def room(make_client: ClientFactory, migrated: Engine) -> Iterator[Room]:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    guest = flow.human(make_client, migrated, "guest")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "member", human_id=guest.id)
    r = Room(migrated, owner, guest)
    clock.set_source(lambda: r.now)
    r.agents = [flow.agent(make_client, owner), flow.agent(make_client, owner)]
    created = owner.post(
        CHATS,
        {"title": "Release go/no-go", "participants": [guest.id, *(a.id for a in r.agents)]},
    )
    assert created.status_code == 201, created.text
    r.chat = created.json()["id"]
    for agent in r.agents:
        r.listen(agent)
    yield r
    for session_id, wait in r.waits:
        listening.closed(session_id, wait)


def test_ten_messages_in_a_row_are_one_nudge_per_agent_and_none_for_one_that_read(
    room: Room,
) -> None:
    r = room
    first, second = r.agents
    seqs = [r.say(r.owner, f"thought {n}") for n in range(10)]
    r.read(second)  # the second agent has read past all ten
    r.at(11)
    written = chat_unread.sweep(r.engine)
    assert len(written) == 1
    [nudge] = r.nudges(first)
    assert r.nudges(second) == []
    assert nudge.audience == [f"member:{first.id}"]
    assert (nudge.subject_type, nudge.subject_id) == ("conversation", r.chat)
    assert nudge.actor_membership is None
    assert nudge.payload == {
        "conversation": {"id": r.chat, "kind": "group", "title": "Release go/no-go"},
        "unread": 10,
        "oldest_seq": seqs[0],
        "newest_seq": seqs[-1],
    }
    # Every later pass finds it written: one per read cycle, not one per minute.
    for minute in (12, 30, 120):
        r.at(minute)
        assert chat_unread.sweep(r.engine) == []
    assert len(r.nudges()) == 1


def test_not_before_the_delay_and_counted_from_the_oldest(room: Room) -> None:
    r = room
    first, _ = r.agents
    r.say(r.owner, "one")
    r.at(9)
    r.say(r.guest, "two")
    assert chat_unread.sweep(r.engine) == []
    r.at(10)  # the oldest is exactly the delay old: due
    chat_unread.sweep(r.engine)
    [nudge] = r.nudges(first)
    assert nudge.payload["unread"] == 2


def test_reading_the_chat_rearms_it_and_a_wait_does_not(room: Room) -> None:
    r = room
    first, _ = r.agents
    r.say(r.owner, "one")
    r.at(11)
    chat_unread.sweep(r.engine)
    assert len(r.nudges(first)) == 1
    # The wait that returns the nudge moves no read mark: a new message is not a new cycle.
    events = first.get(f"{PROJECT}/events", params={"after": 0, "wait": 1}).json()
    assert "chat_unread" in [e["kind"] for e in events["items"]]
    r.say(r.owner, "two")
    r.at(30)
    assert chat_unread.sweep(r.engine) == []
    # Reading the chat moves the mark; the next counted message starts a new cycle, after the
    # delay again.
    r.read(first)
    r.say(r.owner, "three")
    r.at(39)
    assert chat_unread.sweep(r.engine) == []
    r.at(41)
    chat_unread.sweep(r.engine)
    nudges = r.nudges(first)
    assert len(nudges) == 2 and nudges[1].payload["unread"] == 1


def test_posting_moves_the_mark_too(room: Room) -> None:
    r = room
    first, _ = r.agents
    r.say(r.owner, "one")
    r.say(first, "answered")  # whoever speaks has read up to there (§9.2)
    r.at(11)
    chat_unread.sweep(r.engine)
    assert r.nudges(first) == []


def test_mentions_and_agents_messages_are_not_counted(room: Room) -> None:
    r = room
    first, second = r.agents
    # The second agent speaks first: its own post moves its mark, so it goes before the rest.
    r.say(second, "an agent's message never counts")
    r.say(r.owner, f"@{r.handle(first)} your call")  # woke the first already
    r.at(11)
    chat_unread.sweep(r.engine)
    assert r.nudges(first) == []
    # The mention of the first is an unmentioned human message for the second.
    [nudge] = r.nudges(second)
    assert nudge.payload["unread"] == 1


def test_nothing_while_no_instance_listens(room: Room) -> None:
    r = room
    first, second = r.agents
    for session_id, wait in r.waits:
        listening.closed(session_id, wait)
    r.waits.clear()
    r.say(r.owner, "anyone?")
    r.at(11)
    assert chat_unread.sweep(r.engine) == []
    r.listen(first)  # its resume counts the chat in `conversations` meanwhile
    chat_unread.sweep(r.engine)
    assert len(r.nudges(first)) == 1 and r.nudges(second) == []


def test_a_paused_membership_is_not_nudged(room: Room) -> None:
    r = room
    first, second = r.agents
    with r.engine.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == first.id)
            .values(paused_since=clock.now())
        )
    r.say(r.owner, "one")
    r.at(11)
    chat_unread.sweep(r.engine)
    assert r.nudges(first) == [] and len(r.nudges(second)) == 1


def test_a_closed_chat_is_not_nudged(room: Room) -> None:
    r = room
    r.say(r.owner, "one")
    with r.engine.begin() as conn:
        conn.execute(
            update(t.conversation)
            .where(t.conversation.c.id == r.chat)
            .values(closed_at=clock.now(), closed_reason="no_humans")
        )
    r.at(11)
    assert chat_unread.sweep(r.engine) == []


def test_read_only_by_the_agent_it_names_and_it_wakes_it(room: Room) -> None:
    r = room
    first, second = r.agents
    r.say(r.owner, "one")
    r.read(second)
    r.at(11)
    [seq] = chat_unread.sweep(r.engine)
    woken = first.get(f"{PROJECT}/events", params={"after": seq - 1, "wait": 1}).json()
    assert [e["kind"] for e in woken["items"]] == ["chat_unread"]

    def kinds(who: Any) -> list[str]:
        items = who.get(f"{PROJECT}/events", params={"after": 0, "wait": 0}).json()["items"]
        return [e["kind"] for e in items]

    assert "chat_unread" in kinds(first)
    # Not the owner's see-all, nor another participant.
    assert "chat_unread" not in kinds(r.owner)
    assert "chat_unread" not in kinds(second)
    assert "chat_unread" not in kinds(r.guest)


def test_the_worker_runs_it_with_its_minute_pass(room: Room) -> None:
    r = room
    first, _ = r.agents
    r.say(r.owner, "one")
    r.at(11)
    worker = not_listening.Worker(r.engine, interval=0.01)
    worker.start()
    try:
        for _ in range(500):
            if r.nudges(first):
                break
            time.sleep(0.01)
    finally:
        worker.stop()
    assert len(r.nudges(first)) == 1
