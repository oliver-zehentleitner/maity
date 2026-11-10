"""docs/api.md §16.9: a touched page is rendered once the writer's transaction has committed, in
a transaction of its own; a removal takes it off in the writer's transaction. One target's render
has a time limit, and a starting process a budget."""

from __future__ import annotations

import dataclasses
import logging
import multiprocessing
import threading
import time
from collections.abc import Callable, Iterator
from types import SimpleNamespace

import pytest
from sqlalchemy import Connection, Engine, select

from maity_hub import clock, events, public_pages
from maity_hub import tables as t
from maity_hub.config import ConfigError, Settings
from maity_hub.db import make_engine

KIND = "probe"
DEPENDENT = "probe_dependent"
TARGETS = ["a", "b", "c"]


class Probe:
    """Two kinds of page: `probe` with the targets a, b and c, each shown on the page of the
    `probe_dependent` d. Each render records whether it ran in the writer's connection, inside
    an `events.transaction`, and after the writer's connection had closed."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bool, bool, bool]] = []
        self.slow: set[str] = set()
        # A render of a target here says it started and waits to be let go.
        self.gates: dict[str, tuple[threading.Event, threading.Event]] = {}
        self.clock = 0.0
        self.writer: Connection | None = None

    def render(self, kind: str) -> Callable[[Connection, Settings, str], list[public_pages.Page]]:
        def run(conn: Connection, hub: Settings, target_id: str) -> list[public_pages.Page]:
            writer = self.writer
            self.calls.append(
                (
                    kind,
                    target_id,
                    conn is writer,
                    events.in_transaction(conn),
                    writer is not None and writer.closed,
                )
            )
            if target_id in self.slow:
                self.clock += 3.0  # three seconds on the clock the render limit reads
            gate = self.gates.get(target_id)
            if gate is not None:
                gate[0].set()
                gate[1].wait(10)
            number = len(self.calls) - 1  # this call's place in `calls`
            return [
                public_pages.Page(
                    path=path(kind, target_id),
                    body=f"<p>{target_id} {number}</p>",
                    inputs=f"probe {number}",
                    lastmod=clock.now(),
                    view="probe",
                    data={},
                )
            ]

        return run


def path(kind: str, target_id: str) -> str:
    return f"/{kind}-{target_id}"


def stored(engine: Engine) -> set[str]:
    with engine.connect() as conn:
        return set(conn.execute(select(t.public_page.c.path)).scalars())


def seed(engine: Engine) -> None:
    with engine.begin() as conn:
        for kind, target_id in [*((KIND, x) for x in TARGETS), (DEPENDENT, "d")]:
            public_pages.put(
                conn,
                path=path(kind, target_id),
                kind=kind,
                target_id=target_id,
                body="<p>before</p>",
                inputs="before",
                lastmod=clock.now(),
                view="probe",
                data={},
            )


@pytest.fixture
def probe(
    migrated: Engine, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[Probe, Settings]]:
    found = Probe()
    hub = dataclasses.replace(settings, public_pages=True)
    monkeypatch.setattr(public_pages, "KINDS", {})
    monkeypatch.setattr(public_pages, "time", SimpleNamespace(monotonic=lambda: found.clock))
    public_pages.register(
        public_pages.Kind(
            name=KIND,
            render=found.render(KIND),
            targets=lambda conn, among=None: [i for i in TARGETS if among is None or i in among],
            dependents=lambda conn, target_id: [(DEPENDENT, "d")],
        )
    )
    public_pages.register(
        public_pages.Kind(
            name=DEPENDENT,
            render=found.render(DEPENDENT),
            targets=lambda c, among=None: [i for i in ["d"] if among is None or i in among],
        )
    )
    before = public_pages._hub
    public_pages.configure(hub)
    yield found, hub
    public_pages.configure(before)


def test_a_touch_renders_after_the_commit_in_a_transaction_of_its_own(
    migrated: Engine, probe: tuple[Probe, Settings]
) -> None:
    found, _ = probe
    with events.transaction(migrated) as conn:
        found.writer = conn
        public_pages.touch(conn, KIND, "a", removal=False)
        public_pages.touch(conn, KIND, "a", removal=False)  # the same target: rendered once
        assert found.calls == []
    # Neither in the writer's connection nor in a transaction with its locks, after it closed.
    assert found.calls == [(KIND, "a", False, False, True), (DEPENDENT, "d", False, False, True)]
    assert stored(migrated) == {path(KIND, "a"), path(DEPENDENT, "d")}


def test_a_removal_takes_the_pages_off_in_the_writers_transaction(
    migrated: Engine, probe: tuple[Probe, Settings]
) -> None:
    found, _ = probe
    seed(migrated)
    with events.transaction(migrated) as conn:
        public_pages.touch(conn, KIND, "a")
        inside = set(conn.execute(select(t.public_page.c.path)).scalars())
    # The target and the page that shows it were off before the commit, and are back after it.
    assert path(KIND, "a") not in inside and path(DEPENDENT, "d") not in inside
    assert {path(KIND, "b"), path(KIND, "c")} <= inside
    assert [call[:2] for call in found.calls] == [(KIND, "a"), (DEPENDENT, "d")]
    assert stored(migrated) == {path(KIND, x) for x in TARGETS} | {path(DEPENDENT, "d")}


def test_a_write_that_rolls_back_renders_nothing_and_keeps_the_pages(
    migrated: Engine, probe: tuple[Probe, Settings]
) -> None:
    found, _ = probe
    seed(migrated)
    with pytest.raises(RuntimeError), events.transaction(migrated) as conn:
        public_pages.touch(conn, KIND, "a")
        raise RuntimeError("the write fails")
    assert found.calls == []
    assert stored(migrated) == {path(KIND, x) for x in TARGETS} | {path(DEPENDENT, "d")}


def test_a_render_over_the_limit_takes_the_pages_off(
    migrated: Engine, probe: tuple[Probe, Settings], caplog: pytest.LogCaptureFixture
) -> None:
    found, hub = probe
    seed(migrated)
    found.slow = {"a"}
    with caplog.at_level(logging.WARNING, logger="maity_hub.public_pages"):
        with migrated.begin() as conn:
            public_pages.refresh(conn, hub, KIND, "a")
        with migrated.begin() as conn:
            public_pages.refresh(conn, hub, KIND, "b")
    assert path(KIND, "a") not in stored(migrated) and path(KIND, "b") in stored(migrated)
    assert "over the limit of 2 s; taken off" in caplog.text


def test_the_start_renders_within_its_budget_and_the_worker_renders_the_rest(
    migrated: Engine, probe: tuple[Probe, Settings]
) -> None:
    found, hub = probe
    hub = dataclasses.replace(hub, public_pages_startup_seconds=2, public_pages_render_seconds=60)
    seed(migrated)
    found.slow = {"a"}  # a takes three seconds: past the budget, b, c and d are not reached
    public_pages.startup(migrated, hub)
    assert [call[:2] for call in found.calls] == [(KIND, "a")]
    assert stored(migrated) == {path(KIND, "a")}  # the others are off, nothing older is served
    found.calls.clear()
    worker = public_pages.Worker(migrated, hub, interval=3600)
    worker.start()
    try:
        until = time.monotonic() + 10
        while len(stored(migrated)) < 4 and time.monotonic() < until:
            time.sleep(0.05)
    finally:
        worker.stop()
    assert [call[:2] for call in found.calls] == [(KIND, "b"), (KIND, "c"), (DEPENDENT, "d")]
    assert stored(migrated) == {path(KIND, x) for x in TARGETS} | {path(DEPENDENT, "d")}


def test_a_removal_waits_for_a_render_of_its_target_that_is_running(
    migrated: Engine, probe: tuple[Probe, Settings]
) -> None:
    found, hub = probe
    if migrated.dialect.name != "postgresql":
        pytest.skip("SQLite writes one transaction at a time: the two cannot interleave")
    seed(migrated)
    first = (threading.Event(), threading.Event())
    second = (threading.Event(), threading.Event())
    found.gates["a"] = first

    def running() -> None:  # a render that read its inputs before the removal
        with migrated.begin() as conn:
            public_pages.refresh(conn, hub, KIND, "a")

    def removal() -> None:
        with events.transaction(migrated) as conn:
            public_pages.touch(conn, KIND, "a")

    render = threading.Thread(target=running)
    writer = threading.Thread(target=removal)
    render.start()
    try:
        assert first[0].wait(10)
        found.gates["a"] = second  # the removal's own render, after its commit
        writer.start()
        time.sleep(0.5)  # the removal has reached its delete
        first[1].set()
        assert second[0].wait(10)
        # While the removal's render runs, the earlier render's page is not served: it was
        # written before the removal's delete, not after it.
        assert path(KIND, "a") not in stored(migrated)
    finally:
        first[1].set()
        second[1].set()
        render.join(10)
        if writer.ident is not None:
            writer.join(10)
    with migrated.connect() as conn:
        body = conn.execute(
            select(t.public_page.c.body).where(t.public_page.c.path == path(KIND, "a"))
        ).scalar_one()
    last = max(i for i, call in enumerate(found.calls) if call[:2] == (KIND, "a"))
    assert body == f"<p>a {last}</p>"


def _worker_of_several(url: str, done: multiprocessing.Queue) -> None:  # type: ignore[type-arg]
    """A spawned worker, as `MAITY_WORKERS` above 1 starts one: its parent ran the start, and
    nothing of the parent's memory is here. It only runs its pages worker."""
    found = Probe()
    public_pages.KINDS.clear()
    public_pages.register(
        public_pages.Kind(
            name=KIND,
            render=found.render(KIND),
            targets=lambda conn, among=None: [i for i in TARGETS if among is None or i in among],
            dependents=lambda conn, target_id: [(DEPENDENT, "d")],
        )
    )
    public_pages.register(
        public_pages.Kind(
            name=DEPENDENT,
            render=found.render(DEPENDENT),
            targets=lambda c, among=None: [i for i in ["d"] if among is None or i in among],
        )
    )
    engine = make_engine(url)
    hub = Settings.from_env({"MAITY_DATABASE_URL": url, "MAITY_PUBLIC_URL": "https://hub.example"})
    hub = dataclasses.replace(hub, public_pages=True)
    public_pages.configure(hub)
    worker = public_pages.Worker(engine, hub, interval=3600)
    worker.start()
    try:
        until = time.monotonic() + 20
        while len(stored(engine)) < 4 and time.monotonic() < until:
            time.sleep(0.05)
    finally:
        worker.stop()
    done.put(([call[:2] for call in found.calls], sorted(stored(engine))))


def test_a_worker_of_several_renders_what_its_parents_start_skipped(
    migrated: Engine, probe: tuple[Probe, Settings]
) -> None:
    found, hub = probe
    if migrated.dialect.name != "sqlite":
        pytest.skip("the spawned worker opens the SQLite file by its URL")
    hub = dataclasses.replace(hub, public_pages_startup_seconds=2, public_pages_render_seconds=60)
    seed(migrated)
    found.slow = {"a"}
    public_pages.startup(migrated, hub)  # in the supervisor's parent
    assert stored(migrated) == {path(KIND, "a")}
    spawn = multiprocessing.get_context("spawn")
    done = spawn.Queue()
    child = spawn.Process(
        target=_worker_of_several, args=(migrated.url.render_as_string(False), done)
    )
    child.start()
    calls, pages = done.get(timeout=60)
    child.join(timeout=10)
    assert calls == [(KIND, "b"), (KIND, "c"), (DEPENDENT, "d")]
    assert set(pages) == {path(KIND, x) for x in TARGETS} | {path(DEPENDENT, "d")}


def test_the_time_limits_are_read_from_the_environment() -> None:
    base = {"MAITY_DATABASE_URL": "sqlite://"}
    defaults = Settings.from_env(base)
    assert (defaults.public_pages_startup_seconds, defaults.public_pages_render_seconds) == (30, 2)
    given = Settings.from_env(
        {
            **base,
            "MAITY_PUBLIC_PAGES_STARTUP_SECONDS": "600",
            "MAITY_PUBLIC_PAGES_RENDER_SECONDS": "60",
        }
    )
    assert (given.public_pages_startup_seconds, given.public_pages_render_seconds) == (600, 60)
    for name, value in (
        ("MAITY_PUBLIC_PAGES_STARTUP_SECONDS", "0"),
        ("MAITY_PUBLIC_PAGES_STARTUP_SECONDS", "601"),
        ("MAITY_PUBLIC_PAGES_RENDER_SECONDS", "0"),
        ("MAITY_PUBLIC_PAGES_RENDER_SECONDS", "61"),
        ("MAITY_PUBLIC_PAGES_RENDER_SECONDS", "1.5"),
    ):
        with pytest.raises(ConfigError):
            Settings.from_env({**base, name: value})
