"""`GET /projects/{owner}/{slug}` resolves the project, the caller's membership and the
owner's handle once each (tsk-6srccd2r1h62). The view's storage figures and restricted
setting use the membership the route read, instead of resolving the project again."""

from __future__ import annotations

import re
import traceback
from collections import Counter
from typing import Any

import pytest
from sqlalchemy import Engine, event, select, update

from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory

PROJECT = "/projects/maintainer/maity"
# namespace.resolve reads the whole project row; owner_of reads the owner's handle.
_RESOLVE = re.compile(r"^\s*SELECT project\.id, project\.owner_id\b", re.IGNORECASE)
_OWNER = re.compile(r"^\s*SELECT coalesce\(human\.handle, org\.handle\)", re.IGNORECASE)
_MEMBERSHIP = re.compile(r"^\s*SELECT membership\.id, membership\.project_id\b", re.IGNORECASE)


def _reads(engine: Engine, call: Any) -> Counter[str]:
    """The route's own reads: statements sent from inside `get_project`. Authentication
    reads the project and a membership of its own for an agent (its lease, its project);
    those are not this route's."""
    seen: Counter[str] = Counter()

    def count(_conn: Any, _cursor: Any, statement: str, *_: Any) -> None:
        if not any(frame.name == "get_project" for frame in traceback.extract_stack()):
            return
        for name, pattern in (
            ("resolve", _RESOLVE),
            ("owner", _OWNER),
            ("membership", _MEMBERSHIP),
        ):
            if pattern.match(statement):
                seen[name] += 1

    event.listen(engine, "before_cursor_execute", count)
    try:
        response = call()
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert response.status_code == 200, response.text
    return seen


@pytest.mark.parametrize("role", ["owner", "member"])
def test_a_project_read_resolves_project_membership_and_owner_once(
    make_client: ClientFactory, migrated: Engine, role: str
) -> None:
    # The owner has project:admin (the storage figures are read); an agent member has not.
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    reader: Any = owner if role == "owner" else flow.agent(make_client, owner)
    reads = _reads(migrated, lambda: reader.get(PROJECT))
    assert (reads["resolve"], reads["membership"], reads["owner"]) == (1, 1, 1), reads


def test_a_view_without_the_membership_reads_it_once_also_when_there_is_none(
    make_client: ClientFactory, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    # #1548 review: a route that calls `_view` without the membership (here the create) has
    # it read once, and the storage figures and the restricted setting use that read, None
    # included; neither reads it again.
    from maity_hub.routes import projects

    calls: list[str] = []

    def none(_conn: Any, project: Any, _request: Any) -> None:
        calls.append(project.id)
        return None

    monkeypatch.setattr(projects, "_reader", none)
    owner = flow.human(make_client, migrated)
    created = flow.project(owner)
    assert len(calls) == 1, calls
    assert created["attachments"] is None  # no membership: no storage figures


def test_the_view_follows_the_membership_the_read_started_with(
    make_client: ClientFactory, migrated: Engine
) -> None:
    # #1548, the project lead's decision (hub/context/persistence.md): an admin demoted by a
    # commit after the route read their membership still gets the admin fields in this answer,
    # which matches the role the read passed on; the next read follows the demotion.
    if migrated.dialect.name == "sqlite":
        pytest.skip("a commit between two statements of a call needs a second writer")
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    admin = flow.human(make_client, migrated, "someone")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    member_id = factory.membership(migrated, project_id, "admin", human_id=admin.id)
    fired: list[str] = []

    def demote(_conn: Any, _cursor: Any, statement: str, *_: Any) -> None:
        # Another session demotes the admin right after the route's membership read.
        if fired or not any(f.name == "get_project" for f in traceback.extract_stack()):
            return
        if _MEMBERSHIP.match(statement):
            fired.append(statement)
            with migrated.begin() as other:
                other.execute(
                    update(t.membership)
                    .where(t.membership.c.id == member_id)
                    .values(trust="member", role="coder", role_base="coder")
                )

    event.listen(migrated, "after_cursor_execute", demote)
    try:
        answered = admin.get(PROJECT)
    finally:
        event.remove(migrated, "after_cursor_execute", demote)
    assert fired, "the route read no membership"
    assert answered.status_code == 200, answered.text
    assert answered.json()["attachments"] is not None  # the admin the read passed on
    after = admin.get(PROJECT)
    assert after.status_code == 200 and after.json()["attachments"] is None
