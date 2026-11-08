"""docs/api.md §9.2 "The unread nudge", §8.2: what humans write in a group chat without a
mention reaches an agent participant once per read cycle as `chat_unread`, `DELAY` after the
oldest such message, while one of its instances listens."""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update
from sqlalchemy import event as sqlalchemy_event

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


def test_reading_right_after_the_nudge_closes_the_cycle(room: Room) -> None:
    """The read mark is a message's seq and the nudge is written after the messages it counts:
    the cycle closes on the nudge's `newest_seq`, not its own seq (review of #1484)."""
    r = room
    first, _ = r.agents
    r.say(r.owner, "one")
    r.at(11)
    chat_unread.sweep(r.engine)
    [nudge] = r.nudges(first)
    seq = nudge.seq
    r.read(first)  # nothing newer than the nudge's messages: the mark stays below its seq
    with r.engine.connect() as conn:
        mark = conn.execute(
            select(t.conversation_read.c.last_seq)
            .join(t.membership, t.membership.c.id == t.conversation_read.c.reader)
            .where(
                t.conversation_read.c.conversation_id == r.chat,
                t.membership.c.agent_id == first.id,
            )
        ).scalar_one()
    assert mark < seq
    r.at(12)
    r.say(r.owner, "two")
    r.at(23)
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


class _Statements:
    """The SQL a block runs on the engine, with its parameters."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.seen: list[tuple[str, Any]] = []

    def __enter__(self) -> list[tuple[str, Any]]:
        sqlalchemy_event.listen(self.engine, "before_cursor_execute", self._record)
        return self.seen

    def __exit__(self, *_: object) -> None:
        sqlalchemy_event.remove(self.engine, "before_cursor_execute", self._record)

    def _record(self, _conn: Any, _cursor: Any, statement: str, params: Any, *_: Any) -> None:
        self.seen.append((statement, params))


def _reads_messages(statement: str, params: Any) -> bool:
    values = params.values() if isinstance(params, dict) else params or ()
    return "event" in statement and "message" in [v for v in values if isinstance(v, str)]


# A bare `event.payload` in a select list; `json_extract(event.payload, ?)` or
# `event.payload -> %(x)s`, which read one key, do not count.
_BARE_PAYLOAD = re.compile(r"event\.payload\s*(?:,(?!\s*[?%])|FROM\b|$)")


def test_offline_agents_read_no_message_however_much_is_unread(room: Room) -> None:
    """Review of #1490 (load): an agent nobody listens for has no nudge to close a cycle, so
    its unread range only grows; the minute pass must not read it, for any agent."""
    r = room
    for session_id, wait in r.waits:
        listening.closed(session_id, wait)
    r.waits.clear()
    for n in range(40):
        r.say(r.owner, f"long message {n} " + "x" * 2000)
    for minute in (11, 12, 13):
        r.at(minute)
        with _Statements(r.engine) as seen:
            assert chat_unread.sweep(r.engine) == []
        assert not [s for s, p in seen if _reads_messages(s, p)]


def test_a_listening_agent_reads_no_message_before_the_delay_and_no_body_at_all(
    room: Room,
) -> None:
    r = room
    first, _ = r.agents
    for n in range(40):
        r.say(r.owner, f"long message {n} " + "x" * 2000)
    r.at(9)
    with _Statements(r.engine) as seen:
        assert chat_unread.sweep(r.engine) == []
    # Before the delay only the aggregate runs: no message row is selected.
    assert not [s for s, p in seen if _reads_messages(s, p) and "min(" not in s.lower()]
    r.at(11)
    with _Statements(r.engine) as seen:
        chat_unread.sweep(r.engine)
    assert [n.payload["unread"] for n in r.nudges(first)] == [40]
    assert not [s for s, _ in seen if _BARE_PAYLOAD.search(s)]
    # The open cycle reads no message on the next passes either.
    r.at(12)
    with _Statements(r.engine) as seen:
        assert chat_unread.sweep(r.engine) == []
    assert not [s for s, p in seen if _reads_messages(s, p)]


# Each clause below has its own test (review of #1490, e5zv P3).


def _credential_of(r: Room, agent: flow.Agent, **values: Any) -> None:
    with r.engine.begin() as conn:
        conn.execute(
            update(t.credential).where(t.credential.c.id == agent.credential_id).values(**values)
        )


@pytest.mark.parametrize("column", ["dormant_since", "paused_since"])
def test_a_dormant_or_paused_instance_does_not_count_as_listening(room: Room, column: str) -> None:
    r = room
    first, second = r.agents
    _credential_of(r, first, **{column: clock.now()})
    r.say(r.owner, "one")
    r.at(11)
    chat_unread.sweep(r.engine)
    assert r.nudges(first) == [] and len(r.nudges(second)) == 1


def test_a_round_thread_is_not_nudged(room: Room) -> None:
    r = room
    r.say(r.owner, "one")
    with r.engine.begin() as conn:
        conn.execute(
            update(t.conversation).where(t.conversation.c.id == r.chat).values(hub_thread=True)
        )
    r.at(11)
    assert chat_unread.sweep(r.engine) == []


def test_a_redacted_message_is_not_counted(room: Room) -> None:
    r = room
    first, _ = r.agents
    gone = r.say(r.owner, "taken back")
    r.at(5)
    kept = r.say(r.owner, "stays")
    with r.engine.begin() as conn:
        conn.execute(update(t.event).where(t.event.c.seq == gone).values(redacted=True))
    r.at(11)
    assert chat_unread.sweep(r.engine) == []  # the oldest counted one is 6 minutes old
    r.at(16)
    chat_unread.sweep(r.engine)
    [nudge] = r.nudges(first)
    assert (nudge.payload["unread"], nudge.payload["oldest_seq"]) == (1, kept)


def test_messages_before_the_stay_are_not_counted(room: Room) -> None:
    """The window: a member re-added to a chat starts fresh from its latest join (§9.2)."""
    r = room
    first, _ = r.agents
    before = r.say(r.owner, "before the stay")
    r.at(5)
    after = r.say(r.owner, "after the stay")
    with r.engine.begin() as conn:
        member = conn.execute(
            select(t.membership.c.id).where(t.membership.c.agent_id == first.id)
        ).scalar_one()
        conn.execute(
            update(t.conversation_participant)
            .where(
                t.conversation_participant.c.conversation_id == r.chat,
                t.conversation_participant.c.membership_id == member,
            )
            .values(window_after=before)
        )
    r.at(11)
    assert chat_unread.sweep(r.engine) != []  # the second agent's nudge
    assert r.nudges(first) == []  # its only counted message is 6 minutes old
    r.at(16)
    chat_unread.sweep(r.engine)
    [nudge] = r.nudges(first)
    assert (nudge.payload["unread"], nudge.payload["oldest_seq"]) == (1, after)


# The rest of the clauses, each with its own test (review of #1490, ppge P2-1).


def test_an_isolated_membership_is_not_nudged(room: Room) -> None:
    r = room
    first, second = r.agents
    r.say(r.owner, "one")
    with r.engine.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == first.id)
            .values(isolated_since=clock.now())
        )
    r.at(11)
    chat_unread.sweep(r.engine)
    assert r.nudges(first) == [] and len(r.nudges(second)) == 1


def test_an_instance_mention_counts_as_a_mention(room: Room) -> None:
    r = room
    first, second = r.agents
    r.say(r.owner, f"@{r.handle(first)}#{first.instance} this one is yours")
    r.at(11)
    chat_unread.sweep(r.engine)
    assert r.nudges(first) == []  # mentioned through its instance
    assert len(r.nudges(second)) == 1


def test_one_agents_open_cycle_does_not_hold_back_another_agents_nudge(room: Room) -> None:
    """The cycle is per agent: the second agent's nudge, still unread and counting a message
    above the first agent's read mark, must not stop the first agent's own nudge."""
    r = room
    first, second = r.agents
    session_id, wait = r.waits.pop(0)  # the first agent stops listening for a while
    listening.closed(session_id, wait)
    r.say(r.owner, "one")
    r.read(first)  # the first agent's mark: "one"
    r.at(1)
    r.say(r.owner, "two")
    r.at(11)
    chat_unread.sweep(r.engine)
    [theirs] = r.nudges(second)
    assert theirs.payload["unread"] == 2  # "one" and "two": newest above the first's mark
    assert r.nudges(first) == []  # nobody listens for the first agent
    r.at(12)
    r.listen(first)
    chat_unread.sweep(r.engine)
    [mine] = r.nudges(first)
    assert mine.payload["unread"] == 1 and len(r.nudges(second)) == 1


def test_one_failing_stay_does_not_stop_the_others(
    room: Room, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review of #1490 (ppge P3-1): the read pass guards each stay, as the writes do."""
    r = room
    first, second = r.agents
    r.say(r.owner, "one")
    r.at(11)
    real = chat_unread.due

    def due(conn: Any, stay: Any, listens: Any = None) -> Any:
        if stay.agent_id == first.id:
            raise RuntimeError("a broken stay")
        return real(conn, stay, listens)

    monkeypatch.setattr(chat_unread, "due", due)
    chat_unread.sweep(r.engine)
    assert r.nudges(first) == [] and len(r.nudges(second)) == 1


def test_the_worker_runs_the_nudge_when_the_lease_expiry_fails(
    room: Room, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = room
    first, _ = r.agents
    r.say(r.owner, "one")
    r.at(11)
    from maity_hub import holder_stalled

    def broken(_engine: Any) -> None:
        raise RuntimeError("the lease expiry failed")

    monkeypatch.setattr(holder_stalled, "expire", broken)
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
