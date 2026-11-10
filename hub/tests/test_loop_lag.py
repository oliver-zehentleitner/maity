"""The event loop stays on time under concurrent requests (tsk-v874y63b4z8p, the loop-lag guard).

A route moved to the async engine runs its database work on the event loop
(`AsyncConnection.run_sync`), so a slow body there delays the requests and held long-polls'
wakes that are due meanwhile. This test sends concurrent requests of the hot families and fails
when the loop's own tick (`request_stats.watch_load`, the `loop_late_*` of the `stats` line) ran
later than the limit at any time during them. Each app's loop gets a window of its own for the
test, which the `stats` reporter does not drain, so no tick of the run is lost to a report, and
the apps of the test (the owner's, the agent's) are each checked. It also prints the windows'
fields, the numbers each PR of the series names before and after.

A `load` test: PostgreSQL in CI's `hub-load` job (`pytest -m load`), not the ordinary suite."""

from __future__ import annotations

import os
import threading
from typing import Any

import pytest
from sqlalchemy import Engine

from maity_hub import request_stats
from tests import flow
from tests.conftest import ClientFactory
from tests.test_notifications import bell
from tests.test_notifications_load import inbox_item, owner  # noqa: F401

pytestmark = pytest.mark.load

# The loop's tick may run this much later than due, at most, while the requests run (250 ms by
# default; `MAITY_LOOP_LATE_LIMIT_MS` sets another). The tick looks every 0.1 s; a late tick is
# the loop's scheduling delay, the loop busy (or the GIL held) for that long, and what was due on
# it meanwhile waited up to as much. Agreed in PR 1 from runs on main and the branch (the PR's
# body); a PR that moves a family onto the loop must stay under it.
LOOP_LATE_LIMIT_MS = int(os.environ.get("MAITY_LOOP_LATE_LIMIT_MS", "250"))
THREADS = 16
ROUNDS = int(os.environ.get("MAITY_LOOP_ROUNDS", "20"))


def fields(text: str) -> dict[str, float]:
    return {k: float(v) for k, v in (pair.split("=") for pair in text.split())}


@pytest.fixture
def loop_windows(monkeypatch: pytest.MonkeyPatch) -> list[request_stats.LoadWindow]:
    """A window of its own for each app the test starts, in the order they start: the app's
    `watch_load` records there instead of the process's `LOAD`, which the `stats` reporter
    empties every minute. Asked for before `owner`, so it is in place before any app starts."""
    windows: list[request_stats.LoadWindow] = []
    real = request_stats.watch_load

    async def watched(
        _load: request_stats.LoadWindow, tick: float = request_stats.LOAD_TICK
    ) -> None:
        window = request_stats.LoadWindow()
        windows.append(window)
        await real(window, tick)

    monkeypatch.setattr(request_stats, "watch_load", watched)
    return windows


def test_the_event_loop_stays_on_time_under_concurrent_requests(
    loop_windows: list[request_stats.LoadWindow],
    make_client: ClientFactory,
    owner: flow.Human,  # noqa: F811
    migrated: Engine,
) -> None:
    inbox_item(make_client, owner)
    paths = [
        "/projects/maintainer/maity",
        "/projects/maintainer/maity/members",
        "/projects/maintainer/maity/tasks",
        "/projects/maintainer/maity/requests",
    ]
    failures: list[Any] = []

    def calls() -> None:
        try:
            for _ in range(ROUNDS):
                bell(owner, limit=20)
                for path in paths:
                    answer = owner.get(path)
                    if answer.status_code != 200:
                        failures.append((path, answer.status_code))
        except Exception as error:  # a thread's failure must fail the test
            failures.append(error)

    assert loop_windows, "no app's loop was watched"
    for window in loop_windows:
        window.fields()  # each window starts here
    callers = [threading.Thread(target=calls) for _ in range(THREADS)]
    for caller in callers:
        caller.start()
    for caller in callers:
        caller.join(timeout=600)
    seen = [fields(window.fields()) for window in loop_windows]
    print(f"\nloop-lag guard ({THREADS} threads × {ROUNDS} rounds), one window per app: {seen}")
    assert failures == []
    assert max(w["loop_late_max_ms"] for w in seen) <= LOOP_LATE_LIMIT_MS, seen
