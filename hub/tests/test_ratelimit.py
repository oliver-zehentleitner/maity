"""The in-process limiter, and the scrypt slots."""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Any

import pytest

from maity_hub.auth import passwords
from maity_hub.ratelimit import Limiter


def test_the_limit_and_the_retry_after() -> None:
    limiter = Limiter(2, 60)
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
    limiter = Limiter(10, 60)
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
    limiter = Limiter(3, 10)
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
    limiter = Limiter(2, 10)
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
