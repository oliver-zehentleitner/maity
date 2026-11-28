"""The per-target lock of the public pages on every server database (tsk-pwqhg0d0tznn,
hub/context/public-pages.md): a render that read a target before a takedown cannot write its
page back after it. PostgreSQL holds an advisory lock; MySQL/MariaDB a row of
`public_page_lock`, locked `FOR UPDATE` until the transaction ends; SQLite writes one
transaction at a time. Two real transactions in a fixed interleaving, so these skip on SQLite."""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, func, select, text
from sqlalchemy.exc import OperationalError

from maity_hub import clock, events, public_pages
from maity_hub import tables as t
from maity_hub.config import Settings
from maity_hub.errors import driver_code, driver_number
from tests.concurrency import BLOCKED_FOR, FINISH_WITHIN
from tests.test_public_pages_engine import NOTE, Shown, hub, rows
from tests.test_public_pages_engine import shown as shown  # noqa: F401  (the fixture)


class Running:
    """A function running in a daemon thread on connections of its own."""

    def __init__(self, fn: Callable[[], Any]) -> None:
        self.started = threading.Event()
        self.future: Future[Any] = Future()

        def run() -> None:
            self.started.set()
            try:
                self.future.set_result(fn())
            except BaseException as error:  # handed to whoever takes the result
                self.future.set_exception(error)

        threading.Thread(target=run, name="maity-page-lock-step", daemon=True).start()

    def waiting(self) -> bool:
        """It began and is still blocked `BLOCKED_FOR` seconds later."""
        assert self.started.wait(FINISH_WITHIN), "the step never started"
        try:
            self.future.result(timeout=BLOCKED_FOR)
        except TimeoutError:
            return True
        return False

    def result(self) -> Any:
        return self.future.result(timeout=FINISH_WITHIN)


def server(engine: Engine) -> None:
    if engine.dialect.name == "sqlite":
        pytest.skip("SQLite writes one transaction at a time; the race needs two writers")


def lock_refused(engine: Engine, error: Exception) -> bool:
    """Whether `error` is a lock that was not granted: PostgreSQL's `lock_not_available`
    (SQLSTATE 55P03, from `lock_timeout`), MariaDB's `ER_LOCK_WAIT_TIMEOUT` (1205, from
    `innodb_lock_wait_timeout` and from `FOR UPDATE NOWAIT` alike; MySQL's own NOWAIT code 3572
    is not MariaDB's). MariaDB's driver reports SQLSTATE HY000 for it, so its number is read
    (`driver_number`); any other error is not a refused lock."""
    if engine.dialect.name == "postgresql":
        return driver_code(error) == "55P03"
    return driver_number(error) == 1205


def lock_held(engine: Engine, name: str) -> bool:
    """Whether another transaction holds the lock `name` right now, asked by a third one that
    does not wait for it: `pg_try_advisory_xact_lock` on PostgreSQL, the lock row `FOR UPDATE
    NOWAIT` on MariaDB (no PROCESS privilege needed, which the CI user lacks). Only the code of
    a refused lock (`lock_refused`) counts as held; any other error propagates."""
    with engine.connect() as conn, conn.begin():
        if engine.dialect.name == "postgresql":
            got = conn.execute(
                select(func.pg_try_advisory_xact_lock(func.hashtextextended(name, 0)))
            ).scalar_one()
            return not got
        key = hashlib.sha256(name.encode()).hexdigest()
        try:
            conn.execute(
                text("SELECT digest FROM public_page_lock WHERE digest = :key FOR UPDATE NOWAIT"),
                {"key": key},
            ).all()
        except OperationalError as error:
            if not lock_refused(engine, error):
                raise
            return True
        return False


def pause_first_render(target_id: str) -> tuple[threading.Event, threading.Event]:
    """The next render of `target_id` reads its inputs, then stops until `go` is set; `reached`
    says it got there. Later renders run through."""
    kind = public_pages.KINDS[NOTE]
    reached, go = threading.Event(), threading.Event()
    armed = [True]

    def render(conn: Connection, config: Settings, found: str) -> list[public_pages.Page]:
        pages = kind.render(conn, config, found)
        if armed and found == target_id:
            armed.clear()
            reached.set()
            assert go.wait(FINISH_WITHIN), "never let go"
        return pages

    # Straight into the registry: the `shown` fixture restores it.
    public_pages.KINDS[NOTE] = replace(kind, render=render)
    return reached, go


@pytest.mark.parametrize("locked", [True, False], ids=["with-the-lock", "without-the-lock"])
def test_a_render_cannot_write_back_a_page_a_takedown_removed(
    migrated: Engine,
    settings: Settings,
    shown: Shown,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    locked: bool,
) -> None:
    """R renders "x" after an edit and has read it as shown; then W takes "x" off (as a hold
    does) in its own transaction and touches it. With the lock, W waits for R: R's page is
    committed first, and W's delete takes it off. Without it (the no-op MariaDB had, patched in
    here as the teeth of the test), W deletes and commits at once, and R's write puts the page
    of a target that is no longer shown back, where it stays until the next render."""
    server(migrated)
    config = hub(settings)
    shown.targets["x"] = ("X one", True, clock.now())
    public_pages.render_all(migrated, config)
    assert "X one" in rows(migrated)["/x"].body
    if not locked:
        monkeypatch.setattr(public_pages, "_target_lock", lambda conn, name: None)
    reached, go = pause_first_render("x")
    shown.targets["x"] = ("X two", True, clock.now())  # the edit R renders

    def render_x() -> None:
        with migrated.begin() as conn:
            public_pages.refresh(conn, config, NOTE, "x")

    def take_down() -> None:
        with events.transaction(migrated) as conn:
            shown.targets["x"] = ("X two", False, clock.now())
            public_pages.touch(conn, NOTE, "x")

    render = Running(render_x)
    assert reached.wait(FINISH_WITHIN), "R never read the target"
    writer = Running(take_down)
    try:
        writer_waited = writer.waiting()
        held = lock_held(migrated, f"public_page:{NOTE}:x")
    finally:
        go.set()
    render.result()
    writer.result()
    if locked:
        assert rows(migrated) == {}, "a page of a target no longer shown survived the takedown"
        assert writer_waited, "the takedown did not wait for the render holding the lock"
        assert held, "no transaction held the target's lock while the takedown waited"
    else:
        assert not writer_waited and not held
        assert "X two" in rows(migrated)["/x"].body, "the harness no longer shows the race"


def short_lock_wait(conn: Connection) -> None:
    """A lock wait of one second for this transaction, not the server's default."""
    if conn.dialect.name == "postgresql":
        conn.execute(text("SET LOCAL lock_timeout = '1s'"))
    else:
        # Session-wide on InnoDB: the test drops the connection afterwards (`invalidate`).
        conn.execute(text("SET SESSION innodb_lock_wait_timeout = 1"))


@pytest.mark.parametrize("first_use", [True, False], ids=["row-made-here", "row-there"])
def test_a_rollback_gives_the_lock_back(
    migrated: Engine,
    settings: Settings,
    shown: Shown,  # noqa: F811
    first_use: bool,
) -> None:
    """The lock ends with the transaction however it ends: a render waiting behind one that
    rolls back goes on at once, also where the holder made the lock row and its rollback
    took the row with it; nothing stays held on the pooled connection."""
    server(migrated)
    config = hub(settings)
    shown.targets["x"] = ("X", True, clock.now())
    if not first_use:
        public_pages.render_all(migrated, config)  # the row exists from then on (MariaDB)
    holder = migrated.connect()
    try:
        holder.begin()
        public_pages._target_lock(holder, f"public_page:{NOTE}:x")

        def render_x() -> None:
            with migrated.begin() as conn:
                public_pages.refresh(conn, config, NOTE, "x")

        render = Running(render_x)
        assert render.waiting(), "the render did not wait for the holder"
        holder.rollback()
        render.result()
    finally:
        holder.close()
    assert "X" in rows(migrated)["/x"].body
    assert not lock_held(migrated, f"public_page:{NOTE}:x")


def test_a_render_that_times_out_on_the_lock_writes_nothing_and_takes_nothing_off(
    migrated: Engine,
    settings: Settings,
    shown: Shown,  # noqa: F811
) -> None:
    """A render that waits past the lock timeout fails before it read or wrote anything: its
    transaction rolls back, the stored page stays as it was (not taken off, not replaced), and
    the next render writes it. That page is never one a committed takedown removed, since the
    takedown deletes it in its own transaction; only a render that ran and failed takes a page
    off (`refresh`)."""
    server(migrated)
    config = hub(settings)
    shown.targets["x"] = ("X one", True, clock.now())
    public_pages.render_all(migrated, config)
    before = rows(migrated)["/x"]
    shown.targets["x"] = ("X two", True, clock.now())
    renders = shown.renders
    with migrated.connect() as holder, holder.begin():
        public_pages._target_lock(holder, f"public_page:{NOTE}:x")
        late = migrated.connect()
        late_transaction = late.begin()
        try:
            # Outside the expected error: a failure here is a broken test, not the lock timeout.
            short_lock_wait(late)
            with pytest.raises(OperationalError) as refused:
                public_pages.refresh(late, config, NOTE, "x")
            assert lock_refused(
                migrated, refused.value
            ), "the render failed, but not on the lock timeout"
        finally:
            late_transaction.rollback()
            late.invalidate()
            late.close()
    after = rows(migrated)["/x"]
    assert shown.renders == renders, "the timed-out render ran"
    assert (after.body, after.etag, after.rendered_at) == (
        before.body,
        before.etag,
        before.rendered_at,
    )
    public_pages.render_all(migrated, config)
    assert "X two" in rows(migrated)["/x"].body


def test_the_lock_row_is_made_once_and_holds_no_target_id(
    migrated: Engine,
    settings: Settings,
    shown: Shown,  # noqa: F811
) -> None:
    """MariaDB: the first lock of a target makes its row, keyed by the sha256 of the lock's
    name; later locks find it and make none. PostgreSQL and SQLite never write the table."""
    config = hub(settings)
    shown.targets["secret-target"] = ("S", True, clock.now())
    for _ in range(2):
        public_pages.render_all(migrated, config)
        with migrated.begin() as conn:
            public_pages.touch(conn, NOTE, "secret-target")
    with migrated.connect() as conn:
        found = list(conn.execute(select(t.public_page_lock.c.digest)).scalars())
    if migrated.dialect.name in ("mysql", "mariadb"):
        name = f"public_page:{NOTE}:secret-target"
        assert found == [hashlib.sha256(name.encode()).hexdigest()]
    else:
        assert found == []
    assert not any("secret-target" in digest for digest in found)
