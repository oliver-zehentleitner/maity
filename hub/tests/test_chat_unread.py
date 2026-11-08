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
from sqlalchemy import Engine, select, text, update
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

    def redact(self, seq: int) -> None:
        """A redaction as the hub writes it: the tombstone and its `event_redacted`, together."""
        response = self.owner.post(f"{PROJECT}/events/{seq}/redact", {"reason": "a test"})
        assert response.status_code == 200, response.text

    def settle(self) -> None:
        """Both agents' read marks past what came with the chat (its creation event), so a
        test with a tiny budget counts its own messages' rows only."""
        self.say(self.owner, "before the test")
        for agent in self.agents:
            self.read(agent)

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
    chat_unread.reset()  # the scans kept in memory belong to the last test's database
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


def _payload_keys(seen: list[tuple[str, Any]]) -> set[str]:
    """The payload keys the statements project, on SQLite (`JSON_EXTRACT(event.payload, ?)`
    with a `$."key"` parameter) and PostgreSQL (`event.payload -> %(name)s` with the key as
    the parameter). An occurrence of `event.payload` that is neither reads all of it."""
    keys: set[str] = set()
    for statement, params in seen:
        found = statement.count("event.payload")
        if not found:
            continue
        values = list(params.values()) if isinstance(params, dict) else list(params or ())
        named = re.findall(r"event\.payload\s*->>?\s*%\((\w+)\)s", statement)
        keys.update(str(params[name]) for name in named if isinstance(params, dict))
        sqlite = [v for v in values if isinstance(v, str) and v.startswith("$.")]
        keys.update(v.removeprefix("$.").strip('"') for v in sqlite)
        if found > len(named) + len(sqlite):
            keys.add("<all>")
    return keys


def _names_body(statement: str, params: Any) -> bool:
    values = params.values() if isinstance(params, dict) else params or ()
    return "body" in statement or any(isinstance(v, str) and "body" in v for v in values)


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


def test_a_listening_agent_reads_each_message_once_and_no_body_at_all(
    room: Room, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rows are read once, within the budget, before the delay if they are there by then;
    no later pass reads them again, and no statement reads a body (tsk-tgh0st6p2zag: the
    aggregate that let the pass skip the read before the delay went over the whole range)."""
    r = room
    first, second = r.agents
    for n in range(40):
        r.say(r.owner, f"long message {n} " + "x" * 2000)
    r.read(second)  # one agent's read is counted
    count = _RowCount(monkeypatch)
    r.at(9)
    assert chat_unread.sweep(r.engine) == []
    # Read once, though not due yet: the 40 messages and the chat's creation, the event rows
    # the read goes over (tsk-tgh0st6p2zag: the limit counts every event row of the range).
    assert count.rows == 41
    r.at(9.5)
    assert chat_unread.sweep(r.engine) == [] and count.rows == 41
    r.at(11)
    with _Statements(r.engine) as seen:
        chat_unread.sweep(r.engine)
    assert [n.payload["unread"] for n in r.nudges(first)] == [40]
    assert count.rows == 41  # the nudge came from what was read before
    assert not [s for s, _ in seen if _BARE_PAYLOAD.search(s)]
    # Nor any projection of the payload but the mentions, a nudge's newest_seq and a
    # redaction's target seq (review of #1490, P3): never a body.
    assert not [s for s, p in seen if _names_body(s, p)]
    assert _payload_keys(seen) <= {"mentions", "newest_seq", "seq"}
    # The open cycle reads no message on the next passes either.
    r.at(12)
    chat_unread.sweep(r.engine)
    assert count.rows == 41


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

    def due(conn: Any, stay: Any, listens: Any = None, extend: bool = True) -> Any:
        if stay.agent_id == first.id:
            raise RuntimeError("a broken stay")
        return real(conn, stay, listens, extend)

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


# The read is incremental and bounded (review of #1490 delta, P2): what a stay's scan has
# read is not read again while its mark stands.


class _RowCount:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.rows = 0
        real = chat_unread._rows_after

        def counted(conn: Any, stay: Any, after: int, upto: int, limit: int) -> list[Any]:
            found = real(conn, stay, after, upto, limit)
            self.rows += len(found)
            return found

        monkeypatch.setattr(chat_unread, "_rows_after", counted)


def test_a_backlog_that_mentions_the_agents_is_read_once_not_each_minute(
    room: Room, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every unread message mentions both agents: none counts, no nudge opens a cycle, and
    still the rows are read on the first pass only."""
    r = room
    first, second = r.agents
    for n in range(5):
        r.say(r.owner, f"@{r.handle(first)} @{r.handle(second)} point {n}")
    count = _RowCount(monkeypatch)
    per_pass = []
    for minute in (11, 12, 13):
        r.at(minute)
        before = count.rows
        assert chat_unread.sweep(r.engine) == []
        per_pass.append(count.rows - before)
    assert per_pass == [12, 0, 0]  # per agent the five messages and the chat's creation, once
    r.say(r.owner, "and one without a mention")
    r.at(24)
    before = count.rows
    chat_unread.sweep(r.engine)
    assert count.rows - before == 2  # only the new row, per agent
    assert [n.payload["unread"] for n in r.nudges()] == [1, 1]


def test_a_long_backlog_is_read_over_several_passes_and_counted_exactly(
    room: Room, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = room
    first, second = r.agents
    r.settle()
    seqs = [r.say(r.owner, f"line {n}") for n in range(7)]
    r.read(second)  # only the first agent's backlog is read
    monkeypatch.setattr(chat_unread, "SCAN_BATCH", 2)
    monkeypatch.setattr(chat_unread, "SCAN_BUDGET", 3)
    count = _RowCount(monkeypatch)
    passes = 0
    for minute in range(11, 20):
        r.at(minute)
        before = count.rows
        chat_unread.sweep(r.engine)
        assert count.rows - before <= 3  # the budget per stay and pass
        passes += 1
        if r.nudges(first):
            break
    [nudge] = r.nudges(first)
    assert passes == 3  # 3 + 3 + 1 rows, the last pass finds the end
    assert (nudge.payload["unread"], nudge.payload["oldest_seq"]) == (7, seqs[0])
    assert nudge.payload["newest_seq"] == seqs[-1]


def test_a_redaction_inside_the_range_read_starts_the_read_over(
    room: Room, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = room
    first, second = r.agents
    r.settle()
    gone = r.say(r.owner, "taken back")
    kept = r.say(r.owner, "stays")
    r.read(second)
    monkeypatch.setattr(chat_unread, "SCAN_BATCH", 1)
    monkeypatch.setattr(chat_unread, "SCAN_BUDGET", 1)
    r.at(11)
    assert chat_unread.sweep(r.engine) == []  # read "taken back" only, not at the end yet
    r.redact(gone)
    for minute in range(12, 20):  # one event row a pass: the redacted message is one of them
        r.at(minute)
        chat_unread.sweep(r.engine)
        if r.nudges(first):
            break
    [nudge] = r.nudges(first)
    assert (nudge.payload["unread"], nudge.payload["oldest_seq"]) == (1, kept)


def test_a_failed_statement_in_one_stay_does_not_spoil_the_others(
    room: Room, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review of #1490 (ppge P3-1): a real SQL error in one stay's read. On PostgreSQL it
    aborts the transaction, which the read pass rolls back before the next stay."""
    r = room
    first, second = r.agents
    r.say(r.owner, "one")
    r.at(11)
    real = chat_unread._mark

    def mark(conn: Any, stay: Any) -> int:
        if stay.agent_id == first.id:
            conn.execute(text("SELECT no_such_column FROM no_such_table"))
        return real(conn, stay)

    monkeypatch.setattr(chat_unread, "_mark", mark)
    chat_unread.sweep(r.engine)
    assert r.nudges(first) == [] and len(r.nudges(second)) == 1


def test_the_worker_runs_the_nudge_when_the_not_listening_sweep_fails(
    room: Room, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review of #1490 (ppge P3-3)."""
    r = room
    first, _ = r.agents
    r.say(r.owner, "one")
    r.at(11)

    def broken(_engine: Any) -> None:
        raise RuntimeError("the not-listening sweep failed")

    monkeypatch.setattr(not_listening, "sweep", broken)
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


def test_a_redaction_between_the_read_and_the_write_is_not_counted(
    room: Room, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review of #1490, delta 2: a redaction committed after the rows were read must not end
    up in the nudge. The check under the lock sees the redaction count over the bounded
    range moved and reads it again."""
    r = room
    if r.engine.dialect.name != "postgresql":
        # SQLite lets no other connection commit while the read pass holds its read lock,
        # so the race cannot happen there; it is PostgreSQL's READ COMMITTED that allows it.
        pytest.skip("a concurrent commit during the read needs PostgreSQL")
    first, second = r.agents
    gone = r.say(r.owner, "taken back")
    kept = r.say(r.owner, "stays")
    r.read(second)
    r.at(11)
    real = chat_unread._rows_after
    done: list[bool] = []

    def rows_then_redact(conn: Any, stay: Any, after: int, upto: int, limit: int) -> list[Any]:
        found = real(conn, stay, after, upto, limit)
        if found and not done:  # the first read of the pass, outside the lock
            done.append(True)
            r.redact(gone)  # committed by another writer (the API) meanwhile
        return found

    monkeypatch.setattr(chat_unread, "_rows_after", rows_then_redact)
    chat_unread.sweep(r.engine)
    [nudge] = r.nudges(first)
    assert (nudge.payload["unread"], nudge.payload["oldest_seq"]) == (1, kept)


def test_a_redaction_while_a_cached_read_extends_its_bound_is_not_counted(
    room: Room, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review of #1490, delta 3: a scan that read the first message in an earlier pass extends
    its bound to a new message; a redaction of the first, committed right after the check of
    the range already read, must not be adopted into the new count."""
    r = room
    if r.engine.dialect.name != "postgresql":
        pytest.skip("a concurrent commit during the read needs PostgreSQL")
    first, second = r.agents
    r.settle()
    gone = r.say(r.owner, "taken back")
    r.read(second)
    monkeypatch.setattr(chat_unread, "SCAN_BATCH", 1)
    monkeypatch.setattr(chat_unread, "SCAN_BUDGET", 1)
    r.at(11)
    assert chat_unread.sweep(r.engine) == []  # read "taken back", the end not seen yet
    monkeypatch.setattr(chat_unread, "SCAN_BATCH", 500)
    monkeypatch.setattr(chat_unread, "SCAN_BUDGET", 2000)
    r.at(12)
    kept = r.say(r.owner, "stays")
    r.read(second)
    real = chat_unread._newest_seq
    armed: list[bool] = [True]

    def newest_then_redact(conn: Any, stay: Any) -> Any:
        found = real(conn, stay)
        if armed and stay.agent_id == first.id:  # once, after the redaction check, as it extends
            armed.clear()
            r.redact(gone)  # committed by another writer (the API) meanwhile
        return found

    monkeypatch.setattr(chat_unread, "_newest_seq", newest_then_redact)
    r.at(23)
    chat_unread.sweep(r.engine)
    [nudge] = r.nudges(first)
    assert (nudge.payload["unread"], nudge.payload["oldest_seq"]) == (1, kept)


def test_messages_arriving_faster_than_the_budget_still_lead_to_a_nudge(
    room: Room, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review of #1490, delta 4: a bound that grew on every call before the read reached it
    kept a full batch each pass while new messages kept coming, and no nudge ever went out.
    Now pass 0 reads two of the first three, pass 1 the third, and the nudge covers those."""
    r = room
    first, second = r.agents
    r.settle()
    monkeypatch.setattr(chat_unread, "SCAN_BATCH", 2)
    monkeypatch.setattr(chat_unread, "SCAN_BUDGET", 2)
    sent: list[int] = []
    for n in range(5):
        r.at(11 * n)
        sent += [r.say(r.owner, f"pass {n} line {k}") for k in range(3)]  # > the budget
        r.read(second)  # only the first agent's read is under test
        r.at(11 * n + 11)
        chat_unread.sweep(r.engine)
        if r.nudges(first):
            break
    [nudge] = r.nudges(first)
    assert n == 1
    assert (nudge.payload["unread"], nudge.payload["oldest_seq"]) == (3, sent[0])
    assert nudge.payload["newest_seq"] == sent[2]


def test_a_read_that_ends_on_redacted_rows_still_finishes(
    room: Room, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rows after the last one read may all be redacted: the read counts them as read
    and finishes, so the bound can grow again."""
    r = room
    first, second = r.agents
    kept = r.say(r.owner, "stays")
    gone = r.say(r.owner, "taken back")
    r.read(second)
    with r.engine.begin() as conn:
        conn.execute(update(t.event).where(t.event.c.seq == gone).values(redacted=True))
    r.at(11)
    chat_unread.sweep(r.engine)
    [nudge] = r.nudges(first)
    assert (nudge.payload["unread"], nudge.payload["newest_seq"]) == (1, kept)


def _event_rows_read(engine: Engine, seen: list[tuple[str, Any]]) -> int:
    """The event rows PostgreSQL touches for the SELECTs in `seen`, by EXPLAIN ANALYZE: rows
    each scan of `event` returned or removed by a filter, times its loops, with sequential
    scans turned off."""

    def walk(node: dict[str, Any]) -> int:
        own = 0
        if node.get("Relation Name") == "event":
            touched = node.get("Actual Rows", 0) + node.get("Rows Removed by Filter", 0)
            own = int(touched * node.get("Actual Loops", 1))
        return own + sum(walk(child) for child in node.get("Plans", []))

    total = 0
    with engine.connect() as conn:
        # The work an index plan does: on a table this small the planner may scan it whole
        # instead, which would measure the table, not the pass.
        conn.exec_driver_sql("SET enable_seqscan = off")
        for statement, params in seen:
            if not statement.lstrip().upper().startswith("SELECT") or "event" not in statement:
                continue
            plan = conn.exec_driver_sql("EXPLAIN (ANALYZE, FORMAT JSON) " + statement, params)
            found: Any = plan.scalar()
            total += walk(found[0]["Plan"])
    return total


def test_the_database_work_of_a_pass_does_not_grow_with_the_unread_history(room: Room) -> None:
    """tsk-tgh0st6p2zag (1): a backlog that never leads to a nudge (every message mentions the
    agent) is read once; after that, a pass touches as many event rows at 400 unread messages as
    at 10. The aggregates over the unread range it replaces grew with it."""
    r = room
    if r.engine.dialect.name != "postgresql":
        pytest.skip("EXPLAIN ANALYZE's row counts are PostgreSQL's")
    first, second = r.agents
    with r.engine.begin() as conn:  # only the first agent's stay is measured
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == second.id)
            .values(paused_since=clock.now())
        )
    template = r.say(r.owner, f"@{r.handle(first)} on you")

    def clone(n: int) -> None:  # more of the same message, as the hub would store them
        columns = [c.name for c in t.event.columns if c.name != "seq"]
        listed = ", ".join(columns)
        with r.engine.begin() as conn:
            for _ in range(n):
                conn.exec_driver_sql(
                    f"INSERT INTO event ({listed}) SELECT {listed} FROM event WHERE seq = %(s)s",
                    {"s": template},
                )

    def measured_pass(minute: float) -> int:
        r.at(minute)
        chat_unread.sweep(r.engine)  # reads what is new
        r.at(minute + 1)
        with _Statements(r.engine) as seen:
            assert chat_unread.sweep(r.engine) == []
        return _event_rows_read(r.engine, seen)

    clone(9)
    at_ten = measured_pass(11)
    clone(390)
    at_four_hundred = measured_pass(13)
    assert r.nudges(first) == []
    assert at_four_hundred == at_ten, (at_ten, at_four_hundred)


def _clone(engine: Engine, template: int, n: int) -> None:
    """n more copies of the event `template`, as the hub would store them."""
    columns = [c.name for c in t.event.columns if c.name != "seq"]
    listed = ", ".join(columns)
    with engine.begin() as conn:
        for _ in range(n):
            conn.exec_driver_sql(
                f"INSERT INTO event ({listed}) SELECT {listed} FROM event WHERE seq = %(s)s",
                {"s": template},
            )


@pytest.mark.parametrize("workload", ["mentions", "agents", "redacted", "nudges"])
def test_the_first_pass_over_a_backlog_touches_rows_by_the_budget_not_the_backlog(
    room: Room, monkeypatch: pytest.MonkeyPatch, workload: str
) -> None:
    """tsk-tgh0st6p2zag (1), review of #1512 R1 (4hch): with a budget of 5, the first pass over
    a backlog of 50 events that never count touches as many event rows as over 400: messages
    that mention the agent, an agent's messages, redacted messages, and another agent's nudges
    (which the open-cycle check read in full each minute)."""
    r = room
    if r.engine.dialect.name != "postgresql":
        pytest.skip("EXPLAIN ANALYZE's row counts are PostgreSQL's")
    first, second = r.agents
    if workload == "mentions":
        template = r.say(r.owner, f"@{r.handle(first)} on you")
    elif workload == "agents":
        template = r.say(second, "an agent's message")
    elif workload == "redacted":
        template = r.say(r.owner, "taken back")
        r.redact(template)
    else:
        r.say(r.owner, "for the second agent")
        r.read(first)
        r.at(11)
        chat_unread.sweep(r.engine)
        [nudge] = r.nudges(second)
        template = int(nudge.seq)
    with r.engine.begin() as conn:  # only the first agent's stay is measured
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == second.id)
            .values(paused_since=clock.now())
        )
    monkeypatch.setattr(chat_unread, "SCAN_BATCH", 5)
    monkeypatch.setattr(chat_unread, "SCAN_BUDGET", 5)

    def first_pass(minute: float) -> int:
        chat_unread.reset()  # as after a restart: nothing read yet
        r.at(minute)
        with _Statements(r.engine) as seen:
            chat_unread.sweep(r.engine)
        return _event_rows_read(r.engine, seen)

    _clone(r.engine, template, 50)
    at_fifty = first_pass(30)
    _clone(r.engine, template, 350)
    at_four_hundred = first_pass(31)
    assert r.nudges(first) == []
    assert at_four_hundred == at_fifty, (at_fifty, at_four_hundred)


@pytest.mark.parametrize("per_pass", [2, 3])
def test_later_redactions_do_not_keep_the_read_from_finishing(
    room: Room, monkeypatch: pytest.MonkeyPatch, per_pass: int
) -> None:
    """Review of #1512 R1 (4hch): before every pass, later messages are written and redacted,
    a full batch of redactions (2) or more than one (3) each time, none of them in the range
    read. The read of the first three still finishes and the nudge counts them; it used to
    stop for good."""
    r = room
    first, second = r.agents
    r.settle()
    monkeypatch.setattr(chat_unread, "SCAN_BATCH", 2)
    monkeypatch.setattr(chat_unread, "SCAN_BUDGET", 2)
    originals = [r.say(r.owner, f"original {k}") for k in range(3)]
    for n in range(8):
        for k in range(per_pass):
            r.redact(r.say(r.owner, f"later {n}.{k}"))
        r.read(second)  # only the first agent's read is under test
        r.at(11 + n)
        chat_unread.sweep(r.engine)
        if r.nudges(first):
            break
    [nudge] = r.nudges(first)
    assert (nudge.payload["unread"], nudge.payload["oldest_seq"]) == (3, originals[0])
    assert nudge.payload["newest_seq"] == originals[-1]
