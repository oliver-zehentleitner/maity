"""The process's nonce window (`credentials.NonceWindow`, SQLite and MariaDB, docs/api.md §8.3):
the same answers as before, and a call that never visits a live nonce and drops a bounded number
of expired ones, however many expired together (it runs on the event loop since
tsk-v874y63b4z8p PR 2)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from maity_hub.auth import credentials
from maity_hub.auth.credentials import NonceWindow

LIVE = 20_000  # well above the 10,000 at which the old window walked every entry on each call


class _Untouchable(dict):  # type: ignore[type-arg]
    """A window's dict that fails the test when a call walks it."""

    def _walked(self, *_: Any) -> Any:
        raise AssertionError("the call walked every nonce of the window")

    __iter__ = items = keys = values = _walked


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    now = [1000.0]
    monkeypatch.setattr(credentials, "time", SimpleNamespace(monotonic=lambda: now[0]))
    return now


def test_a_nonce_is_spent_once_within_its_window(clock: list[float]) -> None:
    window = NonceWindow(seconds=600)
    first, other = object(), object()
    assert window.first_use("cred", "n1", first)
    assert window.first_use("cred", "n1", first)  # the same request, run again: still the first
    assert not window.first_use("cred", "n1", other)  # a replay within the window
    assert window.first_use("cred2", "n1", other)  # the nonce is per credential
    clock[0] += 600
    assert window.first_use("cred", "n1", other)  # the window ended: it may be spent again
    assert not window.first_use("cred", "n1", first)  # ... and now by `other` only


def test_a_nonce_spent_again_after_its_window_keeps_its_new_entry(clock: list[float]) -> None:
    window = NonceWindow(seconds=600)
    a, b, c = object(), object(), object()
    assert window.first_use("cred", "n", a)
    clock[0] += 600
    assert window.first_use("cred", "n", b)  # its old place in the queue is still there
    clock[0] += 1
    assert window.first_use("cred", "other", c)  # drops that old place, not the new entry
    assert not window.first_use("cred", "n", c)


def test_a_call_never_visits_a_live_nonce(clock: list[float]) -> None:
    window = NonceWindow(seconds=600)
    for n in range(LIVE):
        assert window.first_use("cred", f"n{n}", object())
        if n == LIVE // 2 - 1:
            clock[0] += 1  # the second half is spent a second later
    window._seen = _Untouchable(window._seen)
    # Every nonce is live: a call visits none of them.
    assert window.first_use("cred", "fresh", object())
    assert len(window._seen) == LIVE + 1
    # The first half's window ended: the calls drop those, and only those.
    clock[0] += 599.5  # past the first half's window (spent at 1000), within the second's (1001)
    calls = -(-(LIVE // 2) // credentials.FORGET_PER_CALL)
    for n in range(calls):
        assert window.first_use("cred", f"later{n}", object())
    assert len(window._seen) == LIVE // 2 + 1 + calls
    assert window._expiring[0][1] == ("cred", f"n{LIVE // 2}")  # the second half's first


def test_a_burst_that_expires_together_is_dropped_a_bounded_share_per_call(
    clock: list[float],
) -> None:
    """The whole window can expire at once (a burst, then quiet): no single call pays for all of
    it (a review measured 200,000 expired nonces dropped in one `GET /api/v1/me`, 77 ms on the
    loop)."""
    window = NonceWindow(seconds=600)
    for n in range(LIVE):
        assert window.first_use("cred", f"n{n}", object())
    clock[0] += 600  # every one of them expired
    before = len(window._expiring)
    assert window.first_use("cred", "after", object())
    assert before + 1 - len(window._expiring) == credentials.FORGET_PER_CALL
    assert len(window._seen) == LIVE + 1 - credentials.FORGET_PER_CALL
    # An expired nonce still held is not a spent one: another spender may use it.
    assert window.first_use("cred", f"n{LIVE - 1}", object())
    # The backlog shrinks with every call until it is gone.
    calls = 0
    while len(window._seen) > 2 + calls:
        window.first_use("cred", f"drain{calls}", object())
        calls += 1
    assert calls <= LIVE // (credentials.FORGET_PER_CALL - 1)


def test_the_clock_is_read_under_the_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two threads that read the clock before the lock could append their deadlines out of
    order, and an expired nonce would wait behind a live one."""
    window = NonceWindow(seconds=600)
    held: list[bool] = []

    def monotonic() -> float:
        held.append(window._lock.locked())
        return 1000.0

    monkeypatch.setattr(credentials, "time", SimpleNamespace(monotonic=monotonic))
    assert window.first_use("cred", "n", object())
    assert held == [True]
