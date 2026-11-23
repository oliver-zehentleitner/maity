"""Load on the read routes: reads of a large board running side by side do not hold up the
writes of the instance (hub/context/persistence.md, "A transaction that only reads takes no
write lock on SQLite").

A board of `MAITY_LOAD_UNIT` cards (1000 by default) is listed by `READERS` threads without
a pause, while one writer changes a card `WRITES` times. The writes must all commit, their
median under `WRITE_LIMIT`. Every read must answer 200, an exception in a reader thread is
kept and fails the test in the main thread, every reader must have ended, and at least one
read must have run beside the writes. The write maximum is printed, not checked, since on a
shared machine it is noise. The numbers are printed (`pytest -m load -s`) for the pull
request's before and after. On SQLite a read used to take the write lock for as long as it
read; on PostgreSQL a read never locked, and the test guards that it stays so."""

from __future__ import annotations

import os
import statistics
import threading
import time
from typing import Any

import pytest
from sqlalchemy import Engine, insert, select, update
from sqlalchemy.exc import OperationalError

from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_tasks import task

pytestmark = pytest.mark.load

UNIT = int(os.environ.get("MAITY_LOAD_UNIT", "1000"))
READERS = 4
WRITES = 20
WRITE_LIMIT = 2.0  # seconds; the busy timeout is 5


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def seed_cards(engine: Engine, template_id: str, count: int) -> None:
    """`count` copies of one real card, in the same project and column."""
    with engine.begin() as conn:
        card = conn.execute(select(t.card).where(t.card.c.id == template_id)).one()
        rows = [
            {**card._mapping, "id": f"tsk-l{n:011d}", "title": f"Load card {n}", "rank": None}
            for n in range(count)
        ]
        conn.execute(insert(t.card), rows)


def test_writes_stay_quick_while_a_large_board_is_read(owner: flow.Human, migrated: Engine) -> None:
    target = task(owner)
    seed_cards(migrated, target["id"], UNIT - 1)
    path = "/projects/maintainer/maity/tasks?limit=50"

    single = []
    for _ in range(5):
        began = time.perf_counter()
        assert owner.get(path).status_code == 200
        single.append(time.perf_counter() - began)

    stop = threading.Event()
    reads: list[float] = []
    failed_reads: list[int] = []
    raised: list[BaseException] = []  # an exception in a reader thread, kept for the main thread

    def read() -> None:
        try:
            while not stop.is_set():
                began = time.perf_counter()
                status = owner.get(path).status_code
                if status == 200:
                    reads.append(time.perf_counter() - began)
                else:
                    failed_reads.append(status)
        except BaseException as error:  # noqa: BLE001 - asserted in the main thread
            raised.append(error)

    readers = [threading.Thread(target=read) for _ in range(READERS)]
    for reader in readers:
        reader.start()
    writes: list[float] = []
    failed_writes = 0
    began_all = time.perf_counter()
    try:
        time.sleep(0.5)  # the readers are under way
        for n in range(WRITES):
            began = time.perf_counter()
            try:
                with migrated.begin() as conn:
                    conn.execute(
                        update(t.card)
                        .where(t.card.c.id == target["id"])
                        .values(title=f"written {n}")
                    )
                writes.append(time.perf_counter() - began)
            except OperationalError:
                failed_writes += 1
            time.sleep(0.05)
    finally:
        stop.set()
        for reader in readers:
            reader.join(30)
    window = time.perf_counter() - began_all
    shown: dict[str, Any] = {
        "engine": migrated.dialect.name,
        "cards": UNIT,
        "single_read_median_ms": round(statistics.median(single) * 1000, 1),
        "reads_in_window": len(reads),
        "reads_per_s": round(len(reads) / window, 1),
        "read_median_ms": round(statistics.median(reads) * 1000, 1) if reads else None,
        "write_median_ms": round(statistics.median(writes) * 1000, 1) if writes else None,
        "write_p90_ms": (
            round(statistics.quantiles(writes, n=10)[-1] * 1000, 1) if len(writes) > 1 else None
        ),
        "write_max_ms": round(max(writes) * 1000, 1) if writes else None,
        "failed_writes": failed_writes,
        "failed_reads": len(failed_reads),
    }
    shown["reader_errors"] = [repr(error) for error in raised]
    shown["readers_alive"] = sum(reader.is_alive() for reader in readers)
    print(f"\nLOAD read routes: {shown}")
    assert not shown["readers_alive"], shown
    assert not raised, shown
    assert failed_writes == 0, shown
    assert not failed_reads, shown
    assert reads, shown  # the reads ran side by side with the writes
    assert statistics.median(writes) < WRITE_LIMIT, shown
