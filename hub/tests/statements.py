"""Counting the statements a call sends to the database, for the tests that say a cost does
not grow with the data (the chat lists, a human's sign-in).

A call counts on `engine` and on every async engine on the same database: an app authenticates
on its async engine (`deps._resolve`), whose statements run on that engine's `sync_engine`. The
listener hangs on the `Engine` class for the call, so it reaches the app's async engine without
the test naming it; the hub's other engines (shared counters, health) are sync and not counted,
as before."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, event
from sqlalchemy.engine import URL


def _database(url: URL) -> tuple[Any, ...]:
    return (url.get_backend_name(), url.host, url.port, url.database)


@contextmanager
def listening(engine: Engine, listener: Callable[..., None]) -> Iterator[None]:
    """`listener` on `before_cursor_execute` of `engine` and of every async engine on its
    database (an app's, where its calls authenticate) while the block runs."""
    database = _database(engine.url)

    def heard(conn: Any, *args: Any) -> None:
        on = conn.engine
        if on is engine or (on.dialect.is_async and _database(on.url) == database):
            listener(conn, *args)

    event.listen(Engine, "before_cursor_execute", heard)
    try:
        yield
    finally:
        event.remove(Engine, "before_cursor_execute", heard)


def _counting(engine: Engine, count: Callable[..., None], call: Any) -> None:
    with listening(engine, count):
        call()


def count_statements(engine: Engine, call: Any) -> int:
    seen = [0]

    def counted(*_: Any) -> None:
        seen[0] += 1

    _counting(engine, counted, call)
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
