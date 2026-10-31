"""Counts every replica shares: the rate limits, the breakers and the guess counters, on
PostgreSQL (hub/context/replicas.md 2bd65fec).

One UNLOGGED table, `rate_count(bucket, subject, window_start, count)`; `subject` is the
limit's key. A limit counts in fixed
windows and reads a sliding window from two of them: the current window's count plus the
previous window's, weighted by how much of it still overlaps (`estimate`). A moment until which
something stays shut (a tripped breaker) is a row of its own, its `count` the moment in epoch
seconds (`set_until`, `until`). Every call is its own short transaction, apart from the request's:
a count is spent whether the request then succeeds or not, as the counts in the process were.

`configure` turns it on for an engine on PostgreSQL; elsewhere, and before it is configured, the
callers keep their counts in the process.
"""

from __future__ import annotations

import hashlib
import math
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Connection, Engine, delete, func, select, update
from sqlalchemy.dialects import postgresql

from maity_hub import tables as t
from maity_hub import write_guard

KEY_MAX = 200  # a longer key is kept as its SHA-256 (`_key`)
UNTIL_WINDOW = datetime(1970, 1, 1, tzinfo=UTC)  # the `window_start` of an `until` row
KEPT = timedelta(days=2)  # the longest window is a day; its previous window is read too
SWEEP_EVERY = 1000  # adds per process between deletes of windows nobody reads any more

_engine: list[Engine | None] = [None]
_adds = [0]
_lock = threading.Lock()


@dataclass(frozen=True)
class Window:
    """The counts a limit reads: the current window's, the previous window's, how far into the
    current window `now` is (0 to 1), and where the current window starts."""

    current: int
    previous: int
    elapsed: float
    start: datetime

    def estimate(self) -> float:
        """The sliding window's count: the previous window weighted by what still overlaps."""
        return self.current + self.previous * (1 - self.elapsed)


def configure(engine: Engine | None) -> None:
    """Share the counts through `engine` when it is PostgreSQL; otherwise keep them in the
    process (None turns sharing off)."""
    _engine[0] = engine if engine is not None and engine.dialect.name == "postgresql" else None


def active() -> bool:
    return _engine[0] is not None


def _db() -> Engine:
    engine = _engine[0]
    if engine is None:
        raise RuntimeError("shared counts are not configured")
    return engine


def _key(key: str) -> str:
    """The key as stored: a long one, or one with a NUL (a pair of an address and a source)
    that PostgreSQL text cannot hold, as its SHA-256."""
    if len(key) <= KEY_MAX and "\x00" not in key:
        return key
    return hashlib.sha256(key.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _start(now: datetime, seconds: float) -> datetime:
    epoch = (now - UNTIL_WINDOW).total_seconds()
    return UNTIL_WINDOW + timedelta(seconds=math.floor(epoch / seconds) * seconds)


def _window(conn: Connection, bucket: str, key: str, seconds: float, now: datetime) -> Window:
    start = _start(now, seconds)
    c = t.rate_count.c
    rows = dict(
        conn.execute(
            select(c.window_start, c.count).where(
                c.bucket == bucket,
                c.subject == key,
                c.window_start.in_([start, start - timedelta(seconds=seconds)]),
            )
        ).all()
    )
    return Window(
        current=int(rows.get(start, 0)),
        previous=int(rows.get(start - timedelta(seconds=seconds), 0)),
        elapsed=(now - start).total_seconds() / seconds,
        start=start,
    )


def _upsert(
    conn: Connection, bucket: str, key: str, at: datetime, count: int, now: datetime
) -> None:
    """Add `count` to the row at `at`, and every thousandth time sweep the old rows."""
    statement = postgresql.insert(t.rate_count).values(
        bucket=bucket, subject=key, window_start=at, count=count
    )
    conn.execute(
        statement.on_conflict_do_update(
            index_elements=["bucket", "subject", "window_start"],
            set_={"count": t.rate_count.c.count + count},
        )
    )
    with _lock:
        _adds[0] += 1
        sweep = _adds[0] % SWEEP_EVERY == 0
    if sweep:
        conn.execute(
            delete(t.rate_count).where(
                t.rate_count.c.window_start < now - KEPT,
                t.rate_count.c.window_start != UNTIL_WINDOW,
            )
        )


def add(bucket: str, key: str, seconds: float, count: int = 1) -> Window:
    """Count `count` in the current window and read both windows, in one transaction."""
    key, now = _key(key), _now()
    with _db().begin() as conn:
        write_guard.exempt(conn)  # a count is no write of an account
        _upsert(conn, bucket, key, _start(now, seconds), count, now)
        return _window(conn, bucket, key, seconds, now)


# --- exact: a row per attempt, for the small limits ------------------------------------


@dataclass(frozen=True)
class Log:
    """An exact limit's attempts inside the window, oldest first, and the moment read."""

    entries: list[tuple[datetime, int]]
    now: datetime

    @property
    def total(self) -> int:
        return sum(count for _, count in self.entries)


def _log(conn: Connection, bucket: str, key: str, seconds: float, now: datetime) -> Log:
    c = t.rate_count.c
    rows = conn.execute(
        select(c.window_start, c.count)
        .where(
            c.bucket == bucket,
            c.subject == key,
            c.window_start > now - timedelta(seconds=seconds),
            c.count > 0,
        )
        .order_by(c.window_start)
    ).all()
    return Log(entries=[(at, int(held)) for at, held in rows], now=now)


def _hold(conn: Connection, bucket: str, key: str) -> None:
    """One key's exact attempts one at a time across replicas, until the transaction ends."""
    conn.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(f"{bucket}:{key}", 0))))


def log_take(
    bucket: str, key: str, seconds: float, count: int, limit: int
) -> tuple[Log, datetime | None]:
    """Record `count` attempts at this moment when they fit `limit` within `seconds`; the log
    as read, and the moment recorded (None when refused: nothing is written then)."""
    key, now = _key(key), _now()
    with _db().begin() as conn:
        write_guard.exempt(conn)  # a count is no write of an account
        _hold(conn, bucket, key)
        found = _log(conn, bucket, key, seconds, now)
        if found.total + count > limit:
            return found, None
        _upsert(conn, bucket, key, now, count, now)
    return found, now


def log_read(bucket: str, key: str, seconds: float) -> Log:
    with _db().connect() as conn:
        return _log(conn, bucket, _key(key), seconds, _now())


def read(bucket: str, key: str, seconds: float) -> Window:
    with _db().connect() as conn:
        return _window(conn, bucket, _key(key), seconds, _now())


def subtract(bucket: str, key: str, start: datetime, count: int) -> None:
    """Take `count` back from the window that starts at `start`, never below zero."""
    c = t.rate_count.c
    with _db().begin() as conn:
        write_guard.exempt(conn)  # a count is no write of an account
        conn.execute(
            update(t.rate_count)
            .where(c.bucket == bucket, c.subject == _key(key), c.window_start == start)
            .values(count=func.greatest(c.count - count, 0))
        )


def set_until(bucket: str, key: str, until_epoch: float) -> None:
    """Keep `bucket`/`key` shut until `until_epoch` (seconds), never shortening it."""
    statement = postgresql.insert(t.rate_count).values(
        bucket=bucket, subject=_key(key), window_start=UNTIL_WINDOW, count=math.ceil(until_epoch)
    )
    with _db().begin() as conn:
        write_guard.exempt(conn)  # a count is no write of an account
        conn.execute(
            statement.on_conflict_do_update(
                index_elements=["bucket", "subject", "window_start"],
                set_={"count": func.greatest(t.rate_count.c.count, statement.excluded.count)},
            )
        )


def until(bucket: str, key: str) -> float:
    """The moment (epoch seconds) `bucket`/`key` is shut until; 0 when it is not."""
    c = t.rate_count.c
    with _db().connect() as conn:
        found = conn.execute(
            select(c.count).where(
                c.bucket == bucket, c.subject == _key(key), c.window_start == UNTIL_WINDOW
            )
        ).scalar()
    return float(found or 0)


def clear(bucket: str, key: str | None = None) -> None:
    """Forget a bucket's counts, or one key's."""
    c = t.rate_count.c
    query = delete(t.rate_count).where(c.bucket == bucket)
    if key is not None:
        query = query.where(c.subject == _key(key))
    with _db().begin() as conn:
        write_guard.exempt(conn)  # a count is no write of an account
        conn.execute(query)
