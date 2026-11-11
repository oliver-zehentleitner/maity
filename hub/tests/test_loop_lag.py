"""The event loop stays on time under concurrent requests (tsk-v874y63b4z8p, the loop-lag guard).

A route moved to the async engine runs its database work on the event loop
(`AsyncConnection.run_sync`), so a slow body there delays the requests and held long-polls'
wakes that are due meanwhile. This test sends concurrent requests of the hot families and fails
when an app's loop ran later than the machine let an idle loop run. Each app's loop gets a window
of its own for the test (`request_stats.watch_load`, the `loop_late_*` of the `stats` line), which
the `stats` reporter does not drain, so no tick of the run is lost to a report, and the apps of
the test (the owner's, the agent's) are each checked.

The reference is a bare event loop in a thread of its own, the same tick and nothing else on it:
what it is late is the machine's share (CPU and the GIL taken by the request threads and the
database), which on a shared CI runner reached 247 ms on a loop that served nothing. An app's loop
fails the guard when its worst tick runs more than `LOOP_LATE_MARGIN_MS` later than the
reference's worst tick, or when its average is above `LOOP_LATE_AVG_LIMIT_MS`. The reference
shares the GIL, so a computation that holds it on an app's loop delays the reference as much and
passes the margin: one callback on an app's loop may also spend at most
`LOOP_CALLBACK_CPU_LIMIT_MS` of the loop thread's CPU time, the garbage collector's left out. The
test prints every window's fields and each app loop's longest callback, the numbers each PR of the
series names before and after.

A `load` test: PostgreSQL in CI's `hub-load` job (`pytest -m load`), not the ordinary suite."""

from __future__ import annotations

import asyncio
import contextlib
import gc
import os
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Engine

from maity_hub import request_stats
from tests import flow
from tests.conftest import ClientFactory
from tests.test_notifications import bell
from tests.test_notifications_load import inbox_item, owner  # noqa: F401

pytestmark = pytest.mark.load

# The tick looks every 0.1 s; a late tick is the loop's scheduling delay, the loop busy (or the GIL
# held) for that long, and what was due on it meanwhile waited up to as much. An app's loop may run
# its worst tick this much later than the idle reference loop's worst tick
# (`MAITY_LOOP_LATE_MARGIN_MS` sets another), and late by this much on average at most
# (`MAITY_LOOP_LATE_AVG_LIMIT_MS`): the margin is the hub's own share of the lag, the average
# catches a loop that is late all the time. The numbers behind both are in
# hub/context/persistence.md (66f0bcf9); a PR that moves a family onto the loop must stay under
# them.
LOOP_LATE_MARGIN_MS = int(os.environ.get("MAITY_LOOP_LATE_MARGIN_MS", "150"))
LOOP_LATE_AVG_LIMIT_MS = int(os.environ.get("MAITY_LOOP_LATE_AVG_LIMIT_MS", "20"))
# The reference shares the process's GIL: work on an app's loop that holds the GIL (a long
# computation in C) stops the reference too and cancels out of the margin. So each callback an
# app's loop runs is also timed in the loop thread's own CPU time (`time.thread_time`), which a
# wait for the GIL or the CPU does not add to, less the garbage collector's: the work the hub
# itself put on the loop, at most this much in one callback (`MAITY_LOOP_CALLBACK_CPU_LIMIT_MS`;
# about 3 ms in local runs).
LOOP_CALLBACK_CPU_LIMIT_MS = int(os.environ.get("MAITY_LOOP_CALLBACK_CPU_LIMIT_MS", "50"))
THREADS = 16
ROUNDS = int(os.environ.get("MAITY_LOOP_ROUNDS", "20"))


def fields(text: str) -> dict[str, float]:
    return {k: float(v) for k, v in (pair.split("=") for pair in text.split())}


class AppLoops:
    """What the test watches of each app's loop: its load window and its thread."""

    def __init__(self) -> None:
        self.windows: list[request_stats.LoadWindow] = []
        self.threads: list[int] = []


@pytest.fixture
def loop_windows(monkeypatch: pytest.MonkeyPatch) -> AppLoops:
    """A window of its own for each app the test starts, in the order they start: the app's
    `watch_load` records there instead of the process's `LOAD`, which the `stats` reporter
    empties every minute. Asked for before `owner`, so it is in place before any app starts."""
    loops = AppLoops()
    real = request_stats.watch_load

    async def watched(
        _load: request_stats.LoadWindow, tick: float = request_stats.LOAD_TICK
    ) -> None:
        window = request_stats.LoadWindow()
        loops.windows.append(window)
        loops.threads.append(threading.get_ident())
        await real(window, tick)

    monkeypatch.setattr(request_stats, "watch_load", watched)
    return loops


@pytest.fixture
def callback_cpu(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[int, float]]:
    """The longest callback, in its thread's CPU milliseconds, each event loop thread ran while
    the test runs (every task step and timer is a `Handle`), less the garbage collector's time in
    it: a collection is the process's, run by whichever thread allocates when it is due (about
    90 ms locally for a full one, on any loop or request thread alike), not work the hub put on
    the loop."""
    longest: dict[int, float] = {}
    collecting: dict[int, float] = {}  # a thread's collection running: its CPU time at the start
    collected: dict[int, float] = {}  # a thread's CPU seconds in collections, summed
    real = asyncio.events.Handle._run

    def collector(phase: str, _info: dict[str, int]) -> None:
        thread = threading.get_ident()
        if phase == "start":
            collecting[thread] = time.thread_time()
        elif thread in collecting:
            spent = time.thread_time() - collecting.pop(thread)
            collected[thread] = collected.get(thread, 0.0) + spent

    def timed(handle: asyncio.events.Handle) -> None:
        thread = threading.get_ident()
        started, before = time.thread_time(), collected.get(thread, 0.0)
        try:
            real(handle)
        finally:
            spent = time.thread_time() - started - (collected.get(thread, 0.0) - before)
            longest[thread] = max(longest.get(thread, 0.0), spent * 1000)

    monkeypatch.setattr(asyncio.events.Handle, "_run", timed)
    gc.callbacks.append(collector)
    yield longest
    gc.callbacks.remove(collector)


@pytest.fixture
def reference() -> Iterator[request_stats.LoadWindow]:
    """An idle event loop beside the apps' for the length of the test: its window shows how late
    the machine alone makes a loop's tick, with nothing of the hub's on it."""
    window = request_stats.LoadWindow()
    started = threading.Event()
    held: dict[str, Any] = {}

    async def watch() -> None:
        held["loop"] = asyncio.get_running_loop()
        held["task"] = asyncio.current_task()
        started.set()
        with contextlib.suppress(asyncio.CancelledError):
            await request_stats.watch_load(window)

    runner = threading.Thread(target=asyncio.run, args=(watch(),), name="loop-reference")
    runner.start()
    started.wait(timeout=10)
    yield window
    held["loop"].call_soon_threadsafe(held["task"].cancel)
    runner.join(timeout=10)


def test_the_event_loop_stays_on_time_under_concurrent_requests(
    reference: request_stats.LoadWindow,
    callback_cpu: dict[int, float],
    loop_windows: AppLoops,
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

    assert loop_windows.windows, "no app's loop was watched"
    for window in (reference, *loop_windows.windows):
        window.fields()  # each window starts here
    callback_cpu.clear()
    callers = [threading.Thread(target=calls) for _ in range(THREADS)]
    for caller in callers:
        caller.start()
    for caller in callers:
        caller.join(timeout=600)
    idle = fields(reference.fields())
    seen = [fields(window.fields()) for window in loop_windows.windows]
    cpu = [round(callback_cpu.get(thread, 0.0), 1) for thread in loop_windows.threads]
    print(
        f"\nloop-lag guard ({THREADS} threads × {ROUNDS} rounds), the idle reference: {idle}, "
        f"one window per app: {seen}, each app loop's longest callback in CPU ms: {cpu}"
    )
    assert failures == []
    for app in seen:
        assert app["loop_late_max_ms"] - idle["loop_late_max_ms"] <= LOOP_LATE_MARGIN_MS, (
            idle,
            seen,
        )
        assert app["loop_late_avg_ms"] <= LOOP_LATE_AVG_LIMIT_MS, (idle, seen)
    assert max(cpu) <= LOOP_CALLBACK_CPU_LIMIT_MS, cpu
