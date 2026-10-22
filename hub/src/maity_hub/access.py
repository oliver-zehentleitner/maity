"""Who may touch which project (docs/api.md §2.3).

A project the caller is not a member of does not exist for it: `not_found`,
never `forbidden`, so that projects cannot be enumerated. Within a project
the membership's role decides, by scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, select

from maity_hub import tables as t
from maity_hub.auth.caller import Caller
from maity_hub.errors import forbidden, not_found
from maity_hub.scopes import has_scope


@dataclass(frozen=True)
class Membership:
    """The caller's own membership in one project, with the project row."""

    project: Any
    row: Any
    kind: str  # human, agent

    @property
    def id(self) -> int:
        membership_id: int = self.row.id
        return membership_id

    @property
    def role(self) -> str:
        role: str = self.row.role
        return role

    @property
    def principal_id(self) -> str:
        principal: str = self.row.agent_id or self.row.human_id
        return principal

    def may(self, scope: str) -> bool:
        return has_scope(self.role, self.kind, scope)

    def require(self, scope: str) -> None:
        if not self.may(scope):
            raise forbidden(scope)


def membership(conn: Connection, caller: Caller, slug: str) -> Membership:
    project = conn.execute(select(t.project).where(t.project.c.slug == slug)).first()
    if project is None:
        raise not_found()
    # An agent credential belongs to one membership, of one project (§2.2): the
    # profile's memberships elsewhere are not reachable through it.
    principal = (
        t.membership.c.id == caller.membership_id
        if caller.kind == "agent"
        else t.membership.c.human_id == caller.human_id
    )
    row = conn.execute(
        select(t.membership).where(
            t.membership.c.project_id == project.id,
            principal,
            t.membership.c.active.is_(True),
        )
    ).first()
    if row is None:
        raise not_found()
    return Membership(project, row, caller.kind)


def member_row_or_removed(conn: Connection, project_id: str, principal_id: str) -> Any:
    """The active membership, else the most recently removed one: a removed member
    stays addressable for a repeated DELETE and its credentials (§6.2, §10)."""
    row = conn.execute(
        select(t.membership)
        .where(
            t.membership.c.project_id == project_id,
            (t.membership.c.agent_id == principal_id) | (t.membership.c.human_id == principal_id),
        )
        .order_by(t.membership.c.active.is_(True).desc(), t.membership.c.joined_at.desc())
    ).first()
    if row is None:
        raise not_found()
    return row


def member_row(conn: Connection, project_id: str, principal_id: str) -> Any:
    """The active membership of a principal (`hum-…` or `agt-…`) in a project."""
    row = conn.execute(
        select(t.membership).where(
            t.membership.c.project_id == project_id,
            (t.membership.c.agent_id == principal_id) | (t.membership.c.human_id == principal_id),
            t.membership.c.active.is_(True),
        )
    ).first()
    if row is None:
        raise not_found()
    return row
