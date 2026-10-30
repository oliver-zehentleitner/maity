"""The hub's generated text is a rules input (docs/api.md §6.9, tsk-n6b8q0tz9yt2): a start
with other text bumps every project's `rules_version` once."""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, select

from maity_hub import rules
from maity_hub import tables as t
from maity_hub.events import transaction
from tests import factory, flow
from tests.conftest import ClientFactory


def version(engine: Engine, project_id: str) -> int:
    with engine.connect() as conn:
        found: int = conn.execute(
            select(t.project.c.rules_version).where(t.project.c.id == project_id)
        ).scalar_one()
    return found


def sync(engine: Engine) -> int:
    with transaction(engine) as conn:
        return rules.sync_text(conn)


def test_the_digest_is_stable_and_follows_the_text(monkeypatch: pytest.MonkeyPatch) -> None:
    digest = rules.text_digest()
    assert digest == rules.text_digest() and len(digest) == 64
    monkeypatch.setattr(rules, "DUTY_SELF", rules.DUTY_SELF + " Another sentence.")
    assert rules.text_digest() != digest
    monkeypatch.undo()
    assert rules.text_digest() == digest


def test_a_project_that_never_counted_the_text_is_bumped_once(migrated: Engine) -> None:
    project = factory.project(migrated, "p")
    assert version(migrated, project) == 1
    assert sync(migrated) == 1
    assert version(migrated, project) == 2
    with migrated.connect() as conn:
        event = conn.execute(
            select(t.event).where(t.event.c.kind == "rules_changed").order_by(t.event.c.seq.desc())
        ).first()
        seq = conn.execute(
            select(t.project.c.rules_changed_seq).where(t.project.c.id == project)
        ).scalar_one()
    assert event is not None and event.audience == ["all"] and event.seq == seq
    assert event.payload == {"version": 2, "reason": "generated text"}
    assert sync(migrated) == 0 and version(migrated, project) == 2  # the second start: nothing


def test_changed_text_bumps_every_project_again(
    migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = factory.project(migrated, "a"), factory.project(migrated, "b")
    assert sync(migrated) == 2
    monkeypatch.setattr(rules, "KEEP_THE_WHY", rules.KEEP_THE_WHY + " Then say so.")
    assert sync(migrated) == 2
    assert (version(migrated, first), version(migrated, second)) == (3, 3)
    assert sync(migrated) == 0


def test_a_new_project_starts_with_the_current_digest(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    with migrated.connect() as conn:
        row = conn.execute(select(t.project)).one()
    assert row.rules_text_digest == rules.text_digest() and row.rules_version == 1
    assert sync(migrated) == 0 and version(migrated, row.id) == 1


def test_an_agent_with_a_current_cursor_reads_the_new_text_after_a_bump(
    make_client: ClientFactory, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    agent = flow.agent(make_client, owner)
    first = agent.resume().json()
    monkeypatch.setattr(rules, "DUTY_SELF", rules.DUTY_SELF + " More.")
    assert sync(migrated) == 1
    again = agent.resume(cursor=first["events"]["cursor"]).json()
    assert again["rules"]["version"] == first["rules"]["version"] + 1
    assert again["rules"]["changed"] is True and "More." in again["rules"]["markdown"]


def test_a_hub_start_counts_the_text_once_for_a_project_that_never_did(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """The lifespan calls `sync_text`: a project whose digest is null is bumped by the start
    of the app and not again by the next one."""
    project = factory.project(migrated, "p")
    assert version(migrated, project) == 1
    make_client()  # the app starts: the lifespan runs
    assert version(migrated, project) == 2
    make_client()
    assert version(migrated, project) == 2
    with migrated.connect() as conn:
        digest = conn.execute(
            select(t.project.c.rules_text_digest).where(t.project.c.id == project)
        ).scalar_one()
    assert digest == rules.text_digest()
