"""The event writer: seq order and the post-commit signal (docs/architecture.md §7)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, select

from maity_hub import events
from maity_hub import tables as t
from tests import factory


@pytest.fixture
def heard(migrated: Engine) -> Iterator[list[tuple[str, int]]]:
    received: list[tuple[str, int]] = []
    unsubscribe = events.notifier.subscribe(lambda p, s: received.append((p, s)))
    yield received
    unsubscribe()


def test_a_woken_reader_on_another_connection_finds_the_row(migrated: Engine) -> None:
    project_id = factory.project(migrated)
    seen: list[int | None] = []

    def reader(_project: str, seq: int) -> None:
        with migrated.connect() as other:  # a waiter's own connection
            seen.append(other.execute(select(t.event.c.seq).where(t.event.c.seq == seq)).scalar())

    unsubscribe = events.notifier.subscribe(reader)
    try:
        with events.transaction(migrated) as conn:
            seq = events.emit(conn, project_id, "state_changed", ["all"], {"old": "build"})
            assert seen == []  # not before the commit
    finally:
        unsubscribe()
    assert seen == [seq]


def test_emit_outside_the_transaction_helper_is_refused(migrated: Engine) -> None:
    project_id = factory.project(migrated)
    with pytest.raises(RuntimeError, match="events.transaction"), migrated.begin() as conn:
        events.emit(conn, project_id, "state_changed", ["all"], {})


def test_a_rolled_back_event_is_never_announced(
    migrated: Engine, heard: list[tuple[str, int]]
) -> None:
    project_id = factory.project(migrated)
    with pytest.raises(RuntimeError, match="abort"), events.transaction(migrated) as conn:
        events.emit(conn, project_id, "state_changed", ["all"], {})
        raise RuntimeError("abort")
    with events.transaction(migrated) as conn:
        seq = events.emit(conn, project_id, "state_changed", ["all"], {})
    assert heard == [(project_id, seq)]
    with migrated.connect() as conn:
        assert conn.execute(select(t.event.c.seq)).scalars().all() == [seq]


def test_actor_and_subject_are_recorded(migrated: Engine) -> None:
    project_id = factory.project(migrated)
    member = factory.membership(migrated, project_id, human_id=factory.human(migrated))
    actor = events.Actor(member, "ses-1", "crd-1", "signed", "Claude Code", "opus")
    with events.transaction(migrated) as conn:
        events.emit(
            conn,
            project_id,
            "task_claimed",
            ["member:x"],
            {},
            actor=actor,
            subject=("task", "tsk-1"),
        )
    with migrated.connect() as conn:
        row = conn.execute(select(t.event)).one()
    assert (row.actor_membership, row.actor_session_id, row.actor_credential_id) == (
        member,
        "ses-1",
        "crd-1",
    )
    assert (row.actor_via, row.actor_harness, row.actor_model) == ("signed", "Claude Code", "opus")
    assert (row.subject_type, row.subject_id, row.redacted) == ("task", "tsk-1", False)


def test_at_never_runs_backwards_within_a_project(migrated: Engine) -> None:
    """A clock step back (or a replica whose clock is behind) gives a later event the
    earlier one's `at`, never an earlier one; another project keeps its own (§18.2)."""
    from datetime import UTC, datetime, timedelta

    from maity_hub import clock

    project_id, other = factory.project(migrated), factory.project(migrated, "other")
    start = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
    for minutes, target in ((10, project_id), (0, project_id), (5, other), (12, project_id)):

        def now(at: datetime = start + timedelta(minutes=minutes)) -> datetime:
            return at

        clock.set_source(now)
        with events.transaction(migrated) as conn:
            events.emit(conn, target, "state_changed", ["all"], {})
    with migrated.connect() as conn:
        rows = conn.execute(
            select(t.event.c.project_id, t.event.c.at).order_by(t.event.c.seq)
        ).all()
    ats = [r.at for r in rows if r.project_id == project_id]
    assert ats == [start + timedelta(minutes=m) for m in (10, 10, 12)]
    assert [r.at for r in rows if r.project_id == other] == [start + timedelta(minutes=5)]
