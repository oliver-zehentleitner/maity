"""Two real database connections in a fixed interleaving (shared by the race tests).

SQLite has one writer and serialises everything, so a race between two transactions
only shows on a server database: `race` skips on SQLite, and CI runs it on PostgreSQL
and MariaDB. A step that must wait for the other transaction runs in a thread on the
connection it names; `waiting` says it started and is still blocked, `finished` takes
its result. On the way out, whatever happened, the transactions no running step uses
roll back first, so that a step blocked on their locks is released before it is
joined; a step that still runs then fails the test instead of hanging it.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import wait as wait_for
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy import Connection, Engine

BLOCKED_FOR = 0.5  # seconds a blocked step must stay blocked to count as waiting
FINISH_WITHIN = 10.0  # seconds a released step may take


@dataclass
class Step:
    """A step running in its own thread. `started` is set right before its first
    statement, so that `waiting` measures the database, not the thread's start."""

    future: Future[Any]
    started: threading.Event
    conn: Connection


@dataclass
class Race:
    first: Connection
    second: Connection
    _pool: ThreadPoolExecutor
    steps: list[Step] = field(default_factory=list)

    def run(self, conn: Connection, fn: Callable[[], Any]) -> Step:
        """Run `fn` in a thread; it uses `conn` and no other connection."""
        started = threading.Event()

        def step() -> Any:
            started.set()
            return fn()

        found = Step(self._pool.submit(step), started, conn)
        self.steps.append(found)
        return found


def _end(conn: Connection) -> None:
    if conn.in_transaction():
        conn.rollback()
    conn.close()


@contextmanager
def race(engine: Engine) -> Iterator[Race]:
    """Two connections, each in its own open transaction; rolled back at the end unless
    the test committed them."""
    if engine.dialect.name == "sqlite":
        pytest.skip("a race needs two writers: PostgreSQL or MariaDB (CI)")
    first, second = engine.connect(), engine.connect()
    pool = ThreadPoolExecutor(max_workers=2)
    found = Race(first, second, pool)
    first.begin()
    second.begin()
    try:
        yield found
    finally:
        busy = {id(s.conn) for s in found.steps if not s.future.done()}
        rest = [c for c in (first, second) if id(c) in busy]
        for conn in (first, second):
            if id(conn) not in busy:
                _end(conn)  # releases the locks a running step may wait for
        pool.shutdown(wait=False, cancel_futures=True)
        _, running = wait_for([s.future for s in found.steps], timeout=FINISH_WITHIN)
        for conn in rest:
            if not running:
                _end(conn)
        if running:
            raise AssertionError("a race step still runs after the other side rolled back")


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
