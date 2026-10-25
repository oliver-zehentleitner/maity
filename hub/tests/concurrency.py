"""Two real database connections in a fixed interleaving (shared by the race tests).

SQLite has one writer and serialises everything, so a race between two transactions
only shows on a server database: the helpers skip on SQLite, and CI runs them on
PostgreSQL and MariaDB. A step that must wait for the other transaction runs in a
thread; `waiting` says it started and is still blocked, `finished` takes its result.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
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


@dataclass
class Step:
    """A step running in its own thread. `started` is set right before its first
    statement, so that `waiting` measures the database, not the thread's start."""

    future: Future[Any]
    started: threading.Event


@contextmanager
def background() -> Iterator[Callable[[Callable[[], Any]], Step]]:
    """Run steps in a thread of their own, so that one may block on the other."""
    pool = ThreadPoolExecutor(max_workers=2)

    def run(fn: Callable[[], Any]) -> Step:
        started = threading.Event()

        def step() -> Any:
            started.set()
            return fn()

        return Step(pool.submit(step), started)

    try:
        yield run
    finally:
        pool.shutdown(wait=True, cancel_futures=True)


def waiting(step: Step) -> bool:
    """The step began and is still blocked `BLOCKED_FOR` seconds later."""
    assert step.started.wait(FINISH_WITHIN), "the step never started"
    try:
        step.future.result(timeout=BLOCKED_FOR)
    except TimeoutError:
        return True
    return False


def finished(step: Step) -> Any:
    return step.future.result(timeout=FINISH_WITHIN)
