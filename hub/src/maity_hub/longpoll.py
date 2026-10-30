"""Who waits for events right now, and how they are woken (hub/context/events.md).

One waiter per credential (or per dashboard session): a second long-poll of
the same key supersedes the first (docs/api.md §8.3). Waiters wait on an
`asyncio.Event` in the loop that serves them; the notifier of
`maity_hub.events` calls in from whatever thread committed, so the wake
goes through `call_soon_threadsafe`.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field

from maity_hub import events, listening


@dataclass(eq=False)
class Waiter:
    key: str
    project_id: str | None
    session_id: str | None
    loop: asyncio.AbstractEventLoop
    event: asyncio.Event = field(default_factory=asyncio.Event)
    superseded: bool = False
    # Set when the agent's membership was isolated: the wait ends at once (§6.2).
    ended: bool = False
    membership_id: int | None = None
    # A runner's waiter reads several projects (docs/api.md §15.8); the reader
    # replaces the set on every pass, an assignment the notifier reads atomically.
    project_ids: frozenset[str] = frozenset()

    def wake(self) -> None:
        self.loop.call_soon_threadsafe(self.event.set)


class Registry:
    def __init__(self) -> None:
        self._by_key: dict[str, Waiter] = {}
        self._lock = threading.Lock()

    def enter(self, waiter: Waiter) -> None:
        with self._lock:
            previous = self._by_key.get(waiter.key)
            self._by_key[waiter.key] = waiter
        if previous is not None:
            previous.superseded = True
            previous.wake()
        if waiter.session_id:
            listening.opened(waiter.session_id)

    def leave(self, waiter: Waiter) -> None:
        with self._lock:
            if self._by_key.get(waiter.key) is waiter:
                del self._by_key[waiter.key]
        if waiter.session_id:
            listening.closed(waiter.session_id)

    def notify(self, project_id: str, _seq: int) -> None:
        with self._lock:
            waiting = [
                w
                for w in self._by_key.values()
                if w.project_id == project_id or project_id in w.project_ids
            ]
        for waiter in waiting:
            waiter.wake()

    def end(self, membership_id: int) -> None:
        """End every open wait of an isolated agent's credentials (§6.2, "Isolation")."""
        with self._lock:
            waiting = [w for w in self._by_key.values() if w.membership_id == membership_id]
        for waiter in waiting:
            waiter.ended = True
            waiter.wake()

    def wake_all(self) -> None:
        with self._lock:
            waiting = list(self._by_key.values())
        for waiter in waiting:
            waiter.wake()

    def __len__(self) -> int:
        with self._lock:
            return len(self._by_key)


registry = Registry()
events.notifier.subscribe(registry.notify)

# Set when the process is told to stop: every long-poll answers at once with what it has,
# so a restart does not wait out the open waits (hub/context/kubernetes.md).
stopping = threading.Event()


def begin_shutdown() -> None:
    stopping.set()
    registry.wake_all()
