"""When a placement's process exits: restart after a backoff, or stop at the crash cap
(runner design §8, "Harness crash loop").

Pure: the times come in, the decision goes out. An exit within `quick_exit` seconds of the
start is a crash; `crash_cap` crashes within `crash_window` end the placement as
`failed`/`crash_loop` until its generation moves. A run that lasted longer resets the count.
Every exit is restarted after `initial × factor^n` seconds (n = the earlier crashes counted),
capped at `max`, with ±20 % jitter.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from . import config

JITTER = 0.2


@dataclass(frozen=True)
class Decision:
    crashes: list[float]  # start times of the quick exits still inside the window
    retry_at: float | None  # None: no restart (the crash cap)

    @property
    def crash_loop(self) -> bool:
        return self.retry_at is None


def delay(policy: config.Restart, crashes: int, rand: Callable[[], float]) -> float:
    base = min(policy.initial * policy.factor**crashes, policy.max)
    return float(base * (1 + JITTER * (2 * rand() - 1)))


def on_exit(
    policy: config.Restart,
    crashes: list[float],
    started_at: float,
    exited_at: float,
    rand: Callable[[], float],
) -> Decision:
    """The decision for one exit. `crashes` are the earlier quick exits' times."""
    if exited_at - started_at >= policy.quick_exit:
        return Decision([], exited_at + delay(policy, 0, rand))
    window = [t for t in crashes if exited_at - t < policy.crash_window] + [exited_at]
    if len(window) >= policy.crash_cap:
        return Decision(window, None)
    return Decision(window, exited_at + delay(policy, len(window) - 1, rand))
