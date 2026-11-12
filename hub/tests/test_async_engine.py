"""The async engine beside the sync one (tsk-v874y63b4z8p, PR 1): the same database, options and
hooks, the sync `Connection` code run through `AsyncConnection.run_sync`, and the context of the
request reaching the cursor events there, as it reaches them in the thread pool today."""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, event, insert, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from maity_hub import db, events, timing, write_guard
from maity_hub import tables as t
from maity_hub.db import async_url, head_revision
from maity_hub.errors import ApiError
from tests import flow
from tests.async_engine import on_async_engine
from tests.conftest import ClientFactory


@pytest.mark.parametrize(
    ("given", "wanted"),
    [
        ("postgresql+psycopg://u:p@db/maity", "postgresql+psycopg_async://u:p@db/maity"),
        ("mysql+pymysql://u:p@db/maity", "mysql+aiomysql://u:p@db/maity"),
        ("mariadb+pymysql://u:p@db/maity", "mariadb+aiomysql://u:p@db/maity"),
        ("sqlite:////var/lib/maity/hub.db", "sqlite+aiosqlite:////var/lib/maity/hub.db"),
    ],
)
def test_the_async_url_names_the_async_driver_of_each_one_the_hub_ships(
    given: str, wanted: str
) -> None:
    assert async_url(given).render_as_string(hide_password=False) == wanted


def test_a_driver_the_hub_does_not_ship_has_no_async_url() -> None:
    with pytest.raises(ValueError, match="no async driver"):
        async_url("postgresql+psycopg2://u@db/maity")


def test_run_sync_hands_sync_code_the_same_database(migrated: Engine) -> None:
    def revision(conn: Connection) -> str | None:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()

    async def work(engine: AsyncEngine) -> str | None:
        async with engine.begin() as conn:
            return await conn.run_sync(revision)

    assert on_async_engine(migrated, work) == head_revision(migrated)


def test_sqlite_through_the_async_engine_has_the_pragmas_and_begins_immediate(
    migrated: Engine,
) -> None:
    if migrated.dialect.name != "sqlite":
        pytest.skip("SQLite's own connection setup")
    sent: list[str] = []

    async def work(engine: AsyncEngine) -> int:
        event.listen(engine.sync_engine, "before_cursor_execute", lambda *a: sent.append(a[2]))
        async with engine.begin() as conn:
            return int((await conn.execute(text("PRAGMA foreign_keys"))).scalar_one())

    assert on_async_engine(migrated, work) == 1
    assert sent[0] == "BEGIN IMMEDIATE"


def _insert_lock(conn: Connection) -> None:
    conn.execute(insert(t.account_lock).values(human_id="hum-nobody"))


def test_the_write_guard_sees_the_callers_human_inside_run_sync(migrated: Engine) -> None:
    """The guard reads the human from a context variable that `deps._resolve` sets; the routes
    that move to `run_sync` run their statements in SQLAlchemy's greenlet, which must see the
    request's context as the thread pool's copy of it does. A human that does not exist is
    refused before the first write."""

    async def work(engine: AsyncEngine) -> ApiError | None:
        write_guard.bind("hum-nobody")
        try:
            async with engine.begin() as conn:
                await conn.run_sync(_insert_lock)
        except ApiError as refused:
            return refused
        return None

    refused = on_async_engine(migrated, work)
    assert refused is not None and refused.code == "unauthenticated"


def _three(conn: Connection) -> None:
    for _ in range(3):
        conn.execute(select(t.human.c.id).limit(1)).all()


def test_the_request_tally_counts_through_run_sync_what_it_counts_in_a_thread(
    migrated: Engine,
) -> None:
    """The `Server-Timing` tally lives in a context variable as well: the same work counts the
    same statements on either engine (SQLite adds its `BEGIN IMMEDIATE` to both)."""
    timing.install(migrated)
    sync_tally = timing.Tally()

    def in_a_thread() -> None:
        timing._TALLY.set(sync_tally)
        with migrated.begin() as conn:
            _three(conn)

    worker = threading.Thread(target=in_a_thread)
    worker.start()
    worker.join()

    async def work(engine: AsyncEngine) -> int:
        tally = timing.Tally()
        timing._TALLY.set(tally)
        async with engine.begin() as conn:
            await conn.run_sync(_three)
        return tally.statements

    assert sync_tally.statements >= 3
    assert on_async_engine(migrated, work) == sync_tally.statements


def test_the_async_engines_statements_reach_the_cursor_events_of_its_sync_engine(
    migrated: Engine,
) -> None:
    """What the statement counts (`tests/statements.py`) listen to: on the async engine they hang
    on its `sync_engine`, where SQLAlchemy runs the cursor events."""

    async def work(engine: AsyncEngine) -> list[str]:
        seen: list[str] = []

        def counted(*args: Any) -> None:
            seen.append(args[2])

        event.listen(engine.sync_engine, "before_cursor_execute", counted)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            await conn.execute(text("SELECT 2"))
        event.remove(engine.sync_engine, "before_cursor_execute", counted)
        return seen

    seen = on_async_engine(migrated, work)
    assert [s for s in seen if s.startswith("SELECT")] == ["SELECT 1", "SELECT 2"]


def _transient() -> OperationalError:
    return OperationalError("UPDATE …", {}, Exception(1213, "Deadlock found"))


def test_retrying_async_runs_a_transient_conflict_again_and_awaits_the_pause(
    migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    pauses: list[float] = []

    async def no_pause(seconds: float) -> None:
        pauses.append(seconds)

    monkeypatch.setattr("maity_hub.db.asyncio", SimpleNamespace(sleep=no_pause))
    attempts: list[int] = []

    async def flaky() -> str:
        attempts.append(1)
        if len(attempts) < 3:
            raise _transient()
        return "done"

    async def work(_engine: AsyncEngine) -> str:
        return await db.retrying_async(flaky)

    assert on_async_engine(migrated, work) == "done"
    assert len(attempts) == 3 and len(pauses) == 2


def test_retrying_async_gives_up_as_retrying_does(
    migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def no_pause(_seconds: float) -> None:
        return None

    monkeypatch.setattr("maity_hub.db.asyncio", SimpleNamespace(sleep=no_pause))
    attempts: list[int] = []

    async def always() -> None:
        attempts.append(1)
        raise _transient()

    async def other() -> None:
        attempts.append(1)
        raise OperationalError("SELECT …", {}, Exception(1146, "no such table"))

    async def work(_engine: AsyncEngine) -> list[int]:
        counts = []
        for call in (always, other):
            attempts.clear()
            with pytest.raises(OperationalError):
                await db.retrying_async(call)
            counts.append(len(attempts))
        return counts

    assert on_async_engine(migrated, work) == [db.RETRIES, 1]


def test_async_transaction_announces_after_the_commit_and_runs_its_steps_in_a_thread(
    migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    announced: list[tuple[str, int]] = []
    monkeypatch.setattr(events.notifier, "notify", lambda p, s: announced.append((p, s)))
    steps: list[str] = []

    def write(conn: Connection) -> None:
        conn.info[events._PENDING].append(("prj-1", 7))
        events.on_commit(conn, lambda: steps.append(threading.current_thread().name))
        assert announced == []  # not before the commit

    async def work(engine: AsyncEngine) -> None:
        async with events.async_transaction(engine) as conn:
            assert isinstance(conn, AsyncConnection)
            await conn.run_sync(write)
            assert events._PENDING in conn.info

    on_async_engine(migrated, work)
    assert announced == [("prj-1", 7)]
    assert len(steps) == 1 and steps[0] != threading.main_thread().name


def test_async_transaction_rolls_back_without_announcing_and_gives_back_in_a_thread(
    migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    announced: list[tuple[str, int]] = []
    monkeypatch.setattr(events.notifier, "notify", lambda p, s: announced.append((p, s)))
    undone: list[str] = []
    after: list[int] = []

    def write(conn: Connection) -> None:
        conn.info[events._PENDING].append(("prj-1", 8))
        events.on_rollback(conn, lambda: undone.append(threading.current_thread().name))
        events.on_commit(conn, lambda: after.append(1))
        raise RuntimeError("the write failed")

    async def work(engine: AsyncEngine) -> None:
        with pytest.raises(RuntimeError, match="the write failed"):
            async with events.async_transaction(engine) as conn:
                await conn.run_sync(write)

    on_async_engine(migrated, work)
    assert announced == [] and after == []
    assert len(undone) == 1 and undone[0] != threading.main_thread().name


def test_the_app_holds_an_async_engine_on_its_database_with_the_hooks(
    client: TestClient,
) -> None:
    app: Any = client.app
    async_engine: AsyncEngine = app.state.async_engine
    engine: Engine = app.state.engine
    assert async_engine.url.database == engine.url.database
    assert async_engine.sync_engine.dialect.name == engine.dialect.name
    for listener in (write_guard._before, timing._before):
        assert event.contains(async_engine.sync_engine, "before_cursor_execute", listener)


# A statement that runs for a few seconds on each engine, for a cancellation while the driver
# waits on it.
SLOW = {
    "sqlite": "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < 20000000)"
    " SELECT count(*) FROM c",
    "postgresql": "SELECT pg_sleep(5)",
    "mysql": "SELECT SLEEP(5)",
    "mariadb": "SELECT SLEEP(5)",
}


def test_a_request_cancelled_during_a_statement_ends_as_a_cancellation(
    migrated: Engine,
) -> None:
    """A request cancelled while its statement runs (a client gone, a server stopping) must end
    with `CancelledError`, which unwinds it: the driver invalidates the connection, and reading
    `conn.info` again at the end would ask SQLAlchemy to revalidate it inside the transaction,
    which raises `PendingRollbackError` in its place. The rate it counted is given back once and
    the connection returns to the pool."""
    undone: list[int] = []
    statement = SLOW[migrated.dialect.name]

    def slow(conn: Connection) -> None:
        events.on_rollback(conn, lambda: undone.append(1))
        conn.execute(text(statement))

    async def work(engine: AsyncEngine) -> tuple[str, int]:
        async def request() -> None:
            async with events.async_transaction(engine) as conn:
                await conn.run_sync(slow)

        task = asyncio.ensure_future(request())
        await asyncio.sleep(0.5)
        task.cancel()
        try:
            await task
            ended = "returned"
        except asyncio.CancelledError:
            ended = "cancelled"
        except BaseException as error:  # what replaced the cancellation
            ended = type(error).__name__
        pool: Any = engine.sync_engine.pool
        return ended, pool.checkedout()

    started = time.monotonic()
    assert on_async_engine(migrated, work) == ("cancelled", 0)
    assert undone == [1]
    assert time.monotonic() - started < 60


def test_a_call_authenticates_on_the_async_engine(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """PR 2: `deps._resolve` reads the session on the app's async engine (through `run_sync`),
    not on the sync engine in a thread of the pool."""
    owner = flow.human(make_client, migrated)
    app: Any = owner.client.app
    async_side: list[str] = []
    sync_side: list[str] = []

    def on(seen: list[str]) -> Any:
        def heard(_conn: Any, _cursor: Any, statement: str, *_: Any) -> None:
            if "human_session" in statement:
                seen.append(statement)

        return heard

    to_async, to_sync = on(async_side), on(sync_side)
    event.listen(app.state.async_engine.sync_engine, "before_cursor_execute", to_async)
    event.listen(app.state.engine, "before_cursor_execute", to_sync)
    try:
        assert owner.get("/me").status_code == 200
    finally:
        event.remove(app.state.async_engine.sync_engine, "before_cursor_execute", to_async)
        event.remove(app.state.engine, "before_cursor_execute", to_sync)
    assert async_side and not sync_side, (async_side, sync_side)
