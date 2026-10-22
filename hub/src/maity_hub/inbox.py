"""The rules of requests to humans: addressing, who may see and answer them (docs/api.md §7).

Pure decisions over rows; `routes/requests.py` applies them in a transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, select

from maity_hub import tables as t
from maity_hub.access import Membership
from maity_hub.scopes import ROLES, has_scope

CLASSES = ("decision", "consent", "contract", "info")
PRIORITIES = ("low", "normal", "high", "urgent")
PRIORITY_RANK = {p: i for i, p in enumerate(reversed(PRIORITIES))}  # urgent first
WHILE_OPEN = ("wait", "proceed_provisionally")
STATUSES = ("open", "answered", "withdrawn")
MAX_OPTIONS = 8
CONSENT_REPLIES = [{"id": "go", "label": "go"}, {"id": "no", "label": "no"}]
# `to` of a consent: a role or member that holds requests:answer (§7).
CONSENT_ROLES = ("admin", "proxy")


@dataclass(frozen=True)
class Addressee:
    kind: str  # member, role, owner
    member: int | None = None
    role: str | None = None

    def text(self, conn: Connection) -> str:
        if self.kind == "owner":
            return "owner"
        if self.kind == "role":
            return f"role:{self.role}"
        from maity_hub.views import principal_id

        member = principal_id(conn, self.member)
        assert member is not None
        return member


def addressee_of(row: Any) -> Addressee:
    return Addressee(row.to_kind, row.to_member, row.to_role)


def replies(class_: str, options: list[dict[str, Any]]) -> list[dict[str, str]]:
    """The answers the inbox renders as buttons: the options, or go/no for a bare consent."""
    if class_ == "consent" and not options:
        return list(CONSENT_REPLIES)
    return [{"id": o["id"], "label": o["label"]} for o in options]


def owner_membership(conn: Connection, project_id: str) -> Any:
    return conn.execute(
        select(t.membership)
        .where(
            t.membership.c.project_id == project_id,
            t.membership.c.role == "owner",
            t.membership.c.active.is_(True),
        )
        .order_by(t.membership.c.joined_at, t.membership.c.id)
    ).first()


def addressed_to(conn: Connection, request: Any, mine: Membership) -> bool:
    """`to=me`: the caller's member id, `owner` for the owner, a role the caller holds."""
    if request.to_kind == "member":
        return bool(request.to_member == mine.id)
    if request.to_kind == "owner":
        return mine.role == "owner"
    return bool(request.to_role == mine.role)


def is_asker(request: Any, mine: Membership) -> bool:
    return mine.id in (request.asked_by, request.on_behalf_of)


def may_read(conn: Connection, request: Any, mine: Membership) -> bool:
    return (
        is_asker(request, mine) or addressed_to(conn, request, mine) or mine.may("requests:answer")
    )


def needs_a_human(request: Any, mine: Membership) -> bool:
    """A placement's consent request under `spawn_consent_by: human` (§6.1, §15.6):
    starting an agent spends compute and model budget, so no agent gives the go."""
    return (
        mine.kind == "agent"
        and request.placement_id is not None
        and mine.project.spawn_consent_by == "human"
    )


def may_answer(conn: Connection, request: Any, mine: Membership) -> bool:
    """`requests:answer` for every class; the addressee in its own right for the others.
    Never an agent where the request needs a human."""
    if needs_a_human(request, mine):
        return False
    if mine.may("requests:answer"):
        return True
    return getattr(request, "class") != "consent" and addressed_to(conn, request, mine)


def answered_in_own_right(conn: Connection, request: Any, mine: Membership) -> bool:
    return addressed_to(conn, request, mine)


def consent_target_ok(conn: Connection, project_id: str, to: Addressee) -> bool:
    """A consent goes only to a role that may answer it (§7, architecture §5)."""
    if to.kind == "owner":
        return True
    if to.kind == "role":
        return to.role in CONSENT_ROLES or to.role == "owner"
    row = conn.execute(select(t.membership).where(t.membership.c.id == to.member)).one()
    kind = "agent" if row.agent_id else "human"
    return has_scope(row.role, kind, "requests:answer")


def valid_role(role: str) -> bool:
    return role in ROLES
