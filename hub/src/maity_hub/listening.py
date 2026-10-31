"""Which sessions hold an open events long-poll right now (docs/api.md §5.3, §8.3).

On PostgreSQL every replica's waits are rows of `long_poll` (hub/context/replicas.md 387c2409,
point 4): a wait's row is inserted when it opens and deleted by its own `wait_id` when it closes,
so two waits of one key never remove each other's. Each process refreshes its `hub_pod` row
every `HEARTBEAT`; a wait whose pod has not been seen for `STALE` does not count, and the next
heartbeat of any pod removes it. The writes go through one thread per process, so opening a wait
never waits for the database; this process's own waits count at once, from memory. The same
heartbeat rewrites this process's rows when they are missing (the tables are UNLOGGED: a crash
or a failover empties them while the waits go on). Elsewhere, and before `start`, the registry
stays in the process.
"""

from __future__ import annotations

import logging
import queue
import secrets
import socket
import threading
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Connection,
    Engine,
    delete,
    func,
    insert,
    literal_column,
    select,
)
from sqlalchemy.dialects import postgresql

from maity_hub import tables as t
from maity_hub import write_guard

log = logging.getLogger(__name__)

POD = f"{socket.gethostname()[:40]}-{secrets.token_hex(4)}"  # this process, in `hub_pod`
HEARTBEAT = timedelta(seconds=15)
STALE = timedelta(seconds=45)  # three heartbeats missed: the pod is gone
# Every moment of the registry is the database's (c47w at #903): pods whose clocks differ by
# more than a heartbeat would otherwise count each other as gone.
_STALE_SQL: ColumnElement[Any] = literal_column(f"interval '{int(STALE.total_seconds())} seconds'")
# The columns hold UTC without a zone (`UtcDateTime`): the database's `now()` compared with them
# must be taken in UTC, or a server not on UTC shifts it by its offset.
_DB_NOW: ColumnElement[Any] = func.timezone("UTC", func.now())

_open: dict[str, int] = {}  # this process's open waits per key
_rows: dict[str, str] = {}  # this process's waits as they should stand in `long_poll`
_lock = threading.Lock()
_engine: list[Engine | None] = [None]
_writes: queue.Queue[tuple[str, str, str] | None] = queue.Queue()
_thread: list[threading.Thread | None] = [None]
_starts = [0]  # apps that started the registry in this process and have not stopped it


def _now() -> datetime:
    return datetime.now(UTC)


def which(keys: Iterable[str], conn: Connection | None = None) -> set[str]:
    """The keys among `keys` that hold an open wait on any live replica, in one read."""
    wanted = list(dict.fromkeys(keys))
    with _lock:
        found = {key for key in wanted if _open.get(key, 0) > 0}
    rest = [key for key in wanted if key not in found]
    engine = _engine[0]
    if engine is None or not rest:
        return found
    w, p = t.long_poll.c, t.hub_pod.c
    query = (
        select(w.listening_key)
        .join(t.hub_pod, p.pod == w.pod)
        .where(w.listening_key.in_(rest), p.seen_at > _DB_NOW - _STALE_SQL)
        .distinct()
    )
    if conn is not None:
        return found | set(conn.execute(query).scalars())
    with engine.connect() as own:
        return found | set(own.execute(query).scalars())


def is_listening(key: str, conn: Connection | None = None) -> bool:
    return key in which([key], conn)


def opened(key: str) -> str:
    """A wait of `key` opens; the token `closed` takes."""
    wait_id = secrets.token_hex(16)
    with _lock:
        _open[key] = _open.get(key, 0) + 1
        if _engine[0] is not None:
            _rows[wait_id] = key
            _writes.put(("open", wait_id, key))
    return wait_id


def closed(key: str, wait_id: str) -> None:
    with _lock:
        remaining = _open.get(key, 0) - 1
        if remaining > 0:
            _open[key] = remaining
        else:
            _open.pop(key, None)
        if _rows.pop(wait_id, None) is not None:
            _writes.put(("close", wait_id, key))


def reset() -> None:
    """Forget every wait of this process, in memory and, once what was queued is written, in
    the database: a test that makes an agent stop listening."""
    with _lock:
        _open.clear()
        _rows.clear()
    engine = _engine[0]
    if engine is None:
        return
    _writes.join()
    with engine.begin() as conn:
        write_guard.exempt(conn)
        conn.execute(delete(t.long_poll).where(t.long_poll.c.pod == POD))


# --- the writer and the heartbeat (PostgreSQL) ----------------------------------------------


def start(engine: Engine) -> None:
    """Share the registry through `engine` when it is PostgreSQL, from now on. One writer per
    process, however many apps start it (the tests start one per client): the last `stop`
    ends it."""
    if engine.dialect.name != "postgresql":
        return
    with _lock:
        _starts[0] += 1
        if _engine[0] is not None:
            return
        _engine[0] = engine
    _heartbeat(engine)
    thread = threading.Thread(target=_write, args=(engine,), name="maity-listening", daemon=True)
    _thread[0] = thread
    thread.start()


def stop(*, every: bool = False) -> None:
    """One app stops; with the last (or `every`, between tests) this process leaves the
    registry: its waits and its pod row."""
    with _lock:
        _starts[0] = 0 if every else max(0, _starts[0] - 1)
        if _starts[0] > 0:
            return
    engine, thread = _engine[0], _thread[0]
    if engine is None:
        return
    _writes.put(None)
    if thread is not None:
        thread.join(timeout=5)
    _engine[0], _thread[0] = None, None
    with _lock:
        _rows.clear()
    try:
        with engine.begin() as conn:
            write_guard.exempt(conn)
            conn.execute(delete(t.long_poll).where(t.long_poll.c.pod == POD))
            conn.execute(delete(t.hub_pod).where(t.hub_pod.c.pod == POD))
    except Exception:
        log.warning("the listening registry could not remove this process's rows")


def _write(engine: Engine) -> None:
    due = _now() + HEARTBEAT  # when the next heartbeat is owed, on this process's clock
    while True:
        try:
            item = _writes.get(timeout=max(0.0, (due - _now()).total_seconds()))
            queued = True
        except queue.Empty:
            item, queued = ("beat", "", ""), False
        beat = item is not None and (item[0] == "beat" or _now() >= due)
        if beat:
            # Owed again a whole interval from now, whether this one succeeds or not: with the
            # database gone (a failover) a failed beat must not be retried at once, on every pod.
            due = _now() + HEARTBEAT
        try:
            if item is None:
                return
            if beat:
                _heartbeat(engine)
            if item[0] in ("open", "close"):
                _apply(engine, *item)
        except Exception:
            log.warning("the listening registry could not write; the heartbeat retries")
        finally:
            if queued:
                _writes.task_done()  # `reset` waits until what was queued is written


def _apply(engine: Engine, kind: str, wait_id: str, key: str) -> None:
    with engine.begin() as conn:
        write_guard.exempt(conn)  # the registry is no write of an account
        if kind == "open":
            conn.execute(
                postgresql.insert(t.long_poll)
                .values(wait_id=wait_id, listening_key=key, pod=POD, opened_at=_DB_NOW)
                .on_conflict_do_nothing()
            )
        else:
            conn.execute(delete(t.long_poll).where(t.long_poll.c.wait_id == wait_id))


def _heartbeat(engine: Engine) -> None:
    """This pod is alive; the waits of pods gone longer than `STALE` go; this pod's own rows
    are written again when what the table holds differs from what is open here (the same
    `wait_id`s, not merely as many: a lost open and a lost close would cancel out)."""
    w, p = t.long_poll.c, t.hub_pod.c
    with engine.begin() as conn:
        write_guard.exempt(conn)  # the registry is no write of an account
        # `now()` itself, aware, not `_DB_NOW`: bound back into `UtcDateTime` it is turned into
        # UTC once; `_DB_NOW` is already UTC without a zone and is for comparisons in SQL.
        now = conn.execute(select(func.now())).scalar_one()
        statement = postgresql.insert(t.hub_pod).values(pod=POD, seen_at=now)
        conn.execute(statement.on_conflict_do_update(index_elements=["pod"], set_={"seen_at": now}))
        gone = select(p.pod).where(p.seen_at <= now - STALE).scalar_subquery()
        conn.execute(delete(t.long_poll).where(w.pod.in_(gone)))
        conn.execute(delete(t.hub_pod).where(p.seen_at <= now - STALE))
        with _lock:
            expected = dict(_rows)
        held = set(conn.execute(select(w.wait_id).where(w.pod == POD)).scalars())
        if held != set(expected):
            conn.execute(delete(t.long_poll).where(w.pod == POD))
            if expected:
                conn.execute(
                    insert(t.long_poll),
                    [
                        {"wait_id": wait_id, "listening_key": key, "pod": POD, "opened_at": now}
                        for wait_id, key in expected.items()
                    ],
                )
