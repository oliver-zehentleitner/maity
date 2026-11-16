"""Counting the statements a call sends to the database, for the tests that say a cost does
not grow with the data (the chat lists, a human's sign-in).

A call counts on `engine` and on every async engine on the same database: an app authenticates
on its async engine (`deps._resolve`), whose statements run on that engine's `sync_engine`. The
listener hangs on the `Engine` class for the call, so it reaches the app's async engine without
the test naming it; the hub's other engines (shared counters, health) are sync and not counted,
as before.

Only the call's own statements count: those sent while a context variable that the block sets
is in force. A test client's request runs with the context of the thread that sends it (the
portal's task copies it), and so does every thread or task the request hands work to
(`run_in_threadpool`, `anyio.to_thread`, `asyncio.create_task`, the async engine's greenlet).
The app's background workers run on threads started before the block, with no such context, so
a tick of theirs during the call is not counted (tsk-dbnh1nhcjrc4; `hub/context/tests.md`).
A test that starts its own threads in the call hands each a `contextvars.copy_context()`."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from sqlalchemy import Engine, event
from sqlalchemy.engine import URL

# The block being counted, as the context its statements run in sees it; None outside one.
_measured: ContextVar[object | None] = ContextVar("measured_call", default=None)


def _database(url: URL) -> tuple[Any, ...]:
    return (url.get_backend_name(), url.host, url.port, url.database)


@contextmanager
def listening(
    engine: Engine, listener: Callable[..., None], async_engines: bool = True
) -> Iterator[None]:
    """`listener` on `before_cursor_execute` of `engine` and, with `async_engines`, of every
    async engine on its database (an app's, where its calls authenticate), for the statements
    the block itself sends while it runs: not those of the app's background workers."""
    database = _database(engine.url)
    block = object()

    def heard(conn: Any, *args: Any) -> None:
        if _measured.get() is not block:
            return  # another thread's work, not the call's
        on = conn.engine
        if on is engine or (
            async_engines and on.dialect.is_async and _database(on.url) == database
        ):
            listener(conn, *args)

    entered = _measured.set(block)
    event.listen(Engine, "before_cursor_execute", heard)
    try:
        yield
    finally:
        event.remove(Engine, "before_cursor_execute", heard)
        _measured.reset(entered)


def _counting(
    engine: Engine, count: Callable[..., None], call: Any, async_engines: bool = True
) -> None:
    with listening(engine, count, async_engines):
        call()


def count_statements(engine: Engine, call: Any, async_engines: bool = True) -> int:
    """The statements `call` sends; without `async_engines` only those on `engine` itself
    (not the authentication's, whose presence write comes once a minute, `seen.SEEN_EVERY`)."""
    seen = [0]

    def counted(*_: Any) -> None:
        seen[0] += 1

    _counting(engine, counted, call, async_engines)
    return seen[0]


def count_executions(engine: Engine, call: Any) -> int:
    """Like `count_statements`, but a list of parameters (`executemany`) counts once per row,
    as sqlite3 and psycopg run it: one INSERT with many VALUES rows counts once. A driver that
    folds an INSERT's parameter list into one statement (PyMySQL) runs fewer than this counts;
    the rule is the conservative one, so a regression to a parameter list fails the test."""
    seen = [0]

    def counted(
        conn: Any, cursor: Any, statement: Any, parameters: Any, context: Any, many: bool
    ) -> None:
        seen[0] += len(parameters) if many else 1

    _counting(engine, counted, call)
    return seen[0]
