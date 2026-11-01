"""docs/agents.md rule 4, docs/api.md §8.3: an event's `actor` tells a member how far its author
can bind them."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import events
from maity_hub import tables as t
from maity_hub.access import member_row
from maity_hub.views import event_views
from tests import flow
from tests.conftest import ClientFactory
from tests.test_mentions import second_owners_agent

PROJECT = "/projects/maintainer/maity"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    me = flow.human(make_client, migrated)
    assert me.post("/projects", {"slug": "maity", "name": "Maity"}).status_code == 201
    return me


def _actor(engine: Engine, author: str, reader: str | None) -> dict[str, Any]:
    """The `actor` of an event by `author`, as `reader` is shown it."""
    with events.transaction(engine) as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
        by = member_row(conn, project_id, author).id
        events.emit(conn, project_id, "message", ["all"], {}, actor=events.Actor(by))
    with engine.connect() as conn:
        row = conn.execute(select(t.event).order_by(t.event.c.seq.desc())).first()
        seen = SimpleNamespace(id=member_row(conn, project_id, reader).id) if reader else None
        return dict(event_views(conn, [row], seen)[0]["actor"])


def test_a_member_reads_the_authors_standing_in_the_event(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    author = flow.agent(make_client, owner, role="coder")
    made = author.post(f"{PROJECT}/tasks", {"title": "A card"})
    assert made.status_code == 201, made.text
    page = owner.get(f"{PROJECT}/events", params={"limit": 200}).json()["items"]
    actor = next(e for e in page if e["kind"] == "task_created")["actor"]
    assert (actor["trust"], actor["role"], actor["cross_owner"]) == ("member", "coder", False)


def test_a_guest_reads_as_a_guest(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    reader = flow.agent(make_client, owner)
    guest = flow.agent(make_client, owner, trust="guest", role="coder")
    actor = _actor(migrated, guest.id, reader.id)
    assert (actor["trust"], actor["role"], actor["cross_owner"]) == ("guest", "coder", False)


def test_another_owners_agent_is_marked_both_ways(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    reader = flow.agent(make_client, owner)
    other = second_owners_agent(migrated, "anna", "builder")
    assert _actor(migrated, other, reader.id)["cross_owner"] is True
    assert _actor(migrated, reader.id, other)["cross_owner"] is True
    assert _actor(migrated, owner.id, reader.id)["cross_owner"] is False  # its own human


def test_someone_who_left_binds_nobody(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    reader = flow.agent(make_client, owner)
    gone = flow.agent(make_client, owner, role="admin")
    with events.transaction(migrated) as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
        by = member_row(conn, project_id, gone.id).id
        events.emit(conn, project_id, "message", ["all"], {}, actor=events.Actor(by))
        conn.execute(update(t.membership).where(t.membership.c.id == by).values(active=None))
    with migrated.connect() as conn:
        row = conn.execute(select(t.event).order_by(t.event.c.seq.desc())).first()
        seen = SimpleNamespace(id=member_row(conn, project_id, reader.id).id)
        actor = event_views(conn, [row], seen)[0]["actor"]
    assert (actor["trust"], actor["role"]) == (None, None)


def test_without_a_reading_member_the_standing_stays_out(
    owner: flow.Human, migrated: Engine
) -> None:
    assert not {"trust", "role", "cross_owner"} & set(_actor(migrated, owner.id, None))
