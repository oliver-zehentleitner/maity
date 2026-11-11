"""The process's nonce window (`credentials.NonceWindow`, SQLite and MariaDB, docs/api.md §8.3):
the same answers as before, and a call that visits only what expired since the last one, never
the whole window (it runs on the event loop since tsk-v874y63b4z8p PR 2)."""

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


def test_a_call_visits_only_the_expired_nonces_never_the_whole_window(
    clock: list[float],
) -> None:
    window = NonceWindow(seconds=600)
    for n in range(LIVE):
        assert window.first_use("cred", f"n{n}", object())
        if n == LIVE // 2 - 1:
            clock[0] += 1  # the second half is spent a second later
    window._seen = _Untouchable(window._seen)
    # Every nonce is live: a call visits none of them.
    assert window.first_use("cred", "fresh", object())
    assert len(window._seen) == LIVE + 1
    # The first half's window ended: one call drops exactly those, and only those.
    clock[0] += 599.5  # past the first half's window (spent at 1000), within the second's (1001)
    assert window.first_use("cred", "later", object())
    assert len(window._seen) == LIVE // 2 + 2
