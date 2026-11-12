"""The notifications answer under load (docs/api.md §18.2, §18.3): a held long-poll derives
again only when something it reads moved, full answers run a few at a time, and two
marks of the same items at once never fail on the key."""

from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any

import anyio
import pytest
from sqlalchemy import Engine, event, insert

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.config import ConfigError, Settings
from maity_hub.db import make_engine
from maity_hub.notifications import listing
from maity_hub.routes import notifications as routes
from tests import flow
from tests.conftest import ClientFactory
from tests.test_notifications import N, bell


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human, "maity")
    return human


@pytest.fixture
def answers(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """When each full answer started."""
    started: list[float] = []
    real = routes._answer

    def counted(*args: Any, **kwargs: Any) -> Any:
        started.append(time.monotonic())
        return real(*args, **kwargs)

    monkeypatch.setattr(routes, "_answer", counted)
    return started


def inbox_item(make_client: ClientFactory, owner: flow.Human) -> dict[str, Any]:
    """One unread `inbox` item of the owner's: an agent asks the owner something."""
    agent = flow.agent(make_client, owner)
    asked = agent.post(
        "/projects/maintainer/maity/requests",
        {"class": "decision", "title": "Which?", "to": "owner"},
    )
    assert asked.status_code == 201, asked.text
    [item] = [i for i in bell(owner)["items"] if i["kind"] == "inbox" and not i["read"]]
    return dict(item)


def test_a_held_long_poll_derives_again_only_when_something_moved(
    make_client: ClientFactory, owner: flow.Human, answers: list[float]
) -> None:
    item = inbox_item(make_client, owner)
    start = bell(owner, limit=0)["next_after"]
    answers.clear()
    quiet = bell(owner, after=start, wait=2)
    assert quiet["items"] == []
    assert len(answers) == 2  # the first look and the last, none in between

    answers.clear()
    held: list[dict[str, Any]] = []
    waiter = threading.Thread(target=lambda: held.append(bell(owner, after=start, wait=3)))
    waiter.start()
    time.sleep(0.8)
    assert owner.post(f"{N}/read", {"ids": [item["id"]]}).status_code == 200
    waiter.join(timeout=10)
    assert held and held[0]["items"] == []
    assert len(answers) == 3  # a read mark is movement: one more answer, then the last


def test_the_stamp_moves_with_events_and_read_marks(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    def stamp() -> tuple[Any, ...]:
        with migrated.connect() as conn:
            return listing.stamp(conn, owner.id)

    item = inbox_item(make_client, owner)
    before = stamp()
    assert stamp() == before  # nothing moved, nothing differs
    owner.post(f"{N}/read", {"ids": [item["id"]]})
    marked = stamp()
    assert marked != before
    owner.post("/projects/maintainer/maity/tasks", {"title": "Another"})
    assert stamp() == marked  # a card makes no notification: it moves nothing (§18.1)
    agent = flow.agent(make_client, owner)
    agent.post(f"/projects/maintainer/maity/conversations/{agent.id}/messages", {"body": "hi"})
    assert stamp() != marked


def test_two_marks_of_the_same_item_at_once_both_succeed(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    """The second waits for the first's row and skips it, where it failed on the key.
    SQLite serialises every writer anyway, so this runs on PostgreSQL and MariaDB; the
    first transaction is released before the worker is joined."""
    if migrated.dialect.name == "sqlite":
        pytest.skip("SQLite serialises writers; the race is the server databases'")
    item = inbox_item(make_client, owner)
    first = migrated.connect()
    started, answered = threading.Event(), threading.Event()

    def mark() -> int:
        started.set()
        status = int(owner.post(f"{N}/read", {"ids": [item["id"]]}).status_code)
        answered.set()
        return status

    pool = ThreadPoolExecutor(max_workers=1)
    first_tx = first.begin()
    try:
        first.execute(
            insert(t.notification_read).values(human_id=owner.id, seq=item["seq"], at=clock.now())
        )
        waiting = pool.submit(mark)
        assert started.wait(timeout=10)
        assert not answered.wait(timeout=1.0)  # waits for the first's row
        first_tx.commit()
        assert waiting.result(timeout=20) == 200
    finally:
        if first_tx.is_active:
            first_tx.rollback()
        first.close()
        pool.shutdown(wait=True, cancel_futures=True)
    assert [i["read"] for i in bell(owner)["items"] if i["id"] == item["id"]] == [True]


def test_marking_what_is_read_already_is_a_no_op(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    item = inbox_item(make_client, owner)
    for _ in range(2):
        assert owner.post(f"{N}/read", {"ids": [item["id"]]}).status_code == 200


def test_full_answers_run_a_few_at_a_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """Six at once, two at a time: the app's semaphore, made at first use (SQLite takes
    its write lock at BEGIN, so overlapping answers show on the semaphore, not the API)."""
    monkeypatch.setattr(routes, "AT_ONCE", 2)
    request: Any = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    running, most = [0], [0]
    lock = threading.Lock()

    def work() -> int:
        with lock:
            running[0] += 1
            most[0] = max(most[0], running[0])
        time.sleep(0.1)
        with lock:
            running[0] -= 1
        return 1

    async def main() -> list[int]:
        found: list[int] = []

        async def one() -> None:
            found.append(await routes._limited(request, work))

        async with anyio.create_task_group() as group:
            for _ in range(6):
                group.start_soon(one)
        return found

    assert anyio.run(main) == [1] * 6
    assert most[0] == 2
    assert routes._limit(request) is request.app.state.notifications_at_once  # one per app


def test_the_pool_size_comes_from_the_environment() -> None:
    base = {"MAITY_DATABASE_URL": "sqlite://"}
    found = Settings.from_env({**base, "MAITY_DB_POOL_SIZE": "8", "MAITY_DB_MAX_OVERFLOW": "0"})
    assert (found.db_pool_size, found.db_max_overflow) == (8, 0)
    default = Settings.from_env(base)
    assert (default.db_pool_size, default.db_max_overflow) == (
        16,
        16,
    )  # not SQLAlchemy's 5 + 10 (hub/context/persistence.md)
    with pytest.raises(ConfigError):
        Settings.from_env({**base, "MAITY_DB_POOL_SIZE": "0"})
    engine = make_engine("postgresql+psycopg://hub@db.invalid/maity", 8, 2)
    assert engine.pool.size() == 8  # type: ignore[attr-defined]
    engine.dispose()


def test_no_database_read_runs_on_the_event_loop(
    make_client: ClientFactory, owner: flow.Human, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The position key's first use reads the database: in a worker thread, never in the
    event loop's, where a slow read would hold every async route and timer."""
    from maity_hub.notifications import positions

    on_loop: list[bool] = []
    real = positions.prepare

    def prepare(*args: Any, **kwargs: Any) -> None:
        try:
            asyncio.get_running_loop()
            on_loop.append(True)
        except RuntimeError:
            on_loop.append(False)
        real(*args, **kwargs)

    monkeypatch.setattr(positions, "prepare", prepare)
    item = inbox_item(make_client, owner)
    start = bell(owner, limit=0)["next_after"]
    bell(owner, after=start, wait=1)
    assert owner.post(f"{N}/read", {"ids": [item["id"]]}).status_code == 200
    assert on_loop and not any(on_loop)


def test_the_derive_reads_a_fixed_number_of_queries_however_many_events(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    """One query per kind of lookup for the whole batch, never one per event: what made
    the held long-poll cost thousands of round trips per answer."""
    from maity_hub.notifications import items

    agent = flow.agent(make_client, owner)

    def act(times: int) -> None:
        for n in range(times):
            agent.post(
                "/projects/maintainer/maity/requests",
                {"class": "decision", "title": f"Which {n}?", "to": "owner"},
            )
            agent.post(
                f"/projects/maintainer/maity/conversations/{agent.id}/messages", {"body": "hi"}
            )

    def queries() -> tuple[int, int]:
        counted: list[int] = []
        with migrated.connect() as conn:
            event.listen(conn, "before_cursor_execute", lambda *a: counted.append(1))
            where = items.scope(conn, owner.id, "https://hub.example")
            found = items.derive(conn, where)
        return len(counted), len(found)

    act(4)
    few, few_items = queries()
    act(8)
    many, many_items = queries()
    assert many_items > few_items * 2  # three times the events, and their items
    assert many == few


def test_a_poll_costs_the_same_however_many_messages_are_not_the_human_s(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    """The messages that may make an item of the human are read from
    `notification_recipient` (hub/context/notifications.md fc79a4a6), not found by matching
    every message's JSON as text: the bell reads as many statements with 2,000 messages
    between agents in the window as with 20,000, and on PostgreSQL none of them scans `event`
    whole."""
    from sqlalchemy import select

    agent = flow.agent(make_client, owner)
    for body in ("@maintainer look", "hi"):  # a mention, then a chat message
        said = agent.post(
            "/projects/maintainer/maity/events",
            {"kind": "message", "type": "notice", "to": "all", "body": body},
        )
        assert said.status_code in (200, 201), said.text
    assert agent.post(
        f"/projects/maintainer/maity/conversations/{agent.id}/messages", {"body": "hi"}
    ).status_code in (200, 201)
    with migrated.connect() as conn:
        project_id = conn.execute(
            select(t.project.c.id).where(t.project.c.slug == "maity")
        ).scalar()
    unrelated = {
        "project_id": project_id, "kind": "message", "audience": ["role:coder"],
        "payload": {"body": "between agents", "mentions": []}, "redacted": False,
    }  # fmt: skip

    def add(n: int) -> None:
        with migrated.begin() as conn:
            conn.execute(insert(t.event), [{**unrelated, "at": clock.now()} for _ in range(n)])
            if conn.dialect.name == "postgresql":
                conn.exec_driver_sql("ANALYZE event")

    def poll() -> tuple[list[tuple[str, Any]], dict[str, Any]]:
        seen: list[tuple[str, Any]] = []

        def note(_c: Any, _cur: Any, statement: str, parameters: Any, *_: Any) -> None:
            seen.append((statement, parameters))

        event.listen(migrated, "before_cursor_execute", note)
        try:
            got = bell(owner)
        finally:
            event.remove(migrated, "before_cursor_execute", note)
        return seen, got

    add(2000)
    poll()  # the first look of a session reads its keys once
    few, few_got = poll()
    add(18000)
    many, many_got = poll()
    assert [s for s, _ in many] == [s for s, _ in few]
    assert many_got["items"] == few_got["items"] and many_got["counts"] == few_got["counts"]
    assert few_got["counts"]["mention"] == 1 and few_got["counts"]["chat"] >= 1
    if migrated.dialect.name != "postgresql":
        return
    scans = []
    with migrated.connect() as conn:
        for statement, parameters in many:
            # The statements that read event rows to classify; the join position's lookup
            # (`items.scope`) reads none and is a cost of its own, not of the messages.
            if statement.lstrip().upper().startswith("SELECT") and "event.payload" in statement:
                plan = conn.exec_driver_sql(f"EXPLAIN {statement}", parameters).scalars().all()
                if any("Seq Scan on event " in line for line in plan):
                    scans.append("\n".join([statement, *plan]))
    assert not scans, "\n\n".join(scans)


def test_a_message_writes_a_recipient_row_per_human_it_may_notify(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    """`events.emit` writes `notification_recipient` with the message: `chat` for a
    conversation's message to the human, `mention` for one that mentions them, nothing for a
    message between agents (hub/context/notifications.md fc79a4a6)."""
    from sqlalchemy import select

    agent = flow.agent(make_client, owner)
    said = [
        agent.post(f"/projects/maintainer/maity/conversations/{agent.id}/messages", {"body": "hi"})
    ]
    said += [
        agent.post(
            "/projects/maintainer/maity/events",
            {"kind": "message", "type": "notice", "to": "all", "body": body},
        )
        for body in ("@maintainer look", "no human named")
    ]
    assert all(s.status_code in (200, 201) for s in said), [s.text for s in said]
    r = t.notification_recipient.c
    with migrated.connect() as conn:
        rows = conn.execute(select(r.human_id, r.chat, r.mention).order_by(r.seq)).all()
    assert [(row.human_id, row.chat, row.mention) for row in rows] == [
        (owner.id, True, False),
        (owner.id, False, True),
    ]
