"""docs/api.md §8.3, tsk-x1rsd4r6htcv step 1: a held events wait reads in full on its first
pass; a later pass first looks at the project's head (one statement, with the reader's own
checks) and reads only when an event lies past its cursor. The conditions the design review set
for it, each with its tests here:

1. Scope: only the held wait's later passes. Wait 0, `after=latest` and the first pass read as
   before; a skipped pass keeps the cursor; rows past the cursor are read by the reader itself.
2. The clear before the look stays: an event committed right after a quiet look is delivered,
   by the notifier or, with its notice lost, by the fallback; a rollback moves nothing; an event
   held back under the project's lock is delivered at its commit.
3. Every skipped pass checks the reader first: isolation, a missing row, a bridge's connection
   and the bridge's own membership end the wait as a read would.
4. No pass skips supersession, a disconnect, the shutdown or the deadline.
5. The cost is pinned: one statement a pass (two for a bridge), no read, in the real wait."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from sqlalchemy import Engine, event, update
from starlette.requests import Request

from maity_hub import clock, events, longpoll
from maity_hub import tables as t
from maity_hub.routes import events as events_route
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_bridge_reads import PROJECT, _bridge_row, _get, _pair, _project, _tell

FAST = 0.05  # the fallback between passes here: many passes in a short wait


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


@pytest.fixture
def fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(events_route, "FALLBACK_SECONDS", FAST)


@pytest.fixture
def reads(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """One entry per full read of a held wait (`events.read_waking`)."""
    calls: list[int] = []
    real = events.read_waking

    def counted(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(events, "read_waking", counted)
    return calls


def _is_look(statement: str) -> bool:
    """The look of a skipped pass: the project's highest `seq` (`quiet` in routes/events.py).
    Nothing else a held wait sends asks for it."""
    return "max(event.seq)" in statement


def _recorded(engine: Engine, call: Callable[[], Any]) -> tuple[list[str], Any]:
    """The statements the engine sends during `call`, but two that belong to no pass:
    SQLite's `BEGIN IMMEDIATE`, the start of a transaction there (`db._sqlite_begin_immediate`),
    which the server engines send through no cursor; every pass has one transaction, with the
    look as without it. And on PostgreSQL the wait's row in `long_poll` (`wakeups.opened`),
    written once per wait and deleted in its `finally`, which may run after the answer is out."""
    seen: list[str] = []

    def heard(_conn: Any, _cursor: Any, statement: str, *_: Any) -> None:
        if statement != "BEGIN IMMEDIATE" and "long_poll" not in statement:
            seen.append(statement)

    event.listen(engine, "before_cursor_execute", heard)
    try:
        result = call()
    finally:
        event.remove(engine, "before_cursor_execute", heard)
    return seen, result


def _agent(engine: Engine, owner: flow.Human) -> factory.Agent:
    return factory.agent(engine, _project(engine), owner.id, "coder", instance="qt01")


def _latest(client: Any, reader: factory.Agent, base: str) -> int:
    got = _get(client, reader, f"{base}after=latest")
    assert got.status_code == 200, got.text
    cursor: int = got.json()["cursor"]
    return cursor


def _until_waiting(marker: str) -> longpoll.Waiter:
    deadline = time.monotonic() + 10
    while True:
        found = [w for key, w in list(longpoll.registry._by_key.items()) if marker in key]
        if found:
            return found[0]
        assert time.monotonic() < deadline, "the wait never opened"
        time.sleep(0.02)


@pytest.fixture
def pool() -> Iterator[ThreadPoolExecutor]:
    with ThreadPoolExecutor(max_workers=2) as running:
        yield running


# --- 5. the cost, pinned in the real held wait ---------------------------------------------


@pytest.mark.parametrize("who", ["agent", "bridge", "human"])
def test_an_idle_held_wait_costs_one_look_a_pass_not_a_read(
    who: str,
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    fast: None,
    reads: list[int],
) -> None:
    """Counting rule: every statement the engine sends during the call (`_recorded`). Two
    waits of 1 s and 2 s differ only in their number of passes, so the difference in
    statements over the difference in looks is the cost of a skipped pass: the look, and for
    a bridge the check that its connection still carries the agent (`_still_carried`). Only
    the first pass reads. On main every pass reads: there are no looks, and a pass costs four
    statements (an agent's or a bridge's) or two (a human's)."""
    client = make_client()
    if who == "human":
        base = f"{PROJECT}/events?"
        after = owner.get(f"{base}after=latest").json()["cursor"]

        def held(wait: int) -> Any:
            return owner.get(f"{base}after={after}&wait={wait}")

    else:
        if who == "bridge":
            served, reader = _pair(migrated, owner)
            base = f"{PROJECT}/events?for={served.agent_id}&"
        else:
            reader = _agent(migrated, owner)
            base = f"{PROJECT}/events?"
        after = _latest(client, reader, base)

        def held(wait: int) -> Any:
            return _get(client, reader, f"{base}after={after}&wait={wait}")

    measured = []
    for wait in (1, 2):
        reads.clear()
        seen, got = _recorded(migrated, lambda w=wait: held(w))  # type: ignore[misc]
        assert got.status_code == 200, got.text
        assert (got.json()["items"], got.json()["cursor"]) == ([], after)  # the head unchanged
        measured.append((len(seen), sum(map(_is_look, seen)), len(reads)))
    (short, short_looks, short_reads), (long, long_looks, long_reads) = measured
    assert short_reads == long_reads == 1, measured  # the first pass alone reads
    assert long_looks > short_looks >= 5, measured
    per_pass = 2 if who == "bridge" else 1
    assert long - short == (long_looks - short_looks) * per_pass, measured


# --- 1. scope -------------------------------------------------------------------------------


def test_wait_zero_and_after_latest_send_no_look(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, fast: None
) -> None:
    reader, client = _agent(migrated, owner), make_client()
    for query in ("after=latest", "after=0", "after=latest&wait=0"):
        path = f"{PROJECT}/events?{query}"
        seen, got = _recorded(migrated, lambda p=path: _get(client, reader, p))  # type: ignore[misc]
        assert got.status_code == 200, got.text
        assert not any(map(_is_look, seen)), query


def test_a_skipped_pass_keeps_the_cursor_also_past_the_end(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, fast: None, reads: list[int]
) -> None:
    """The look never hands its maximum out as a cursor: a pass it skips answers `since`."""
    reader = _agent(migrated, owner)
    got = _get(make_client(), reader, f"{PROJECT}/events?after=999999&wait=1")
    assert got.status_code == 200, got.text
    assert (got.json()["items"], got.json()["cursor"]) == ([], 999999)
    assert reads == [1]


def test_rows_past_the_cursor_it_may_not_read_are_read_by_the_reader(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    fast: None,
    reads: list[int],
    pool: ThreadPoolExecutor,
) -> None:
    """Rows past the cursor that do not wake the reader (here messages to another agent):
    the look sees them and the pass reads, so the cursor moves exactly as a read's does."""
    reader, other, client = _agent(migrated, owner), _agent(migrated, owner), make_client()
    after = _latest(client, reader, f"{PROJECT}/events?")
    waiting = pool.submit(_get, make_client(), reader, f"{PROJECT}/events?after={after}&wait=2")
    _until_waiting(reader.credential_id)
    sent = [_tell(owner, other.agent_id, f"not for you {n}") for n in range(3)]
    got = waiting.result(timeout=15)
    assert got.status_code == 200, got.text
    plain = _get(client, reader, f"{PROJECT}/events?after={after}").json()
    assert got.json()["items"] == [] and got.json()["cursor"] == plain["cursor"] >= sent[-1]
    assert len(reads) > 1  # read in full after the look saw them


# --- 2. the clear before the look, the notifier, the fallback ------------------------------


def _right_after_the_look(
    engine: Engine, then: Callable[[], None]
) -> tuple[Callable[[], None], list[float]]:
    """Runs `then` in a thread at the first look; returns the unhook and when it started."""
    started: list[float] = []

    def heard(_conn: Any, _cursor: Any, statement: str, *_: Any) -> None:
        if _is_look(statement) and not started:
            started.append(time.monotonic())
            threading.Thread(target=then).start()

    event.listen(engine, "after_cursor_execute", heard)
    return (lambda: event.remove(engine, "after_cursor_execute", heard)), started


@pytest.mark.parametrize("notice", ["heard", "lost"])
def test_an_event_right_after_a_quiet_look_is_delivered(
    notice: str,
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    fast: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Heard: from the look on the fallback is 30 s, so only the notifier can deliver it in
    time. Lost: no notice reaches the wait, and the unchanged fallback reads it."""
    reader, client = _agent(migrated, owner), make_client()
    after = _latest(client, reader, f"{PROJECT}/events?")

    def then() -> None:
        if notice == "heard":
            monkeypatch.setattr(events_route, "FALLBACK_SECONDS", 30)
        _tell(owner, reader.agent_id, "right after the look")

    if notice == "lost":
        monkeypatch.setattr(events.notifier, "notify", lambda *_: None)
    unhook, started = _right_after_the_look(migrated, then)
    try:
        got = _get(client, reader, f"{PROJECT}/events?after={after}&wait=20")
    finally:
        unhook()
    assert got.status_code == 200, got.text
    assert [e["payload"]["body"] for e in got.json()["items"]] == ["right after the look"]
    assert started and time.monotonic() - started[0] < 10


def test_a_rolled_back_event_moves_nothing(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    fast: None,
    pool: ThreadPoolExecutor,
) -> None:
    reader, client = _agent(migrated, owner), make_client()
    after = _latest(client, reader, f"{PROJECT}/events?")
    waiting = pool.submit(_get, make_client(), reader, f"{PROJECT}/events?after={after}&wait=1")
    project_id = _project(migrated)  # not inside the transaction: SQLite has one writer
    _until_waiting(reader.credential_id)
    with pytest.raises(RuntimeError, match="roll back"), events.transaction(migrated) as conn:
        events.emit(conn, project_id, "state_changed", ["all"], {})
        raise RuntimeError("roll back")
    got = waiting.result(timeout=10)
    assert (got.json()["items"], got.json()["cursor"]) == ([], after)


def test_an_event_held_under_the_project_lock_is_delivered_at_its_commit(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    fast: None,
    pool: ThreadPoolExecutor,
) -> None:
    """While a writer holds the project's lock with its event written and not committed, the
    looks see no row past the cursor; at the commit the event is delivered. On PostgreSQL and
    MariaDB the lock is `SELECT … FOR UPDATE`, SQLite takes its write lock at BEGIN."""
    reader, client = _agent(migrated, owner), make_client()
    after = _latest(client, reader, f"{PROJECT}/events?")
    waiting = pool.submit(_get, make_client(), reader, f"{PROJECT}/events?after={after}&wait=20")
    project_id = _project(migrated)  # not inside the transaction: SQLite has one writer
    _until_waiting(reader.credential_id)
    with events.transaction(migrated) as conn:
        events.lock_project(conn, project_id)
        seq = events.emit(
            conn,
            project_id,
            "message",
            [f"member:{reader.agent_id}"],
            {"type": "notice", "body": "held back", "to": reader.agent_id},
        )
        time.sleep(0.5)  # the wait passes meanwhile, or on SQLite waits for the lock
    got = waiting.result(timeout=15)
    assert got.status_code == 200, got.text
    assert [e["seq"] for e in got.json()["items"]] == [seq]


# --- 3. the reader's checks on every skipped pass ------------------------------------------


def test_an_isolated_agent_ends_an_idle_wait(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    fast: None,
    pool: ThreadPoolExecutor,
) -> None:
    """Changed in the database without an event or a notice, as another replica would: the
    next skipped pass reads the row and ends the wait, never an endless empty one. A missing
    row the look also takes as not quiet, so the read decides as it does without the look;
    the foreign keys on `membership` keep the row from going while anything refers to it."""
    reader, client = _agent(migrated, owner), make_client()
    after = _latest(client, reader, f"{PROJECT}/events?")
    began = time.monotonic()
    waiting = pool.submit(_get, make_client(), reader, f"{PROJECT}/events?after={after}&wait=20")
    _until_waiting(reader.credential_id)
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == reader.membership_id)
            .values(isolated_since=clock.now(), isolated_reason="x", isolated_by="x")
        )
    got = waiting.result(timeout=15)
    assert got.status_code == 200, got.text
    assert got.json()["items"] == [] and time.monotonic() - began < 10


def test_an_agent_made_inactive_waits_as_it_does_without_the_look(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    fast: None,
    pool: ThreadPoolExecutor,
) -> None:
    """`active` off during the wait is no end of an agent's own wait, with or without the look
    (only a bridge's own row ends what it carries, `_still_carried`): it answers at its
    deadline. A call that starts inactive is refused before it waits."""
    reader, client = _agent(migrated, owner), make_client()
    after = _latest(client, reader, f"{PROJECT}/events?")
    began = time.monotonic()
    waiting = pool.submit(_get, make_client(), reader, f"{PROJECT}/events?after={after}&wait=1")
    _until_waiting(reader.credential_id)
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == reader.membership_id)
            .values(active=None)
        )
    got = waiting.result(timeout=15)
    assert got.status_code == 200, got.text
    assert (got.json()["items"], got.json()["cursor"]) == ([], after)
    assert 0.9 <= time.monotonic() - began < 3


@pytest.mark.parametrize("change", ["ended", "isolated", "removed", "served isolated"])
def test_a_bridge_whose_connection_or_agent_changes_ends_an_idle_wait(
    change: str,
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    fast: None,
    pool: ThreadPoolExecutor,
) -> None:
    served, bridge = _pair(migrated, owner)
    row, client = _bridge_row(migrated, bridge), make_client()
    base = f"{PROJECT}/events?for={served.agent_id}&"
    after = _latest(client, bridge, base)
    began = time.monotonic()
    waiting = pool.submit(_get, make_client(), bridge, f"{base}after={after}&wait=20")
    _until_waiting("|for:")
    isolated = {"isolated_since": clock.now(), "isolated_reason": "x", "isolated_by": "x"}
    with migrated.begin() as conn:
        if change == "ended":
            conn.execute(update(t.bridge).where(t.bridge.c.id == row.id).values(live=None))
        elif change == "served isolated":
            conn.execute(
                update(t.membership)
                .where(t.membership.c.id == served.membership_id)
                .values(**isolated)
            )
        else:
            conn.execute(
                update(t.membership)
                .where(t.membership.c.id == bridge.membership_id)
                .values(**(isolated if change == "isolated" else {"active": None}))
            )
    got = waiting.result(timeout=15)
    assert got.status_code == 200, got.text
    assert got.json()["items"] == [] and time.monotonic() - began < 10


# --- 4. nothing skips supersession, a disconnect, the shutdown, the deadline ----------------


@pytest.mark.parametrize("how", ["here", "another replica"])
def test_a_superseded_idle_wait_answers_superseded(
    how: str,
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    fast: None,
    pool: ThreadPoolExecutor,
) -> None:
    reader, client = _agent(migrated, owner), make_client()
    after = _latest(client, reader, f"{PROJECT}/events?")
    began = time.monotonic()
    first = pool.submit(_get, make_client(), reader, f"{PROJECT}/events?after={after}&wait=20")
    waiter = _until_waiting(reader.credential_id)
    if how == "here":
        second = pool.submit(_get, make_client(), reader, f"{PROJECT}/events?after={after}&wait=1")
    else:
        longpoll.registry.supersede(waiter)  # what `wakeups` does for a newer wait elsewhere
    got = first.result(timeout=15)
    assert got.status_code == 200, got.text
    assert got.json()["superseded"] is True and got.json()["cursor"] == after
    assert time.monotonic() - began < 10
    if how == "here":
        assert second.result(timeout=15).json()["superseded"] is False


def test_a_disconnect_ends_an_idle_wait(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    fast: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader, client = _agent(migrated, owner), make_client()
    after = _latest(client, reader, f"{PROJECT}/events?")
    asked = [0]

    async def gone_after_some_passes(self: Request) -> bool:
        asked[0] += 1
        return asked[0] > 5

    monkeypatch.setattr(Request, "is_disconnected", gone_after_some_passes)
    began = time.monotonic()
    got = _get(client, reader, f"{PROJECT}/events?after={after}&wait=20")
    assert got.status_code == 200, got.text
    assert (got.json()["items"], got.json()["cursor"]) == ([], after)
    assert time.monotonic() - began < 10 and asked[0] == 6


def test_the_shutdown_ends_an_idle_wait(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    fast: None,
    pool: ThreadPoolExecutor,
) -> None:
    reader, client = _agent(migrated, owner), make_client()
    after = _latest(client, reader, f"{PROJECT}/events?")
    began = time.monotonic()
    waiting = pool.submit(_get, make_client(), reader, f"{PROJECT}/events?after={after}&wait=20")
    _until_waiting(reader.credential_id)
    time.sleep(0.3)  # some skipped passes first
    longpoll.stopping.set()
    try:
        got = waiting.result(timeout=15)
    finally:
        longpoll.stopping.clear()
    assert got.status_code == 200, got.text
    assert (got.json()["items"], got.json()["cursor"]) == ([], after)
    assert time.monotonic() - began < 10


def test_an_idle_wait_ends_at_its_deadline(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, fast: None
) -> None:
    reader, client = _agent(migrated, owner), make_client()
    after = _latest(client, reader, f"{PROJECT}/events?")
    began = time.monotonic()
    seen, got = _recorded(
        migrated, lambda: _get(client, reader, f"{PROJECT}/events?after={after}&wait=1")
    )
    elapsed = time.monotonic() - began
    assert (got.json()["items"], got.json()["cursor"]) == ([], after)
    assert 0.9 <= elapsed < 3 and sum(map(_is_look, seen)) >= 5
