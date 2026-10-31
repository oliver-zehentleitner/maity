"""A `reports_to` across owners takes effect only with both owners' consent (docs/api.md §6.2,
"Across owners").

The edge is cross-owner when the subordinate is an agent and `reports_to` names an agent of
another owner or a human who is not its owner. It does not apply at once: the hub files one
`consent` request per owner still to consent, a personal request addressed to that human in
person (`to: human:<id>`, §7), as the receiver's of a project transfer is, so that an owner who is
no member of the project answers it with `POST /requests/{id}/answer` and the project's routes
stay closed to them. The requests of one edge are a pair (`proposal.requests`): a `go` on the
last open one sets the edge, a `no` or a withdrawal of either withdraws the other.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sqlalchemy import Connection, select, update

from maity_hub import namespace, proposals
from maity_hub import tables as t
from maity_hub.access import Membership
from maity_hub.auth.caller import Caller
from maity_hub.events import Actor, lock_project
from maity_hub.views import principal_id

KIND = "cross_owner_reports_to"
# What the hub itself withdraws a pair for.
HUB_REASONS = ("superseded", "member_removed", "owner_not_member")


def owner_of(conn: Connection, row: Any) -> str | None:
    """The human behind a member: an agent's profile owner, a human itself."""
    if row.agent_id is None:
        return str(row.human_id)
    owner = conn.execute(
        select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == row.agent_id)
    ).scalar()
    return None if owner is None else str(owner)


def new_agent(agent_id: str | None) -> Any:
    """A stand-in for the agent a join is about to create, for `owners`."""
    return SimpleNamespace(agent_id=agent_id, human_id=None)


def owners(conn: Connection, target: Any, boss: Any) -> tuple[str, str] | None:
    """(the subordinate's owner, the boss's side) when the edge is cross-owner, else None:
    a human's own `reports_to` is never one, nor an edge to its owner or to another agent of
    that owner (§6.2)."""
    if target.agent_id is None:
        return None
    subordinate = owner_of(conn, target)
    side = owner_of(conn, boss)
    if subordinate is None or side is None or subordinate == side:
        return None
    return subordinate, side


def _handle(conn: Connection, row: Any) -> str:
    if row.agent_id is not None:
        found = conn.execute(
            select(t.agent_profile.c.handle).where(t.agent_profile.c.id == row.agent_id)
        ).scalar()
    else:
        found = conn.execute(select(t.human.c.handle).where(t.human.c.id == row.human_id)).scalar()
    return str(found or principal_id(conn, row.id))


def _human_handle(conn: Connection, human_id: str) -> str:
    return str(conn.execute(select(t.human.c.handle).where(t.human.c.id == human_id)).scalar())


def open_pair(conn: Connection, target_id: int, *, besides: str | None = None) -> list[Any]:
    """The open requests of a member's cross-owner edge, oldest first."""
    rows = conn.execute(
        select(t.request)
        .where(
            t.request.c.status == "open",
            t.request.c.proposal.is_not(None),
            t.request.c.personal.is_(True),
        )
        .order_by(t.request.c.created_at, t.request.c.id)
    ).all()
    return [
        r
        for r in rows
        if (r.proposal or {}).get("kind") == KIND
        and (r.proposal or {}).get("target") == target_id
        and r.id != besides
    ]


def withdraw_for_member(
    conn: Connection, member_id: int, actor: Actor | None, reason: str = "member_removed"
) -> None:
    """The removal of either member of an edge withdraws its requests (`member_removed`); so
    does an owner that is no member any more (`owner_not_member`, §6.2)."""
    from maity_hub.routes.requests import close_request

    rows = conn.execute(
        select(t.request)
        .where(
            t.request.c.status == "open",
            t.request.c.proposal.is_not(None),
            t.request.c.personal.is_(True),
        )
        .order_by(t.request.c.created_at, t.request.c.id)
    ).all()
    for row in rows:
        proposal = row.proposal or {}
        if proposal.get("kind") == KIND and member_id in (proposal["target"], proposal["boss"]):
            close_request(conn, row.id, "withdrawn", actor, reason=reason)


def join_waits(conn: Connection, row: Any) -> bool:
    """Whether a join's `reports_to` would be cross-owner for the agent it creates (§3.1):
    the membership then starts without it, and the join page says so."""
    if row.reports_to is None:
        return False
    boss = conn.execute(select(t.membership).where(t.membership.c.id == row.reports_to)).first()
    if boss is None:
        return False
    owner = (
        owner_of(conn, new_agent(row.agent_id)) if row.agent_id is not None else str(row.created_by)
    )
    side = owner_of(conn, boss)
    return owner is not None and side is not None and owner != side


def withdraw_open(conn: Connection, target_id: int, actor: Actor | None, reason: str) -> None:
    """Withdraw every open request of the member's edge: a newer `PATCH` of its `reports_to`
    (`superseded`), the removal of either member (`member_removed`)."""
    from maity_hub.routes.requests import close_request

    for row in open_pair(conn, target_id):
        close_request(conn, row.id, "withdrawn", actor, reason=reason)


def _rights(conn: Connection, boss: Any) -> bool:
    return bool(boss.role == "manager" and boss.trust != "guest")


def file(
    conn: Connection,
    project: Any,
    mine: Membership | None,
    caller: Caller,
    target: Any,
    boss: Any,
) -> list[str] | None:
    """File the consents of a cross-owner edge and return the requests' ids, the boss
    side's first; None when the edge is not cross-owner. The caller's own action is their
    consent when they are one of the two owners (§6.2). `mine` is None for an agent's owner
    who is no member of the project: they ask as themselves (`asked_by_human`)."""
    from maity_hub.routes.requests import file_to_human, file_to_human_outside

    pair = owners(conn, target, boss)
    if pair is None:
        return None
    subordinate_owner, boss_side = pair
    me = caller.human_id if caller.kind == "human" else None
    asked = [
        (human, side)
        for human, side in ((boss_side, "boss"), (subordinate_owner, "subordinate"))
        if human != me
    ]
    handle = _handle(conn, target)
    boss_handle = _handle(conn, boss)
    sub_owner_handle = _human_handle(conn, subordinate_owner)
    boss_owner_handle = _human_handle(conn, boss_side)
    manager = _rights(conn, boss)
    ids: list[str] = []
    for human, side in asked:
        title = (
            f"Take {handle} of {sub_owner_handle} as a report of {boss_handle}"
            if side == "boss"
            else f"Let {handle} report to {boss_handle} of {boss_owner_handle}"
        )
        proposal = {
            "kind": KIND,
            "target": target.id,
            "boss": boss.id,
            "side": side,
            "manager": manager,
            "requests": [],
        }
        summary = _summary(
            conn,
            project,
            handle=handle,
            boss=boss_handle,
            sub_owner=sub_owner_handle,
            boss_owner=boss_owner_handle,
            manager=manager,
            other=None,
        )
        if mine is None:
            ids.append(
                file_to_human_outside(conn, project.id, caller, human, title, summary, proposal)
            )
        else:
            ids.append(file_to_human(conn, mine, caller, human, title, summary, proposal))
    for request_id in ids:
        other = [i for i in ids if i != request_id]
        row = conn.execute(select(t.request).where(t.request.c.id == request_id)).one()
        conn.execute(
            update(t.request)
            .where(t.request.c.id == request_id)
            .values(
                proposal={**row.proposal, "requests": ids},
                summary=_summary(
                    conn,
                    project,
                    handle=handle,
                    boss=boss_handle,
                    sub_owner=sub_owner_handle,
                    boss_owner=boss_owner_handle,
                    manager=manager,
                    other=other[0] if other else None,
                ),
            )
        )
    return ids


def _summary(
    conn: Connection,
    project: Any,
    *,
    handle: str,
    boss: str,
    sub_owner: str,
    boss_owner: str,
    manager: bool,
    other: str | None,
) -> str:
    """What the decision needs, all in the request: a human who is no member reads nothing
    else of the project (§6.2)."""
    lines = [
        f"In the project {project.name} ({namespace.full_name(conn, project)}), "
        f"the agent {handle}, owned by {sub_owner}, is to report to {boss}, of {boss_owner}.",
        (
            f"The other owner's consent is still open (request {other})."
            if other is not None
            else "The other owner has consented, or acts here as one of the two."
        ),
        "What the edge does: it grants the boss no scope, no credential and no pause, removal "
        "or answering right over the agent. The boss receives the agent's `session_paused` "
        "events, with its harness, model and session id. The agent receives the boss's member "
        "id as `reports_to` in its resume packet and may treat the boss's messages as "
        "direction: to the agent's owner, instructions from outside. The agent's owner can end "
        "the edge at any time.",
    ]
    if manager:
        lines.append(
            "The boss holds the role manager: on a go it may assign and take back the agent's "
            "cards, set its areas and pause it, until the edge ends or the boss loses the role."
        )
    return "\n\n".join(lines)


def settle(conn: Connection, s: proposals.Settlement) -> None:
    """A `no` or a withdrawal withdraws the other request; a `go` that leaves none open sets
    the edge, checked again as it is now (§6.2): a cycle, a guest or the depth refuse the
    answer and the request stays open for a `no` or a withdrawal."""
    from maity_hub.routes import members
    from maity_hub.routes.requests import close_request

    request, proposal = s.request, s.proposal
    if s.outcome != "go":
        reason = "refused"
        if s.outcome != "no":  # the hub's own reasons go on to the other, a person's do not
            stored = conn.execute(
                select(t.request.c.withdraw_reason).where(t.request.c.id == request.id)
            ).scalar()
            reason = stored if stored in HUB_REASONS else "withdrawn"
        for other in open_pair(conn, proposal["target"], besides=request.id):
            close_request(conn, other.id, "withdrawn", s.closer, reason=reason)
        return
    if open_pair(conn, proposal["target"], besides=request.id):
        return  # the other owner is still to answer
    project = lock_project(conn, request.project_id)
    target = conn.execute(
        select(t.membership).where(t.membership.c.id == proposal["target"])
    ).first()
    boss = conn.execute(select(t.membership).where(t.membership.c.id == proposal["boss"])).first()
    if target is None or boss is None or target.active is None or boss.active is None:
        return  # a member left meanwhile: nothing to set (the removal withdraws the pair)
    boss_principal = principal_id(conn, boss.id)
    values = members.validate_assignment(
        conn,
        project.id,
        kind="agent",
        role=None,
        reports_to=boss_principal,
        areas=None,
        capabilities=None,
        member=target.id,
        current=(target.trust, target.role),
    )
    # The asker is a member, or an owner outside the project (`asked_by_human`, §2.3).
    if request.asked_by is not None:
        asker, actor = principal_id(conn, request.asked_by), s.proposer
    else:
        asker = request.asked_by_human
        actor = Actor(membership_id=None, human_id=asker, via=request.changed_via)
    assert asker is not None
    consent = bool(proposal["manager"]) and _rights(conn, boss)
    change = members.Change(project, actor, asker, s.approver or asker, None, None)
    members.apply_patch(conn, change, target, values, (False, None), line_consent=consent)


def may_withdraw(conn: Connection, row: Any, mine: Membership) -> bool | None:
    """Who withdraws a pair's request on the project route (§6.2): the asker, the two owners
    of the edge, and a human who holds `requests:answer` or `members:admin`. An agent that
    is not the asker is refused with `pending_consent`, whatever its scopes (`False`); a
    human with none of these rights is told nothing of the request (`None`, `not_found`, as
    for every personal request)."""
    if row.asked_by == mine.id:
        return True
    if mine.kind == "agent":
        return False
    if mine.may("requests:answer") or mine.may("members:admin"):
        return True
    proposal = row.proposal or {}
    named = [proposal["target"], proposal["boss"]]
    sides = conn.execute(select(t.membership).where(t.membership.c.id.in_(named))).all()
    owners = {owner_of(conn, side) for side in sides}
    return True if mine.principal_id in owners or mine.principal_id == row.to_human else None


def _addressee_only(conn: Connection, request: Any, mine: Any) -> str | None:
    return None


proposals.register(
    KIND,
    settle,
    proposals.Answerer(
        refusal="only the human this consent is addressed to answers it",
        predicate=_addressee_only,
    ),
)
