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
    events.install(migrated)
    received: list[tuple[str, int]] = []
    unsubscribe = events.notifier.subscribe(lambda p, s: received.append((p, s)))
    yield received
    unsubscribe()


def test_waiters_hear_an_event_only_after_its_commit(
    migrated: Engine, heard: list[tuple[str, int]]
) -> None:
    project_id = factory.project(migrated)
    with migrated.begin() as conn:
        seq = events.emit(conn, project_id, "state_changed", ["all"], {"old": "build"})
        assert heard == []  # not before the commit
        visible = conn.execute(select(t.event.c.seq)).scalar()
        assert visible == seq
    assert heard == [(project_id, seq)]


def test_a_rolled_back_event_is_never_announced(
    migrated: Engine, heard: list[tuple[str, int]]
) -> None:
    project_id = factory.project(migrated)
    with pytest.raises(RuntimeError), migrated.begin() as conn:
        events.emit(conn, project_id, "state_changed", ["all"], {})
        raise RuntimeError("abort")
    with migrated.begin() as conn:
        seq = events.emit(conn, project_id, "state_changed", ["all"], {})
    assert heard == [(project_id, seq)]
    with migrated.connect() as conn:
        assert conn.execute(select(t.event.c.seq)).scalars().all() == [seq]


def test_actor_and_subject_are_recorded(migrated: Engine) -> None:
    project_id = factory.project(migrated)
    member = factory.membership(migrated, project_id, human_id=factory.human(migrated))
    actor = events.Actor(member, "ses-1", "crd-1", "signed", "Claude Code", "opus")
    with migrated.begin() as conn:
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
