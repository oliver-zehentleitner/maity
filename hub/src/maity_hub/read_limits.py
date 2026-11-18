"""Reads per credential (docs/api.md §1.7 "Reads per credential", §16.5): a signed-in caller's
`GET` and `HEAD` calls of the API, counted per credential in this process, and refused as
`rate_limited` past `max_reads_per_minute`.

`auth.caller` asks `take` once the credential is known and before any side effect of §2.4, so a
refused read writes nothing. The count is a sliding window estimated from two fixed one-minute
windows (the current count, plus the previous one weighted by what still overlaps), the
estimate the shared limits use (`ratelimit.estimate_wait`): two numbers per credential, never
one entry per read. A credential not seen for two windows counts for nothing and is forgotten,
a few at every call, so memory follows the credentials active in the last two minutes.

The instance's value is read at most every `CACHE_SECONDS` per process, so a read costs no
statement for it; `forget_instance_value` drops it at once when the instance admin changes it
in this process. Why all of this: hub/context/serving.md aaf47866.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import math
import secrets
import threading
from collections import OrderedDict
from dataclasses import dataclass

from sqlalchemy import Connection

from maity_hub import clock, secretbox
from maity_hub import instance_settings as store
from maity_hub.errors import ApiError
from maity_hub.ratelimit import estimate_wait

log = logging.getLogger(__name__)

WINDOW_SECONDS = 60.0
CACHE_SECONDS = 30.0
# Stale credentials forgotten per call at most: authentication runs on the event loop, where a
# pass over every key would hold every other request of the process.
FORGET_PER_CALL = 8
READ_METHODS = frozenset({"GET", "HEAD"})
API_PREFIX = "/api/v1/"
TAG_PURPOSE = "logs.read_limit_tag"
TAG_HEX = 12


@dataclass
class _Count:
    window: int  # the index of the fixed window `current` counts in
    current: int
    previous: int


class ReadCounter:
    """Reads per key in two fixed windows. Thread-safe: authentication runs on the event loop,
    but a route may still authenticate from a worker thread."""

    def __init__(self, seconds: float = WINDOW_SECONDS) -> None:
        self.seconds = seconds
        self._counts: OrderedDict[str, _Count] = OrderedDict()  # least recently read first
        self._lock = threading.Lock()

    def take(self, key: str, limit: int, paid: set[str], now: float) -> int:
        """Count one read of `key` at `now` (seconds); 0 when it fits `limit`, else the seconds
        until one more would fit, and the read is not counted. `paid` is the request's own: the
        keys it was counted for, kept across its transaction's runs, so a request run again is
        not counted twice, also when other reads of the same key run meanwhile."""
        index = math.floor(now / self.seconds)
        elapsed = (now - index * self.seconds) / self.seconds
        with self._lock:
            self._forget(index)
            if key in paid:
                return 0
            count = self._counts.get(key)
            if count is None:
                count = self._counts[key] = _Count(index, 0, 0)
            elif count.window != index:
                # The window moved on: the current count becomes the previous one, unless more
                # than one window passed, when neither counts any more.
                count.previous = count.current if count.window == index - 1 else 0
                count.current = 0
                count.window = index
            self._counts.move_to_end(key)
            # A float's last digit does not refuse a read that fits exactly.
            if count.current + 1 + count.previous * (1 - elapsed) <= limit + 1e-9:
                count.current += 1
                paid.add(key)
                return 0
            return estimate_wait(count.current + 1, count.previous, elapsed, 1, limit, self.seconds)

    def _forget(self, index: int) -> None:
        """Drop up to `FORGET_PER_CALL` keys from the front whose counts no longer reach into
        the current window's estimate; the front is the key read least recently."""
        for _ in range(FORGET_PER_CALL):
            if not self._counts:
                return
            key, oldest = next(iter(self._counts.items()))
            if oldest.window >= index - 1:
                return
            del self._counts[key]

    def __len__(self) -> int:
        return len(self._counts)

    def clear(self) -> None:
        with self._lock:
            self._counts.clear()


COUNTER = ReadCounter()

# The admin's value or the default, as (until, limit), while the environment sets none.
_cached: list[tuple[float, int | None] | None] = [None]
_cache_lock = threading.Lock()
_tag_key: list[bytes] = [secrets.token_bytes(32)]


def configure(secret_key: bytes | None) -> None:
    """The key of the credential tags in the refusal's log line: derived from the instance key
    when there is one, so the tag stays the same across processes and restarts; else a random
    key of this process."""
    _tag_key[0] = (
        secretbox.derive(secret_key, TAG_PURPOSE) if secret_key else secrets.token_bytes(32)
    )


def instance_value(conn: Connection, env_value: object) -> int | None:
    """`max_reads_per_minute` in force on the instance, None for `unlimited`: the environment's
    value, else the admin's, else the default (§16.2), read at most every `CACHE_SECONDS`."""
    from maity_hub import limits

    if env_value is not None:
        return None if env_value == limits.UNLIMITED else int(str(env_value))
    now = clock.now().timestamp()
    with _cache_lock:
        cached = _cached[0]
    if cached is not None and cached[0] > now:
        return cached[1]
    name = f"limits.{limits.READS}"
    value = store.effective(name, None, store.stored(conn, "limits"))[0]
    found = None if value == limits.UNLIMITED else int(value)
    with _cache_lock:
        _cached[0] = (now + CACHE_SECONDS, found)
    return found


def forget_instance_value() -> None:
    """The instance admin changed the value: the next read reads it again."""
    with _cache_lock:
        _cached[0] = None


def counts(method: str, path: str) -> bool:
    """Whether a call is a read of the API (§1.7): `GET` or `HEAD` under `/api/v1/`. `path` is
    the decoded path the router matches (`scope["path"]`), not the raw one: the server decodes
    every escape before routing, so a route reached under any spelling is the same read."""
    return method.upper() in READ_METHODS and path.startswith(API_PREFIX)


def take(
    conn: Connection,
    key: str,
    *,
    env_value: object,
    paid: set[str],
    method: str,
    route: str,
) -> None:
    """Count one read of the credential `key`, unless the request `paid` for it already;
    `rate_limited` with `Retry-After` past the instance's value, and one log line naming the
    route and a tag of the credential."""
    limit = instance_value(conn, env_value)
    if limit is None:
        return
    wait = COUNTER.take(key, limit, paid, clock.now().timestamp())
    if wait:
        log.info(
            "read limit: %s %s credential=%s limit=%d retry_after=%d",
            method,
            route,
            tag(key),
            limit,
            wait,
        )
        raise refusal(wait)


def refusal(wait: int) -> ApiError:
    return ApiError(
        429,
        "rate_limited",
        "too many reads for this credential",
        headers={"Retry-After": str(wait)},
    )


def tag(key: str) -> str:
    """A short tag of a credential for the log: the same credential has the same tag, and
    neither the credential's id nor its secret can be read back from it."""
    return hmac.new(_tag_key[0], key.encode(), hashlib.sha256).hexdigest()[:TAG_HEX]


def reset() -> None:
    """Forget every count and the cached value (tests)."""
    COUNTER.clear()
    forget_instance_value()
