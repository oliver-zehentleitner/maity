"""One pass of a worker per interval, whichever pod is first (hub/context/replicas.md 24489a9c).

Every worker keeps running in every pod, so any pod can take over at once; before a pass it
claims the pass in its `worker_run` row, with one compare-and-set on the database's clock. The
claim is about cost, not correctness: the workers settle under row locks, and two pods running
the same pass do no harm beyond the work. Only PostgreSQL runs replicas, so every other database
claims nothing and writes nothing.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Protocol

from sqlalchemy import Engine, update
from sqlalchemy.dialects import postgresql

from maity_hub import listening
from maity_hub import tables as t

log = logging.getLogger(__name__)

LEASE = timedelta(minutes=5)
RENEW_EVERY = 60.0  # seconds; well inside the lease, so one slow step does not lose it


class Stopping(Protocol):
    """What a pass asks between two of its steps; a `threading.Event` will do."""

    def is_set(self) -> bool: ...


def _take(engine: Engine, name: str, interval: float, pod: str) -> bool:
    now = listening._DB_NOW
    r = t.worker_run.c
    with engine.begin() as conn:
        taken = conn.execute(
            update(t.worker_run)
            .where(
                r.name == name,
                r.started_at <= now - timedelta(seconds=interval),
                r.lease_until < now,
            )
            .values(started_at=now, pod=pod, lease_until=now + LEASE)
            .returning(r.name)
        ).first()
        if taken is None:  # RETURNING, not `rowcount`: as in `auth.nonces`
            taken = conn.execute(
                postgresql.insert(t.worker_run)
                .values(name=name, started_at=now, pod=pod, lease_until=now + LEASE)
                .on_conflict_do_nothing()
                .returning(t.worker_run.c.name)
            ).first()
    return taken is not None


class Claim:
    """A pass this pod holds. `is_set` is the question to ask between two transactions: the
    worker is stopping, or another pod has the pass; asking also renews the lease when due."""

    def __init__(self, engine: Engine | None, name: str, pod: str, stop: Stopping) -> None:
        self._engine, self._name, self._pod, self._stop = engine, name, pod, stop
        self._renew_at = time.monotonic() + RENEW_EVERY
        self._lost = False

    def _set_lease(self, until: object) -> bool:
        assert self._engine is not None
        r = t.worker_run.c
        with self._engine.begin() as conn:
            held = conn.execute(
                update(t.worker_run)
                .where(r.name == self._name, r.pod == self._pod)
                .values(lease_until=until)
                .returning(r.name)
            ).first()
        return held is not None

    def is_set(self) -> bool:
        if self._stop.is_set() or self._lost:
            return True
        if self._engine is not None and time.monotonic() >= self._renew_at:
            self._renew_at = time.monotonic() + RENEW_EVERY
            self._lost = not self._set_lease(listening._DB_NOW + LEASE)
            if self._lost:
                log.warning("worker %s: another pod has the pass, this one stops", self._name)
        return self._lost

    def release(self) -> None:
        """The pass is over: the interval alone decides the next one, not what is left of the
        lease. A pod that dies never gets here, and its lease simply expires."""
        if self._engine is not None:
            self._set_lease(listening._DB_NOW)


@contextmanager
def claim(
    engine: Engine,
    name: str,
    interval: float,
    stop: Stopping | None = None,
    pod: str = listening.POD,
) -> Iterator[Claim | None]:
    """The pass as a `Claim`, or None when another pod ran it within `interval` or holds it."""
    stop = stop if stop is not None else threading.Event()
    if engine.dialect.name != "postgresql":
        yield Claim(None, name, pod, stop)
        return
    if not _take(engine, name, interval, pod):
        yield None
        return
    held = Claim(engine, name, pod, stop)
    try:
        yield held
    finally:
        try:
            held.release()
        except Exception:  # the lease expires on its own; an error of the pass goes on up
            log.exception("worker %s: releasing the pass failed", name)
