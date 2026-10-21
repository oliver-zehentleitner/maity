"""Writing events (docs/api.md §8, docs/architecture.md §7).

Writers serialise per project on the project row, so that a lower `seq`
never becomes visible after a higher one and a cursor never skips an
event. Every write that emits runs in `transaction()`, which signals the
waiters after the transaction committed, never before: a woken reader
must find the row.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, Engine, insert, select

from maity_hub import clock
from maity_hub import tables as t

_PENDING = "maity_pending_events"


@dataclass(frozen=True)
class Actor:
    membership_id: int
    session_id: str | None = None
    credential_id: str | None = None
    via: str | None = None  # signed, bearer, cookie
    harness: str | None = None
    model: str | None = None


class Notifier:
    """Post-commit fan-out of new events to whoever waits on a project.

    Listeners are called from the committing thread; the long-poll
    (slice 5) registers one that wakes its asyncio waiters thread-safely.
    """

    def __init__(self) -> None:
        self._listeners: list[Callable[[str, int], None]] = []
        self._lock = threading.Lock()

    def subscribe(self, listener: Callable[[str, int], None]) -> Callable[[], None]:
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                self._listeners.remove(listener)

        return unsubscribe

    def notify(self, project_id: str, seq: int) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            listener(project_id, seq)


notifier = Notifier()


@contextmanager
def transaction(engine: Engine) -> Iterator[Connection]:
    """`engine.begin()` that announces the events it wrote once they are committed.

    SQLAlchemy's `commit` event fires before the database has committed, so
    a waiter woken there could read before the row is visible; the
    announcement waits until `begin()` has returned cleanly.
    """
    pending: list[tuple[str, int]] = []
    with engine.begin() as conn:
        conn.info[_PENDING] = pending
        try:
            yield conn
        finally:
            conn.info.pop(_PENDING, None)
    for project_id, seq in pending:
        notifier.notify(project_id, seq)


def lock_project(conn: Connection, project_id: str) -> None:
    """`SELECT … FOR UPDATE` on the project row; SQLite's single writer serialises anyway."""
    conn.execute(select(t.project.c.id).where(t.project.c.id == project_id).with_for_update())


def emit(
    conn: Connection,
    project_id: str,
    kind: str,
    audience: list[str],
    payload: dict[str, Any],
    *,
    actor: Actor | None = None,
    subject: tuple[str, str] | None = None,
    conversation_id: str | None = None,
) -> int:
    """Append one event inside the caller's transaction; returns its `seq`."""
    lock_project(conn, project_id)
    result = conn.execute(
        insert(t.event).values(
            project_id=project_id,
            kind=kind,
            at=clock.now(),
            actor_membership=actor.membership_id if actor else None,
            actor_session_id=actor.session_id if actor else None,
            actor_credential_id=actor.credential_id if actor else None,
            actor_via=actor.via if actor else None,
            actor_harness=actor.harness if actor else None,
            actor_model=actor.model if actor else None,
            subject_type=subject[0] if subject else None,
            subject_id=subject[1] if subject else None,
            audience=audience,
            conversation_id=conversation_id,
            payload=payload,
            redacted=False,
        )
    )
    key = result.inserted_primary_key
    if key is None:
        raise RuntimeError("the event insert returned no seq")
    seq = int(key[0])
    pending = conn.info.get(_PENDING)
    if pending is None:
        raise RuntimeError("events.emit outside events.transaction(): nobody would be woken")
    pending.append((project_id, seq))
    return seq
