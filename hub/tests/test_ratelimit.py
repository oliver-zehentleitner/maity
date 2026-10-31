"""The limiter, in the process and across replicas on PostgreSQL, and the scrypt slots."""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Iterator
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
    assert limiter.take("k", 4) == 10  # never fits: a whole window
    limiter.give_back("k", 2)
    assert limiter.take("k", 2) == 0


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
    assert second.take("ada", 1) == 0
    second.give_back("ada", 1)
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
