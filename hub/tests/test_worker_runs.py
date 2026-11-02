"""A worker's pass once per interval, whichever pod is first (hub/context/replicas.md 24489a9c)."""

from __future__ import annotations

import threading
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select, text, update

import maity_hub
from maity_hub import tables as t
from maity_hub import worker_runs
from maity_hub.worker_runs import claim

HOUR = 3600.0


def _ages(engine: Engine, name: str, *, started: float = 0, lease: float | None = None) -> None:
    """Move the row back in time, by seconds on the database's clock."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE worker_run SET started_at = started_at - make_interval(secs => :s) "
                "WHERE name = :n"
            ),
            {"s": started, "n": name},
        )
        if lease is not None:
            conn.execute(
                text(
                    "UPDATE worker_run SET lease_until = lease_until - make_interval(secs => :s) "
                    "WHERE name = :n"
                ),
                {"s": lease, "n": name},
            )


def _row(engine: Engine, name: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(select(t.worker_run).where(t.worker_run.c.name == name)).one()


@pytest.fixture
def replicas(migrated: Engine) -> Engine:
    if migrated.dialect.name != "postgresql":
        pytest.skip("only PostgreSQL runs replicas")
    return migrated


def test_every_other_database_runs_every_pass_and_writes_nothing(migrated: Engine) -> None:
    if migrated.dialect.name == "postgresql":
        pytest.skip("PostgreSQL claims")
    for _ in range(2):
        with claim(migrated, "w", HOUR) as held:
            assert held is not None and not held.is_set()
    with migrated.connect() as conn:
        assert conn.execute(select(t.worker_run)).all() == []


def test_the_first_pod_has_the_pass_and_the_other_is_refused(replicas: Engine) -> None:
    with claim(replicas, "w", HOUR, pod="a") as first:
        assert first is not None
        with claim(replicas, "w", 0, pod="b") as second:  # interval over, the lease still held
            assert second is None
    assert _row(replicas, "w").pod == "a"


def test_a_finished_pass_refuses_until_its_interval_is_over(replicas: Engine) -> None:
    with claim(replicas, "w", HOUR, pod="a"):
        pass
    with claim(replicas, "w", HOUR, pod="b") as refused:
        assert refused is None
    _ages(replicas, "w", started=HOUR + 1)
    with claim(replicas, "w", HOUR, pod="b") as taken:
        assert taken is not None
    assert _row(replicas, "w").pod == "b"


def test_a_pass_shorter_than_its_lease_leaves_the_next_to_the_interval(replicas: Engine) -> None:
    """Without the release an interval under five minutes would wait for the lease every time."""
    with claim(replicas, "w", 0, pod="a"):
        pass
    with claim(replicas, "w", 0, pod="b") as taken:
        assert taken is not None


def test_a_failed_pass_is_released_and_its_error_goes_on_up(replicas: Engine) -> None:
    with pytest.raises(ValueError), claim(replicas, "w", 0, pod="a"):
        raise ValueError
    with claim(replicas, "w", 0, pod="b") as taken:
        assert taken is not None


def test_a_dead_pods_lease_expires(replicas: Engine) -> None:
    """A pod that dies never releases: the context is left open, as it would be."""
    assert worker_runs._take(replicas, "w", HOUR, "dead")
    with claim(replicas, "w", 0, pod="b") as refused:
        assert refused is None
    _ages(replicas, "w", lease=worker_runs.LEASE.total_seconds() + 1)
    with claim(replicas, "w", 0, pod="b") as taken:
        assert taken is not None


def test_a_long_pass_renews_its_lease(replicas: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_runs, "RENEW_EVERY", 0.0)
    with claim(replicas, "w", 0, pod="a") as held:
        assert held is not None
        _ages(replicas, "w", lease=worker_runs.LEASE.total_seconds() - 1)
        before = _row(replicas, "w").lease_until
        assert not held.is_set()
        assert _row(replicas, "w").lease_until - before > timedelta(minutes=4)


def test_a_pass_whose_renewal_finds_another_pod_stops(
    replicas: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(worker_runs, "RENEW_EVERY", 0.0)
    with claim(replicas, "w", 0, pod="a") as held:
        assert held is not None
        with replicas.begin() as conn:
            conn.execute(update(t.worker_run).values(pod="b"))
        assert held.is_set()
        assert held.is_set()  # and stays stopped, with no further write
    assert _row(replicas, "w").pod == "b"  # its end leaves the other pod's lease alone
    assert _row(replicas, "w").lease_until > _row(replicas, "w").started_at


def test_stopping_the_worker_stops_the_pass(replicas: Engine) -> None:
    stop = threading.Event()
    with claim(replicas, "w", 0, stop, pod="a") as held:
        assert held is not None and not held.is_set()
        stop.set()
        assert held.is_set()


def test_of_many_pods_at_once_one_has_the_pass(replicas: Engine) -> None:
    barrier = threading.Barrier(8)
    won: list[str] = []

    def race(pod: str) -> None:
        barrier.wait()
        if worker_runs._take(replicas, "w", HOUR, pod):
            won.append(pod)

    threads = [threading.Thread(target=race, args=(f"pod-{n}",)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(won) == 1


def test_every_worker_claims_its_pass() -> None:
    """A new worker fails here until it follows the rule, or is named as staying per pod."""
    package = Path(maity_hub.__file__).parent
    workers = [p for p in package.rglob("*.py") if "\nclass Worker" in p.read_text()]
    assert len(workers) == 15
    assert [p.name for p in workers if "worker_runs.claim(" not in p.read_text()] == []
