"""Two real database connections in a fixed interleaving (shared by the race tests).

SQLite has one writer and serialises everything, so a race between two transactions
only shows on a server database: `race` skips on SQLite, and CI runs it on PostgreSQL
and MariaDB. A step that must wait for the other transaction runs in a thread on the
connection it names; `waiting` says it started and is still blocked, `finished` takes
its result. On the way out, whatever happened, the transactions no running step uses
roll back first, so that a step blocked on their locks is released before it is
joined; a step that still runs then fails the test, and its daemon thread never holds
the process open.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from concurrent.futures import Future
from concurrent.futures import wait as wait_for
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy import Connection, Engine

from maity_hub import events

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
    steps: list[Step] = field(default_factory=list)

    def run(self, conn: Connection, fn: Callable[[], Any]) -> Step:
        """Run `fn` in a daemon thread; it uses `conn` and no other connection. A daemon,
        so that a step stuck on a lock never keeps the test process from exiting."""
        started = threading.Event()
        future: Future[Any] = Future()

        def step() -> None:
            started.set()
            try:
                future.set_result(fn())
            except BaseException as error:  # handed to whoever takes the result
                future.set_exception(error)

        threading.Thread(target=step, name="maity-race-step", daemon=True).start()
        found = Step(future, started, conn)
        self.steps.append(found)
        return found


def _end(conn: Connection) -> None:
    """Roll back what is open and give the connection back to the pool clean: `info`
    belongs to the pooled connection and outlives `close`, so the event lists go, as
    `events.transaction` drops them."""
    try:
        if conn.in_transaction():
            conn.rollback()
    finally:
        conn.info.pop(events._PENDING, None)
        conn.info.pop(events._UNDO, None)
        conn.close()


@contextmanager
def race(engine: Engine) -> Iterator[Race]:
    """Two connections, each in its own open transaction; rolled back at the end unless
    the test committed them."""
    if engine.dialect.name == "sqlite":
        pytest.skip("a race needs two writers: PostgreSQL or MariaDB (CI)")
    first, second = engine.connect(), engine.connect()
    found = Race(first, second)
    for conn in (first, second):
        conn.begin()
        # What `events.transaction` gives a connection, so that the hub's code may emit
        # in it; the test commits by hand, and nobody is woken (no wake is under test).
        conn.info[events._PENDING] = []
        conn.info[events._UNDO] = []
    try:
        yield found
    finally:
        busy = {id(s.conn) for s in found.steps if not s.future.done()}
        rest = [c for c in (first, second) if id(c) in busy]
        for conn in (first, second):
            if id(conn) not in busy:
                _end(conn)  # releases the locks a running step may wait for
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
