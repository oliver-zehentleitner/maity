"""Two real database connections in a fixed interleaving (shared by the race tests).

SQLite has one writer and serialises everything, so a race between two transactions
only shows on a server database: the helpers skip on SQLite, and CI runs them on
PostgreSQL and MariaDB. A step that must wait for the other transaction runs in a
thread; `waiting` says it is still blocked, `finished` takes its result.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from typing import Any

import pytest
from sqlalchemy import Connection, Engine

BLOCKED_FOR = 0.5  # seconds a blocked step must stay blocked to count as waiting
FINISH_WITHIN = 10.0  # seconds a released step may take


def require_server(engine: Engine) -> None:
    if engine.dialect.name == "sqlite":
        pytest.skip("a race needs two writers: PostgreSQL or MariaDB (CI)")


@contextmanager
def two_transactions(engine: Engine) -> Iterator[tuple[Connection, Connection]]:
    """Two connections, each in its own open transaction; both rolled back at the end
    unless the test commits them."""
    require_server(engine)
    first, second = engine.connect(), engine.connect()
    try:
        first.begin()
        second.begin()
        yield first, second
    finally:
        for conn in (first, second):
            if conn.in_transaction():
                conn.rollback()
            conn.close()


@contextmanager
def background() -> Iterator[Callable[[Callable[[], Any]], Future[Any]]]:
    """Run steps in a thread of their own, so that one may block on the other."""
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        yield pool.submit
    finally:
        pool.shutdown(wait=True, cancel_futures=True)


def waiting(step: Future[Any]) -> bool:
    """The step is still blocked after `BLOCKED_FOR` seconds."""
    try:
        step.result(timeout=BLOCKED_FOR)
    except TimeoutError:
        return True
    return False


def finished[T](step: Future[T]) -> T:
    return step.result(timeout=FINISH_WITHIN)
