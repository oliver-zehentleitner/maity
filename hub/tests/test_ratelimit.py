"""The limiter, in the process and across replicas on PostgreSQL, and the scrypt slots."""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine

from maity_hub.auth import passwords
from maity_hub.ratelimit import Limiter


def test_the_limit_and_the_retry_after() -> None:
    limiter = Limiter(2, 60, name="test")
    assert limiter.hit("a") == 0
    assert limiter.hit("a") == 0
    assert limiter.hit("a") >= 1
    assert limiter.blocked("a") >= 1
    assert limiter.blocked("b") == 0
    assert len(limiter) == 1  # `blocked` records nothing


def test_stale_keys_are_forgotten(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]

    class Clock:  # the limiter's own view of time, nobody else's
        @staticmethod
        def monotonic() -> float:
            return now[0]

    monkeypatch.setattr("maity_hub.ratelimit.time", Clock)
    limiter = Limiter(10, 60, name="test")
    for i in range(1100):
        limiter.hit(f"address-{i}")
    assert len(limiter) > 1024  # all inside the window: nothing to forget
    now[0] += 61
    limiter.hit("fresh")
    assert len(limiter) == 1


def test_several_at_once_wait_for_room_for_all(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [0.0]

    class Clock:
        @staticmethod
        def monotonic() -> float:
            return now[0]

    monkeypatch.setattr("maity_hub.ratelimit.time", Clock)
    limiter = Limiter(3, 10, name="test")
    assert limiter.take("k", 1) == 0
    now[0] = 5.0
    assert limiter.take("k", 2) == 0
    now[0] = 6.0
    assert limiter.take("k", 1) == 4  # the hit at 0 leaves at 10
    assert limiter.take("k", 2) == 9  # two need the hit at 5 gone too: at 15
    with pytest.raises(ValueError):
        limiter.take("k", 4)  # never fits: no wait would be true
    now[0] = 15.0
    wait, mark = limiter.place("k", 2)
    assert wait == 0
    limiter.release("k", mark, 2)  # work that did not happen: both come back
    assert limiter.take("k", 3) == 0


def test_a_late_release_frees_no_later_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [0.0]

    class Clock:
        @staticmethod
        def monotonic() -> float:
            return now[0]

    monkeypatch.setattr("maity_hub.ratelimit.time", Clock)
    limiter = Limiter(2, 10, name="test")
    wait, mark = limiter.place("k")
    assert (wait, mark) == (0, 0.0)
    now[0] = 11.0  # the place has left the window
    assert limiter.hit("k") == 0
    assert limiter.hit("k") == 0
    limiter.release("k", mark)  # its own place only: gone already
    assert limiter.hit("k") >= 1
    # Inside the window the release frees exactly that place.
    wait, mark = limiter.place("j")
    limiter.hit("j")
    limiter.release("j", mark)
    assert limiter.hit("j") == 0
    wait, mark = limiter.place("j")  # full now: refused, nothing to release
    assert wait >= 1 and mark is None


def test_at_most_four_scrypt_derivations_run_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    running = 0
    peak = 0
    lock = threading.Lock()
    real = hashlib.scrypt

    def counting(password: bytes, **kwargs: Any) -> bytes:
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        try:
            time.sleep(0.02)
            return real(password, **kwargs)
        finally:
            with lock:
                running -= 1

    monkeypatch.setattr(hashlib, "scrypt", counting)
    threads = [
        threading.Thread(target=passwords.verify_password, args=("x", passwords.DUMMY_HASH))
        for _ in range(12)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert peak == passwords.CONCURRENT


# --- across replicas, on PostgreSQL (hub/context/replicas.md 2bd65fec) ----------------------


@pytest.fixture
def shared(migrated: Engine) -> Iterator[None]:
    """The counts in the database, as `create_app` configures them on PostgreSQL."""
    from maity_hub import shared_counts

    if migrated.dialect.name != "postgresql":
        pytest.skip("SQLite and MariaDB keep the counts in the process")
    shared_counts.configure(migrated)
    yield
    shared_counts.configure(None)


def test_a_limit_counts_every_replicas_attempts(shared: None) -> None:
    first, second = Limiter(2, 60, name="test.shared"), Limiter(2, 60, name="test.shared")
    assert first.hit("ada") == 0 and second.hit("ada") == 0  # two replicas, one count
    assert first.hit("ada") > 0 and second.hit("ada") > 0  # the limit holds across both
    assert first.blocked("ada") > 0 and second.hit("bob") == 0  # per key, as before
    assert len(first) == 0  # nothing is kept in the process


def test_what_a_replica_gives_back_frees_the_place_for_every_replica(shared: None) -> None:
    first, second = Limiter(1, 60, name="test.back"), Limiter(1, 60, name="test.back")
    wait, mark = first.place("ada")
    assert wait == 0 and second.hit("ada") > 0
    first.release("ada", mark)
    wait, mark = second.place("ada")
    assert wait == 0
    second.release("ada", mark)
    assert first.hit("ada") == 0
    first.reset()
    assert second.blocked("ada") == 0  # a reset clears the bucket for everyone


def test_a_breaker_tripped_on_one_replica_shuts_every_replica(shared: None) -> None:
    from maity_hub import registration

    one, other = registration.Breaker(), registration.Breaker()
    assert one.hit(2) == 0 and other.hit(2) == 0
    assert one.hit(2) > 0  # the third request of the minute, across both
    assert other.hit(1000) > 0  # shut for every replica, whatever its own count says
    dropped = registration.Dropped(), registration.Dropped()
    dropped[0].add()
    dropped[1].add()
    assert dropped[0].last_hour() == dropped[1].last_hour() == 2  # the instance's sum


def _frozen_shared_clock(monkeypatch: pytest.MonkeyPatch, start: datetime) -> list[datetime]:
    from maity_hub import shared_counts

    now = [start]
    monkeypatch.setattr(shared_counts, "_now", lambda: now[0])
    return now


def test_a_release_returns_to_the_window_it_was_counted_in(
    shared: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """c47w at #822: what a take counted in one window is given back there, not to the
    window that is current when the work fails."""
    from maity_hub import shared_counts

    now = _frozen_shared_clock(monkeypatch, datetime(2026, 10, 31, 0, 0, 50, tzinfo=UTC))
    limiter = Limiter(30, 60, name="test.release")  # over `EXACT_UP_TO`: the estimate
    wait, mark = limiter.place("ada", 2)  # in the window from 0:00
    assert wait == 0
    now[0] += timedelta(seconds=20)  # 0:01:10, the next window
    assert limiter.take("ada", 1) == 0
    limiter.release("ada", mark, 2)
    window = shared_counts.read("test.release", "ada", 60)
    assert (window.current, window.previous) == (1, 0)  # the new window keeps its take


def test_blocked_answers_as_hit_would_with_a_weighted_previous_window(
    shared: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """n3yv at #822: 29 now and 1 before, halfway: 29.5 counted, so one more (30.5) is over a
    limit of 30, and `blocked` says so as `hit` would."""
    now = _frozen_shared_clock(monkeypatch, datetime(2026, 10, 31, 0, 0, 0, tzinfo=UTC))
    limiter = Limiter(30, 60, name="test.blocked")  # over `EXACT_UP_TO`: the estimate
    assert limiter.hit("ada") == 0  # the previous window
    now[0] += timedelta(seconds=90)  # halfway through the next one
    for _ in range(29):
        assert limiter.hit("ada") == 0
    assert limiter.blocked("ada") > 0


def test_a_small_limit_counts_every_attempt_exactly_across_replicas(
    shared: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#822's CI: once in ten minutes waited up to twenty with the two-window estimate. A
    small limit keeps a row per attempt and answers as the process does."""
    from maity_hub import shared_counts

    now = [datetime(2026, 10, 31, 0, 9, 50, tzinfo=UTC)]  # late in a fixed window
    monkeypatch.setattr(shared_counts, "_now", lambda: now[0])
    first, second = Limiter(1, 600, name="test.once"), Limiter(1, 600, name="test.once")
    assert first.exact and first.hit("ada") == 0
    assert second.hit("ada") == 600  # the other replica, at once: a whole window
    now[0] += timedelta(seconds=250)  # past the fixed window's end: nothing changes
    assert first.blocked("ada") == 350 and second.hit("ada") == 350
    assert shared_counts.log_read("test.once", "ada", 600).total == 1  # refusals write nothing
    now[0] += timedelta(seconds=350)
    assert second.hit("ada") == 0  # exactly ten minutes after the first


def test_an_exact_limit_gives_back_exactly_what_was_taken(shared: None) -> None:
    limiter = Limiter(3, 60, name="test.exact.back")
    wait, one = limiter.place("ada")
    assert wait == 0
    wait, two = limiter.place("ada", 2)
    assert wait == 0 and limiter.hit("ada") > 0
    limiter.release("ada", one)  # the first place's own row
    limiter.release("ada", two, 1)  # one of the two placed together
    assert limiter.take("ada", 2) == 0
    assert limiter.hit("ada") > 0
