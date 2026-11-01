"""Wake-ups across replicas on PostgreSQL (hub/context/replicas.md 387c2409).

`events.emit` adds `pg_notify('maity_events', '<project_id>:<seq>')` to the writing transaction;
PostgreSQL delivers it at commit. Each process holds one connection outside the pool that runs
`LISTEN maity_events` in a thread and hands every wake-up to the notifier, as a commit in this
process does, so a long-poll on one replica wakes when another writes. The same connection
listens on `maity_supersede`: a wait that opens announces itself there (`opened`), and a replica
holding an older wait of the same key ends it as superseded (§8.3, point 3 of 387c2409).
When that connection drops, every waiter reads once (spread over `RESPREAD_SECONDS`), since
what was announced meanwhile is lost, and the listener connects again with a growing pause.
The long-poll's 2-second fallback read stays as the safety net. SQLite and MariaDB run one
replica and have no listener.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import Connection, Engine, func, select
from starlette.concurrency import run_in_threadpool

from maity_hub import events, longpoll
from maity_hub.db import make_listener_engine

log = logging.getLogger(__name__)

POLL_SECONDS = 1.0  # how often the listening thread looks whether it should stop
RESPREAD_SECONDS = 2.0  # the waiters' reads after a lost connection, spread over this
BACKOFF_FIRST, BACKOFF_MAX = 1.0, 30.0  # the pause before connecting again, doubling
SUPERSEDE = "maity_supersede"  # `<sha256 of kind:key>:<start in µs on the database clock>`
# `<sha256 of kind:key>`: what a held bell or device-code wait shows changed (point 5).
RINGS = {"bell": "maity_bell", "device": "maity_device"}
FALLBACK_SECONDS = 2.0  # a rung wait looks again at the latest after this, as the events do
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# The waits this process holds, by the hash of their kind and key: per wait its start on the
# database clock and what ends it.
_held: dict[str, dict[object, tuple[int, Callable[[], None]]]] = {}
_held_lock = threading.Lock()


def _digest(kind: str, key: str) -> str:
    """Only the hash goes through the channel, never a credential or session id."""
    return hashlib.sha256(f"{kind}:{key}".encode()).hexdigest()


def _forget(digest: str, token: object) -> None:
    with _held_lock:
        waits = _held.get(digest)
        if waits is not None:
            waits.pop(token, None)
            if not waits:
                del _held[digest]


def _announce(engine: Engine, digest: str, token: object, end: Callable[[], None]) -> None:
    """Tell every replica a wait opens now, its start read from the database's clock, which
    every replica shares, unlike their own. The wait is held from the moment its start is
    known, before the notice commits: a newer wait's notice arriving right after the commit
    finds it (c47w at #877), and its own notice ends nothing, not being older."""
    try:
        with engine.begin() as conn:
            now = conn.execute(select(func.clock_timestamp())).scalar_one()
            started = int((now - _EPOCH) // timedelta(microseconds=1))
            with _held_lock:
                _held.setdefault(digest, {})[token] = (started, end)
            conn.execute(select(func.pg_notify(SUPERSEDE, f"{digest}:{started}")))
    except BaseException:
        _forget(digest, token)
        raise


async def opened(
    engine: Engine, kind: str, key: str, on_superseded: Callable[[], None]
) -> Callable[[], None]:
    """A wait of `kind` and `key` opens: on PostgreSQL announce it, and end it with
    `on_superseded` when a newer one of the same key opens on another replica, which may
    happen before this returns: the caller holds the wait before it calls, or, like the event
    routes, keeps a flag that `on_superseded` sets and checks it first. Returns what
    the wait calls when it closes. Superseding inside the process stays the caller's."""
    if engine.dialect.name != "postgresql":
        return lambda: None
    digest, token = _digest(kind, key), object()
    await run_in_threadpool(_announce, engine, digest, token, on_superseded)
    return lambda: _forget(digest, token)


# --- the bell and the device codes (point 5) ------------------------------------------------

_rings: dict[str, set[Callable[[], None]]] = {}


def ring(conn: Connection, kind: str, key: str) -> None:
    """In the caller's transaction: on PostgreSQL, wake every held `kind` wait of `key` at
    commit, on every replica this one included. Elsewhere those waits poll."""
    if conn.dialect.name == "postgresql":
        conn.execute(select(func.pg_notify(RINGS[kind], _digest(kind, key))))


def rung(payload: str) -> None:
    with _held_lock:
        wakes = list(_rings.get(payload, ()))
    for wake in wakes:
        wake()


@dataclass
class Held:
    """What a held bell or device-code wait waits on between two looks: on PostgreSQL its
    ring, an event in `project_ids` and the fallback; elsewhere the old poll."""

    poll: float
    waiter: longpoll.Waiter | None = None
    digest: str = ""
    _wake: Callable[[], None] = field(default=lambda: None)

    async def pause(self, remaining: float) -> None:
        if self.waiter is None:
            await asyncio.sleep(max(0.0, min(self.poll, remaining)))
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(
                self.waiter.event.wait(), max(0.0, min(FALLBACK_SECONDS, remaining))
            )
        self.waiter.event.clear()  # what rings from here on wakes the next pause

    def wake(self) -> None:
        if self.waiter is not None:
            self.waiter.wake()

    def close(self) -> None:
        if self.waiter is None:
            return
        with _held_lock:
            wakes = _rings.get(self.digest)
            if wakes is not None:
                wakes.discard(self._wake)
                if not wakes:
                    del _rings[self.digest]
        longpoll.registry.leave(self.waiter)


def held(
    engine: Engine,
    kind: str,
    *,
    wait_key: str,
    ring_key: str,
    poll: float,
    project_ids: frozenset[str] = frozenset(),
) -> Held:
    """Hold a bell or device-code wait (`wait_key`, one per key as before), woken by `ring`
    of `ring_key` and by every event in `project_ids`. A newer wait of the same key in this
    process wakes the older one at once."""
    if engine.dialect.name != "postgresql":
        return Held(poll)
    waiter = longpoll.Waiter(
        key=f"{kind}:{wait_key}",
        project_id=None,
        session_id=None,
        loop=asyncio.get_running_loop(),
        project_ids=project_ids,
    )
    longpoll.registry.enter(waiter)
    digest = _digest(kind, ring_key)
    with _held_lock:
        _rings.setdefault(digest, set()).add(waiter.wake)
    return Held(poll, waiter, digest, waiter.wake)


def supersede(payload: str) -> None:
    """A wait opened somewhere: every wait of the same key here that started before it ends.
    This process's own announcement comes back too and ends nothing (it is not older)."""
    digest, _, started = payload.rpartition(":")
    if not digest or not started.isdigit():
        log.warning("a supersede notice that is not <hash>:<start> was ignored")
        return
    with _held_lock:
        older = [
            (token, end)
            for token, (begun, end) in _held.get(digest, {}).items()
            if begun < int(started)
        ]
        for token, _ in older:
            _held[digest].pop(token, None)
    for _, end in older:
        end()


def handle(payload: str) -> None:
    """One wake-up: `<project_id>:<seq>`; anything else is ignored."""
    project_id, _, seq = payload.rpartition(":")
    if not project_id or not seq.isdigit():
        log.warning("a wake-up that is not <project>:<seq> was ignored")
        return
    events.notifier.notify_from_elsewhere(project_id, int(seq))


class Listener:
    def __init__(self, url: str) -> None:
        self._engine: Engine = make_listener_engine(url)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.listening = threading.Event()  # set while `LISTEN` is in effect

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="maity-wakeups", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=POLL_SECONDS * 5)
        self._engine.dispose()

    def _run(self) -> None:
        pause, again = BACKOFF_FIRST, False
        while not self._stop.is_set():
            try:
                self._listen(catch_up=again)
            except Exception:
                log.warning("the wake-up listener has no connection; connecting again")
            again = True
            if self.listening.is_set():  # it was up: the first try again comes soon
                self.listening.clear()
                pause = BACKOFF_FIRST
            self._stop.wait(pause)
            pause = min(pause * 2, BACKOFF_MAX)

    def _listen(self, *, catch_up: bool) -> None:
        raw = self._engine.raw_connection()
        try:
            conn = raw.driver_connection
            if conn is None:
                raise RuntimeError("the listener's connection has no driver connection")
            conn.autocommit = True
            conn.execute(f"LISTEN {events.CHANNEL}")
            conn.execute(f"LISTEN {SUPERSEDE}")
            for channel in RINGS.values():
                conn.execute(f"LISTEN {channel}")
            self.listening.set()
            if catch_up:
                # What was announced while nobody listened is lost: every waiter reads once.
                longpoll.registry.wake_all(spread=RESPREAD_SECONDS)
            while not self._stop.is_set():
                for note in conn.notifies(timeout=POLL_SECONDS):
                    if note.channel == SUPERSEDE:
                        supersede(note.payload)
                    elif note.channel in RINGS.values():
                        rung(note.payload)
                    else:
                        handle(note.payload)
        finally:
            raw.close()
