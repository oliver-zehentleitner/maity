"""The projects an organisation owns, and its owners in them (docs/api.md §6.26,
"Organisation owners in its projects").

The hub keeps every owner of an organisation a member with trust `owner` of every project the
organisation owns, archived ones included:

- an owner who is no member joins (`member_joined`, trust `owner`): the membership is marked
  `org_keep = 'created'`, and ends as a removal does when they stop being an owner;
- an owner who is a member with a lower trust is raised to `owner` (`member_updated`, `changed:
  ["trust"]`): `org_keep = 'raised'` with the earlier trust in `org_keep_trust`, which they
  return to;
- an owner who holds trust `owner` already keeps it, and nothing is marked.

All of it runs under the organisation's row lock (`orgs.lock`), taken before any project's, in
the transaction of the change that made someone an owner, ended their ownership, or moved a
project in or out.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.events import Actor, emit, lock_project
from maity_hub.views import member_view

HUB = Actor(None)  # the events name no actor: the hub's own change
BROADCAST = ["all"]


def projects_of(conn: Connection, org_id: str) -> list[Any]:
    """Every project the organisation owns, archived ones included, in a stable order."""
    return list(
        conn.execute(
            select(t.project).where(t.project.c.owner_org_id == org_id).order_by(t.project.c.id)
        ).all()
    )


def owners_of(conn: Connection, org_id: str) -> list[str]:
    return list(
        conn.execute(
            select(t.org_member.c.human_id)
            .where(t.org_member.c.org_id == org_id, t.org_member.c.role == "owner")
            .order_by(t.org_member.c.human_id)
        ).scalars()
    )


def _membership(conn: Connection, project_id: str, human_id: str) -> Any:
    return conn.execute(
        select(t.membership).where(
            t.membership.c.project_id == project_id,
            t.membership.c.human_id == human_id,
            t.membership.c.active.is_(True),
        )
    ).first()


def keep_owner(conn: Connection, project: Any, human_id: str) -> None:
    """Make `human_id`, an owner of the project's organisation, a member with trust `owner`."""
    lock_project(conn, project.id)
    found = _membership(conn, project.id, human_id)
    now = clock.now()
    if found is None:
        made = conn.execute(
            t.membership.insert().values(
                project_id=project.id,
                human_id=human_id,
                trust="owner",
                role="coder",
                areas=["/"],
                capabilities=[],
                joined_at=now,
                last_seen_at=now,
                org_keep="created",
            )
        )
        key = made.inserted_primary_key
        assert key is not None
        row = conn.execute(select(t.membership).where(t.membership.c.id == int(key[0]))).one()
        emit(
            conn,
            project.id,
            "member_joined",
            BROADCAST,
            member_view(conn, row),
            actor=HUB,
            subject=("member", human_id),
        )
        return
    if found.trust == "owner":
        return  # their own ownership, or one the hub keeps already
    conn.execute(
        update(t.membership)
        .where(t.membership.c.id == found.id)
        .values(trust="owner", org_keep="raised", org_keep_trust=found.trust)
    )
    _announce(conn, project, found.id, human_id)


def release_owner(conn: Connection, project: Any, human_id: str) -> None:
    """`human_id` is no owner of the project's organisation any more: the membership the hub
    created ends as a removal does, one it raised returns to its earlier trust, and one
    that held trust `owner` of its own stays."""
    found = _membership(conn, project.id, human_id)
    if found is None or found.org_keep is None:
        return
    lock_project(conn, project.id)
    if found.org_keep == "created":
        from maity_hub.routes.members import Change, apply_remove

        apply_remove(conn, Change(project, HUB, human_id, human_id, None, None), found)
        return
    conn.execute(
        update(t.membership)
        .where(t.membership.c.id == found.id)
        .values(trust=found.org_keep_trust, org_keep=None, org_keep_trust=None)
    )
    _announce(conn, project, found.id, human_id)


def _announce(conn: Connection, project: Any, membership_id: int, human_id: str) -> None:
    row = conn.execute(select(t.membership).where(t.membership.c.id == membership_id)).one()
    view = member_view(conn, row)
    emit(
        conn,
        project.id,
        "member_updated",
        BROADCAST,
        {**view, "changed": ["trust"]},
        actor=HUB,
        subject=("member", human_id),
    )


def keep_in_all(conn: Connection, org_id: str, human_id: str) -> None:
    """A human became an owner of the organisation: every project it owns now."""
    for project in projects_of(conn, org_id):
        keep_owner(conn, project, human_id)


def release_in_all(conn: Connection, org_id: str, human_id: str) -> None:
    """A human stopped being an owner of the organisation: every project it owns."""
    for project in projects_of(conn, org_id):
        release_owner(conn, project, human_id)


def keep_all_owners(conn: Connection, org_id: str, project: Any) -> None:
    """A project was created in or moved into the organisation: every owner of it."""
    for human_id in owners_of(conn, org_id):
        keep_owner(conn, project, human_id)
