"""The rules of requests to humans: addressing, who may see and answer them (docs/api.md §7).

Pure decisions over rows; `routes/requests.py` applies them in a transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, select

from maity_hub import proposals
from maity_hub import tables as t
from maity_hub.access import Membership
from maity_hub.scopes import ROLES, has_scope

CLASSES = ("decision", "consent", "contract", "info")
PRIORITIES = ("low", "normal", "high", "urgent")
PRIORITY_RANK = {p: i for i, p in enumerate(reversed(PRIORITIES))}  # urgent first
WHILE_OPEN = ("wait", "proceed_provisionally")
STATUSES = ("open", "answered", "withdrawn")
MAX_OPTIONS = 8
# `to` of a consent: a role or member that holds requests:answer (§7).
CONSENT_ROLES = ("admin", "proxy")


@dataclass(frozen=True)
class Addressee:
    kind: str  # member, role, owner, profile_owner, human
    member: int | None = None
    role: str | None = None
    profile: str | None = None  # profile_owner: the agent profile whose owner is meant
    human: str | None = None  # human: the human asked in person (§19.4)

    def text(self, conn: Connection) -> str:
        if self.kind == "owner":
            return "owner"
        if self.kind == "profile_owner":
            return f"profile_owner:{self.profile}"
        if self.kind == "human":
            return f"human:{self.human}"
        if self.kind == "role":
            return f"role:{self.role}"
        from maity_hub.views import principal_id

        member = principal_id(conn, self.member)
        assert member is not None
        return member


def addressee_of(row: Any) -> Addressee:
    return Addressee(row.to_kind, row.to_member, row.to_role, row.to_profile, row.to_human)


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


def forwarded(request: Any) -> bool:
    """Whether a request has left its `to` (§7): a member or the admins hold it now."""
    return request.holder_member is not None or bool(request.holder_pool)


def addressed_to(conn: Connection, request: Any, mine: Membership) -> bool:
    """`to=me`: whoever holds the request now (§7). Before a forward that is `to`;
    after one, the holding member, or every admin while the admins hold it as a pool;
    an earlier holder no longer."""
    if request.personal:
        return False
    if request.holder_member is not None:
        return bool(request.holder_member == mine.id)
    if request.holder_pool:
        return mine.role == "admin"
    return originally_addressed(conn, request, mine)


def originally_addressed(conn: Connection, request: Any, mine: Membership) -> bool:
    """`to` as filed: the caller's member id, `owner` for the owner, a role the caller
    holds, or the substitute covering the addressee (§6.12). A personal request is
    addressed to a human, never through a project (§7)."""
    if request.personal:
        return False
    return covers(request, mine) or _in_own_right(request, mine)


def _in_own_right(request: Any, mine: Membership) -> bool:
    if request.to_kind == "member":
        return bool(request.to_member == mine.id)
    if request.to_kind == "owner":
        return mine.role == "owner"
    return bool(request.to_role == mine.role)


def is_asker(request: Any, mine: Membership) -> bool:
    return mine.id in (request.asked_by, request.on_behalf_of)


def may_read(conn: Connection, request: Any, mine: Membership) -> bool:
    return (
        is_asker(request, mine)
        or addressed_to(conn, request, mine)
        or originally_addressed(conn, request, mine)  # it follows what it passed on
        or mine.may("requests:answer")
    )


def needs_a_human(request: Any, mine: Membership) -> str | None:
    """Why no agent answers this, or None: a request marked `humans_only` (§7), a
    placement's consent request under `spawn_consent_by: human` (§6.1, §15.6) — starting
    an agent spends compute and model budget, so no agent gives the go — and a proposal
    whose kind only a human answers (`proposals.Answerer`)."""
    if mine.kind != "agent":
        return None
    if request.humans_only:
        return "only a human answers or holds this request"
    if request.placement_id is not None and mine.project.spawn_consent_by == "human":
        return "under spawn_consent_by: human only a human answers this"
    rule = proposals.answerer(request)
    return rule.refusal if rule is not None and rule.humans_only else None


def answer_scope(request: Any) -> str:
    """The scope an answer needs: a proposal's kind may ask for more (§19.2)."""
    rule = proposals.answerer(request)
    return rule.scope if rule is not None else "requests:answer"


def may_answer(conn: Connection, request: Any, mine: Membership) -> bool:
    """`requests:answer` for every class (or the scope a proposal's kind asks for); the
    addressee in its own right for the others. Never an agent where the request needs a
    human, nobody where it carries a proposal of a kind the hub does not know, and nobody
    through a project for a personal request: its human answers it through
    `POST /requests/{id}/answer` (§7)."""
    if request.personal or not proposals.known(request):
        return False
    if needs_a_human(request, mine) is not None:
        return False
    if forwarded(request):  # once forwarded, only its holder answers (§7)
        return bool(request.holder_member == mine.id)
    if proposals.of(request) is not None:
        return mine.may(answer_scope(request))
    if mine.may("requests:answer"):
        return True
    return getattr(request, "class") != "consent" and addressed_to(conn, request, mine)


def covers(request: Any, mine: Membership) -> bool:
    """The caller is the substitute answering for the addressee (§6.12): it reads the
    request, finds it under `to=me` and answers as the addressee would."""
    cover: dict[str, Any] | None = getattr(request, "cover", None)
    return cover is not None and cover.get("by") == mine.principal_id


def answered_in_own_right(conn: Connection, request: Any, mine: Membership) -> bool:
    """Addressed to the caller itself, not only through a cover it holds."""
    return not request.personal and _in_own_right(request, mine)


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


def humans_only(request: Any) -> bool:
    """`humans_only` as the request shows it: the flag, or a proposal's kind that only a
    human answers (§2.3)."""
    rule = proposals.answerer(request)
    return bool(request.humans_only) or (rule is not None and rule.humans_only)
