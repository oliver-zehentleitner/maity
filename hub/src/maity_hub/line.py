"""The manager's line and reach, `line:lead`, and the depth of a chain (docs/api.md
§2.3 "The manager" and "Depth", §5.3, §6.2).

The **line** of a manager is every member whose `reports_to` chain reaches it. Its
**reach** is the part of the line it acts on: agent memberships with trust `member` or
`guest` whose role is not `proxy`, (a) of the manager's own owner reached through a
chain made only of such same-owner agents, and (b) of another owner reporting to the
manager itself over an edge whose `line_consent` is true, nothing below a (b) member.
The reach is computed from the memberships as they are, never stored: every caller
that decides a write on it holds the project lock first, so the chain it walked is the
chain the write lands on (`hub/context/manager.md`).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, select, update

from maity_hub import proposals
from maity_hub import tables as t
from maity_hub.access import Membership, member_row
from maity_hub.auth.caller import Caller
from maity_hub.errors import ApiError, forbidden, invalid, not_found
from maity_hub.events import Actor, lock_project
from maity_hub.scopes import SENSITIVE_ROLES, has_scope
from maity_hub.views import principal_id

MAX_DEPTH = 8
# The members of a reach: agents below governance, never a proxy (§2.3).
REACH_TRUSTS = ("member", "guest")
# What a caller holding only `line:lead` sets on a member of its reach.
LINE_FIELDS = {"areas", "paused", "instance", "reports_to"}


def not_in_line(message: str = "the member is not in your reach") -> ApiError:
    return ApiError(403, "forbidden", message, {"reason": "not_in_line"})


def leads(trust: str, role: str, kind: str) -> bool:
    return has_scope(trust, role, kind, "line:lead")


# --- the reach ------------------------------------------------------------------------


def _members(conn: Connection, project_id: str) -> list[Any]:
    """Every active membership of the project with the owner of each: the agent's
    profile owner, or the human itself."""
    m = t.membership.c
    return list(
        conn.execute(
            select(
                m.id,
                m.agent_id,
                m.human_id,
                m.trust,
                m.role,
                m.reports_to,
                m.line_consent,
                t.agent_profile.c.owner_id,
            )
            .select_from(
                t.membership.outerjoin(t.agent_profile, t.agent_profile.c.id == m.agent_id)
            )
            .where(m.project_id == project_id, m.active.is_(True))
        )
    )


def _owner(row: Any) -> str:
    owner: str = row.owner_id if row.agent_id is not None else row.human_id
    return owner


def _eligible(row: Any) -> bool:
    return row.agent_id is not None and row.trust in REACH_TRUSTS and row.role != "proxy"


def reach(conn: Connection, manager: Any) -> dict[int, str]:
    """The members `manager` (a membership row) may act on under `line:lead`, each with
    its part, `a` or `b`; empty for a membership that does not hold the scope (a guest
    manager holds nothing of the role)."""
    kind = "agent" if manager.agent_id is not None else "human"
    if manager.active is not True or not leads(manager.trust, manager.role_base, kind):
        return {}
    rows = _members(conn, manager.project_id)
    by_id = {r.id: r for r in rows}
    me = by_id.get(manager.id)
    if me is None:
        return {}
    owner = _owner(me)
    reports: dict[int, list[Any]] = {}
    for row in rows:
        if row.reports_to is not None:
            reports.setdefault(row.reports_to, []).append(row)
    found: dict[int, str] = {}
    frontier = [me.id]
    while frontier:
        boss = frontier.pop()
        for row in reports.get(boss, []):
            if row.id in found or row.id == me.id or not _eligible(row):
                continue  # the reach stops here, and so does everything below it
            if _owner(row) == owner:
                found[row.id] = "a"
                frontier.append(row.id)
            elif boss == me.id and row.line_consent:
                found[row.id] = "b"  # nothing below a (b) member is in the reach
    return found


def require_reach(conn: Connection, mine: Membership, *members: int | None) -> dict[int, str]:
    """`not_in_line` unless every member named is the caller or in its reach; returns
    the reach. The caller holds the project lock."""
    found = reach(conn, mine.row)
    for member in members:
        if member is not None and member != mine.id and member not in found:
            raise not_in_line()
    return found


# --- the depth of a chain -------------------------------------------------------------


def _above(conn: Connection, boss: int) -> int:
    """How many members the chain from `boss` up to the top holds, `boss` included."""
    seen: set[int] = set()
    current: int | None = boss
    while current is not None and current not in seen:
        seen.add(current)
        current = conn.execute(
            select(t.membership.c.reports_to).where(
                t.membership.c.id == current, t.membership.c.active.is_(True)
            )
        ).scalar()
    return len(seen)


def _below(conn: Connection, project_id: str, member: int) -> int:
    """The deepest chain below `member`, `member` included."""
    reports: dict[int, list[int]] = {}
    rows = conn.execute(
        select(t.membership.c.id, t.membership.c.reports_to).where(
            t.membership.c.project_id == project_id,
            t.membership.c.active.is_(True),
            t.membership.c.reports_to.is_not(None),
        )
    )
    for row in rows:
        reports.setdefault(row.reports_to, []).append(row.id)
    depth, level, seen = 0, [member], {member}
    while level:
        depth += 1
        level = [r for m in level for r in reports.get(m, []) if r not in seen]
        seen.update(level)
    return depth


def fits(conn: Connection, project_id: str, boss: int, member: int | None = None) -> bool:
    """Whether `member` (None for a new one) may report to `boss`: the chain above plus
    the deepest chain below stays within 8 (§2.3 "Depth")."""
    below = 1 if member is None else _below(conn, project_id, member)
    return _above(conn, boss) + below <= MAX_DEPTH


def too_deep() -> ApiError:
    return invalid({"reports_to": "too_deep"}, f"a reports_to chain holds at most {MAX_DEPTH}")


# --- PATCH …/members/{id} under line:lead ---------------------------------------------


def _setter_in_reach(conn: Connection, project_id: str, by: str, found: dict[int, str]) -> bool:
    try:
        setter = member_row(conn, project_id, by)
    except ApiError:
        return False
    return setter.id in found


def _check_pause(
    conn: Connection, mine: Membership, target: Any, row: Any, found: dict[int, str]
) -> None:
    """A manager lifts or replaces no pause but its own, the agent's own declaration and
    one a manager in its reach set (§2.3, §5.3): never a human's, an admin's, or one of
    a manager outside its reach."""
    if row.paused_since is None or row.paused_by == target.agent_id:
        return
    if row.paused_line and (
        row.paused_by == mine.principal_id
        or _setter_in_reach(conn, mine.project.id, row.paused_by, found)
    ):
        return
    raise forbidden(
        "members:admin",
        "a pause set by a human, an admin or a manager outside your reach is not yours to change",
    )


def check_patch(conn: Connection, mine: Membership, target: Any, body: Any, given: set[str]) -> Any:
    """The rules of a `PATCH …/members/{id}` by a caller holding only `line:lead`, under
    the project lock it takes; returns the target as read under that lock."""
    if given - LINE_FIELDS:
        raise forbidden("members:admin", "a manager sets areas, paused and reports_to only")
    lock_project(conn, mine.project.id)
    # Read again under the lock, and locked itself: a human's pause write does not take
    # the project lock, and its pause, role and edge decide what follows.
    target = conn.execute(
        select(t.membership).where(t.membership.c.id == target.id).with_for_update()
    ).one()
    if target.active is not True:
        raise not_found()  # removed meanwhile, as `member_row` answers
    found = require_reach(conn, mine, target.id)
    if target.id == mine.id:
        raise not_in_line("a manager is not in its own reach")
    if "reports_to" in given:
        if found[target.id] != "a":
            raise not_in_line("a consented edge is changed by the owners, not under line:lead")
        if body.reports_to is None:
            raise not_in_line("the new boss is you or a member of your own owner in your reach")
        try:
            boss = member_row(conn, mine.project.id, body.reports_to)
        except ApiError:
            boss = None  # `not_a_member` from the validation that follows
        if boss is not None and boss.id != mine.id and found.get(boss.id) != "a":
            raise not_in_line("the new boss is you or a member of your own owner in your reach")
    if "paused" in given:
        from maity_hub import instances

        instance = body.paused.instance if body.paused else body.instance
        row = target
        if instance is not None:
            row = instances.require_active(conn, target, instance, "instance")
        _check_pause(conn, mine, target, row, found)
    return target


def needs_consent(project: Any, target: Any, values: dict[str, Any], pause: Any) -> bool:
    """Pausing a reviewer, a tester, the contract arbiter or the coordinator, and changing
    its `reports_to`, wait for a human's go (§2.3 "The manager")."""
    seat = target.agent_id is not None and target.agent_id in (
        project.contract_arbiter,
        project.coordinator,
    )
    if not (target.role_base in SENSITIVE_ROLES or seat):
        return False
    pauses = bool(pause[0] and pause[1] is not None)
    moves = "reports_to" in values and values["reports_to"] != target.reports_to
    return pauses or moves


def propose(
    conn: Connection, mine: Membership, caller: Caller, target: Any, change: dict[str, Any]
) -> str:
    """File the consent request to the owner that applies `change` on its go."""
    from maity_hub.routes.requests import file_consent

    handle = principal_id(conn, target.id)
    title = f"Pause {handle}" if change["pause"][1] is not None else f"Change {handle}'s lead"
    summary = (
        f"{principal_id(conn, mine.id)} asks, as the manager of {handle}, for this change "
        "of its membership."
    )
    proposal = {"kind": "line_change", "membership_id": target.id, **change}
    return file_consent(conn, mine, caller, title, summary, proposal=proposal)


def settle(conn: Connection, s: proposals.Settlement) -> None:
    """Apply the change on `go` when the manager may still make it: still a manager,
    the member still in its reach, the pause still its to touch, the new boss still in
    the reach and the chain still within depth and free of cycles. Otherwise the answer
    is refused and the request stays open."""
    from maity_hub.routes import members

    if s.outcome != "go" or s.approver is None:
        return
    proposal, request = s.proposal, s.request
    project = lock_project(conn, request.project_id)
    target = conn.execute(
        select(t.membership).where(t.membership.c.id == proposal["membership_id"])
    ).one()
    if target.active is None:  # removed meanwhile: nothing left to change
        return
    proposer = conn.execute(
        select(t.membership).where(t.membership.c.id == request.asked_by)
    ).first()
    found = reach(conn, proposer) if proposer is not None else {}
    if proposer is None or target.id not in found:
        raise ApiError(409, "not_in_line", "the member is no longer in the manager's reach")
    kind = "agent" if proposer.agent_id is not None else "human"
    mine = Membership(project, proposer, kind)
    values = dict(proposal["values"])
    boss = values.get("reports_to")
    if boss is not None:
        if found[target.id] != "a" or (boss != proposer.id and found.get(boss) != "a"):
            raise ApiError(409, "not_in_line", "the new boss is no longer in the manager's reach")
        if target.id in members.chain(conn, boss):
            raise invalid({"reports_to": "cycle"}, "the chain made a cycle in the meantime")
        if not fits(conn, project.id, boss, target.id):
            raise too_deep()
    given, reason = proposal["pause"]
    if given:
        row = target
        instance = proposal.get("instance")
        if instance is not None:
            from maity_hub import instances

            row = instances.require_active(conn, target, instance, "instance")
        try:
            _check_pause(conn, mine, target, row, found)
        except ApiError:
            raise ApiError(
                409, "pause_changed", "the pause is someone else's now; the go cannot touch it"
            ) from None
    agent = principal_id(conn, request.asked_by)
    assert agent is not None
    change = members.Change(project, s.proposer, agent, s.approver, None, None, line=True)
    members.apply_patch(
        conn, change, target, values, (bool(given), reason), instance=proposal.get("instance")
    )


proposals.register(
    "line_change",
    settle,
    proposals.Answerer(
        scope="members:admin",
        refusal="a human with members:admin answers a manager's change of a membership",
    ),
)


# --- the edge and the role ending -----------------------------------------------------


def _lift_line_pauses(conn: Connection, change: Any, target: Any, by: str) -> None:
    """Lift every pause `by` set under `line:lead` over `target`: the membership's and
    each instance's (§6.2 "Ending it")."""
    from maity_hub.routes import members

    row = conn.execute(select(t.membership).where(t.membership.c.id == target.id)).one()
    if row.paused_since is not None and row.paused_line and row.paused_by == by:
        members.set_paused(conn, change, row, None)
    held = conn.execute(
        select(t.credential.c.instance).where(
            t.credential.c.membership_id == target.id,
            t.credential.c.revoked_at.is_(None),
            t.credential.c.paused_since.is_not(None),
            t.credential.c.paused_line.is_(True),
            t.credential.c.paused_by == by,
        )
    ).scalars()
    for instance in sorted(held):
        row = conn.execute(select(t.membership).where(t.membership.c.id == target.id)).one()
        members.set_paused(conn, change, row, None, instance=instance)


def edge_ended(conn: Connection, change: Any, target: Any) -> None:
    """`target`'s `reports_to` changed or ended (its row as it was before): a consent
    for a manager's rights over the old edge is gone for good, and a pause the old boss
    set over it is lifted (§6.2). The caller has written the new `reports_to` and
    cleared `line_consent` already."""
    if target.reports_to is None:
        return
    boss = principal_id(conn, target.reports_to)
    if boss is not None and target.line_consent:
        _lift_line_pauses(conn, change, target, boss)


def manager_lost(conn: Connection, change: Any, boss: Any) -> None:
    """`boss` lost the role `manager`: every consent naming a manager's rights to it is
    cleared for good, and the pauses it set over those edges are lifted (§6.2)."""
    from maity_hub.events import emit
    from maity_hub.views import member_view

    boss_id = principal_id(conn, boss.id)
    assert boss_id is not None
    reports = conn.execute(
        select(t.membership).where(
            t.membership.c.reports_to == boss.id,
            t.membership.c.active.is_(True),
            t.membership.c.line_consent.is_(True),
        )
    ).all()
    for report in sorted(reports, key=lambda r: r.id):
        conn.execute(
            update(t.membership).where(t.membership.c.id == report.id).values(line_consent=False)
        )
        row = conn.execute(select(t.membership).where(t.membership.c.id == report.id)).one()
        view = member_view(conn, row)
        emit(
            conn,
            change.project.id,
            "member_updated",
            ["all"],
            view,
            actor=change.actor,
            subject=("member", view["id"]),
        )
        _lift_line_pauses(conn, change, report, boss_id)


def owner_actor(caller: Caller, membership_id: int | None) -> Actor:
    """The actor of an agent's owner, a member of the project or not (§8.1)."""
    if membership_id is not None:
        return caller.actor(membership_id)
    return Actor(membership_id=None, human_id=caller.human_id, via=caller.via)
