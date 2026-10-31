"""Wake-ups across replicas on PostgreSQL (hub/context/replicas.md 387c2409).

`events.emit` adds `pg_notify('maity_events', '<project_id>:<seq>')` to the writing transaction;
PostgreSQL delivers it at commit. Each process holds one connection outside the pool that runs
`LISTEN maity_events` in a thread and hands every wake-up to the notifier, as a commit in this
process does, so a long-poll on one replica wakes when another writes. When that connection
drops, every waiter reads once (spread over `RESPREAD_SECONDS`), since what was announced
meanwhile is lost, and the listener connects again with a growing pause. The long-poll's
2-second fallback read stays as the safety net. SQLite and MariaDB run one replica and have
no listener.
"""

from __future__ import annotations

import logging
import threading

from sqlalchemy import Engine

from maity_hub import events, longpoll
from maity_hub.db import make_listener_engine

log = logging.getLogger(__name__)

POLL_SECONDS = 1.0  # how often the listening thread looks whether it should stop
RESPREAD_SECONDS = 2.0  # the waiters' reads after a lost connection, spread over this
BACKOFF_FIRST, BACKOFF_MAX = 1.0, 30.0  # the pause before connecting again, doubling


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
            self.listening.set()
            if catch_up:
                # What was announced while nobody listened is lost: every waiter reads once.
                longpoll.registry.wake_all(spread=RESPREAD_SECONDS)
            while not self._stop.is_set():
                for note in conn.notifies(timeout=POLL_SECONDS):
                    handle(note.payload)
        finally:
            raw.close()
