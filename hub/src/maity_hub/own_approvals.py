"""Own approvals for outsiders' work (docs/api.md §2.3 "Own approvals", §6.1 `own_approvals`,
`own_agents`): who is an outside agent, which cards are outsiders' work, how many own approvals
such a card has on its reported head, and the gate in front of every move to `done`.

Everything is judged as the card and its members stand at the check, never stored. An outside
agent has trust `outside`, or joined while its owner held no membership (`joined_outside`), on
its current membership row, or its owner holds none now; an agent whose profile the hub cannot
find counts as outside too.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, case, select

from maity_hub import agent_owners, cards, policy, review_delivery, scopes
from maity_hub import tables as t
from maity_hub.errors import ApiError

OUTSIDE_TRUST = "outside"
REASON = "own_approvals"
# The scopes whose holder may approve a card's head (§6.4, the signatures).
SIGNING_SCOPES = ("tasks:review", "tasks:test")


def outside_agent(conn: Connection, project: Any, agent_id: str) -> bool:
    """§2.3: trust `outside`, or joined while its owner was no member, on the membership the
    check is about, or its owner is no member now. Nothing that shows the agent is the
    project's own counts as outside.

    The membership is the active row, else the most recent (a reporter who has left). Trust
    and mark belong to their row: §2.3's one way out of `outside` is removal and a member's
    fresh join, which makes a new row without either (the lead's ruling of 2026-11-23)."""
    owner = conn.execute(
        select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == agent_id)
    ).scalar()
    if owner is None:
        return True
    row = conn.execute(
        select(t.membership.c.trust, t.membership.c.joined_outside)
        .where(t.membership.c.project_id == project.id, t.membership.c.agent_id == agent_id)
        .order_by(
            case((t.membership.c.removed_at.is_(None), 0), else_=1),
            t.membership.c.joined_at.desc(),
            t.membership.c.id.desc(),
        )
        .limit(1)
    ).first()
    if row is not None and (row.trust == OUTSIDE_TRUST or row.joined_outside):
        return True
    return not agent_owners.owner_is_member(conn, project.id, str(owner))


def _workers(conn: Connection, card: Any) -> list[str]:
    """The agents whose work the card is: its holder and the filer of its current report."""
    agents: list[str] = []
    if card.claim_holder is not None:
        held = conn.execute(
            select(t.membership.c.agent_id).where(t.membership.c.id == card.claim_holder)
        ).scalar()
        if held is not None:
            agents.append(str(held))
    reporter = (card.report or {}).get("reported_by")
    if isinstance(reporter, str) and reporter.startswith("agt-") and reporter not in agents:
        agents.append(reporter)
    return agents


def outsiders_work(conn: Connection, card: Any, project: Any) -> bool:
    """§2.3: an outside agent holds the card, or filed its current report."""
    return any(outside_agent(conn, project, a) for a in _workers(conn, card))


def _excluded_owners(conn: Connection, card: Any) -> set[str]:
    """The owners of the agents that hold the card or filed its current report: neither they
    nor their agents give an own approval on it (§2.3)."""
    agents = _workers(conn, card)
    if not agents:
        return set()
    rows = conn.execute(
        select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id.in_(agents))
    ).scalars()
    return {str(owner) for owner in rows if owner is not None}


def _live_account(conn: Connection, human_id: str) -> bool:
    """An active account, neither suspended nor deleted: only such a human approves, or makes
    its agents the project's own (the lead's ruling of 2026-11-23)."""
    row = conn.execute(
        select(t.human.c.account_status, t.human.c.suspended_at, t.human.c.deleted_at).where(
            t.human.c.id == human_id
        )
    ).first()
    return (
        row is not None
        and row.account_status == "active"
        and row.suspended_at is None
        and row.deleted_at is None
    )


def signer_when_posted(conn: Connection, project: Any, row: Any, bridged: bool) -> bool:
    """What the hub records on a `review_result` when it stores it (`event.review_signer`):
    whether its author stood as a signer at that moment, on the membership `row` it posted
    from. Not through a bridge (a bridge never signs); active and not isolated; trust and role
    giving `tasks:review` or `tasks:test`; a human's account live; an agent the project's own
    on that row (neither trust `outside` nor marked) with an owner who is a member, live."""
    if bridged or row.removed_at is not None or row.isolated_since is not None:
        return False
    if row.active is not True:
        return False
    kind = "human" if row.human_id is not None else "agent"
    if not (
        (kind == "human" and row.trust == "owner")
        or any(scopes.has_scope(row.trust, row.role_base, kind, s) for s in SIGNING_SCOPES)
    ):
        return False
    if kind == "human":
        return _live_account(conn, str(row.human_id))
    if row.trust == OUTSIDE_TRUST or row.joined_outside:
        return False
    owner = conn.execute(
        select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == row.agent_id)
    ).scalar()
    return (
        owner is not None
        and agent_owners.owner_is_member(conn, project.id, str(owner))
        and _live_account(conn, str(owner))
    )


def _human_of_the_project(conn: Connection, project: Any, human_id: str) -> bool:
    """A human member, not isolated, whose trust and role give `tasks:review` or `tasks:test`
    (trust `owner` gives every scope), the standing a signature in `approvals` needs (§6.4)."""
    row = conn.execute(
        select(t.membership.c.trust, t.membership.c.role_base).where(
            t.membership.c.project_id == project.id,
            t.membership.c.human_id == human_id,
            t.membership.c.active.is_(True),
            t.membership.c.removed_at.is_(None),
            t.membership.c.isolated_since.is_(None),
        )
    ).first()
    if row is None or not _live_account(conn, human_id):
        return False
    return row.trust == "owner" or any(
        scopes.has_scope(row.trust, row.role_base, "human", scope) for scope in SIGNING_SCOPES
    )


def _own_agent(conn: Connection, project: Any, agent_id: str, excluded: set[str]) -> bool:
    """An agent `policy.own_agents` counts as the project's own (§6.1): not an outside agent,
    not one of an excluded owner, active and not isolated, whose trust and role give
    `tasks:review` or `tasks:test` now (the standing a signature needs, §6.4), and its owner
    picked by the setting."""
    if outside_agent(conn, project, agent_id):
        return False
    owner = conn.execute(
        select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == agent_id)
    ).scalar()
    if owner is None or str(owner) in excluded:
        return False
    standing = conn.execute(
        select(t.membership.c.trust, t.membership.c.role_base).where(
            t.membership.c.project_id == project.id,
            t.membership.c.agent_id == agent_id,
            t.membership.c.active.is_(True),
            t.membership.c.removed_at.is_(None),
            t.membership.c.isolated_since.is_(None),
        )
    ).first()
    if standing is None or not any(
        scopes.has_scope(standing.trust, standing.role_base, "agent", scope)
        for scope in SIGNING_SCOPES
    ):
        return False
    setting = policy.own_agents(project)
    owner_row = conn.execute(
        select(t.membership.c.trust).where(
            t.membership.c.project_id == project.id,
            t.membership.c.human_id == str(owner),
            t.membership.c.active.is_(True),
        )
    ).first()
    if owner_row is None or not _live_account(conn, str(owner)):
        return False
    if setting == "owners":
        return bool(owner_row.trust == "owner")
    if isinstance(setting, dict):
        return str(owner) in setting.get(policy.OWNERS_OF, [])
    return True  # members: the agents of every human member


def _current_row(conn: Connection, project: Any, principal: str) -> int | None:
    """The principal's active membership row in the project, if any."""
    m = t.membership.c
    found = conn.execute(
        select(m.id).where(
            m.project_id == project.id,
            (m.agent_id == principal) | (m.human_id == principal),
            m.active.is_(True),
            m.removed_at.is_(None),
        )
    ).scalar()
    return int(found) if found is not None else None


def _review_approvers(conn: Connection, card: Any, project: Any, head: str) -> dict[str, str]:
    """The principals whose latest review result for the card is an `approve` on exactly
    `head` that may count, by principal with `agent` or `human` (the lead's ruling of
    2026-11-23). A card's results are those tied to it by `task_id` and those whose subject
    names only its current pull request (§8.4), read through the event's own columns: the
    read is bounded by the card's results, never the project's chat.

    The latest result is the principal's, from any of its memberships, a redacted one
    included: a later `changes`, `comment` or redacted result withdraws an earlier `approve`.
    That `approve` then counts only if it was not sent through a bridge, the hub recorded its
    author as a signer when it stored it (`review_signer`; none recorded is no), and it came
    from the author's current active membership, so a removal and a rejoin leave none."""
    e = t.event.c
    pr = ((card.report or {}).get("pr") or {}).get("number")
    tied = e.subject_id == card.id
    if isinstance(pr, int) and not isinstance(pr, bool):
        tied = tied | (e.subject_id.is_(None) & (e.review_pr == pr))
    rows = conn.execute(
        select(
            e.payload, e.actor_membership, e.actor_bridge, e.review_signer, e.redacted, e.subject_id
        )
        .where(
            e.project_id == card.project_id,
            e.kind == "message",
            e.review_signer.is_not(None),
            e.actor_membership.is_not(None),
            tied,
        )
        .order_by(e.seq)
    ).all()
    principals: dict[int, Any] = {}
    latest: dict[str, Any] = {}
    for row in rows:
        payload = row.payload or {}
        if payload.get("type") != "review_result":
            continue
        if row.subject_id is None:  # named by its pull request alone: is it this card's?
            review = payload.get("review")
            if not isinstance(review, dict) or not isinstance(review.get("subject"), str):
                continue
            resolved = review_delivery._card(conn, card.project_id, None, review)
            if resolved is None or resolved.id != card.id:
                continue
        membership_id = int(row.actor_membership)
        if membership_id not in principals:
            principals[membership_id] = conn.execute(
                select(t.membership.c.agent_id, t.membership.c.human_id).where(
                    t.membership.c.id == membership_id
                )
            ).first()
        member = principals[membership_id]
        if member is None:
            continue
        principal = member.agent_id if member.agent_id is not None else member.human_id
        if principal is not None:
            latest[str(principal)] = (row, member)
    approvers: dict[str, str] = {}
    for principal, (row, member) in latest.items():
        review = (row.payload or {}).get("review") or {}
        if (
            row.redacted
            or review.get("verdict") != "approve"
            or review.get("head") != head
            or row.actor_bridge is not None
            or row.review_signer is not True
            or _current_row(conn, project, principal) != int(row.actor_membership)
        ):
            continue
        approvers[principal] = "agent" if member.agent_id is not None else "human"
    return approvers


def counted(conn: Connection, card: Any, project: Any, mover: str | None = None) -> int:
    """The own approvals the card has on its reported head (§2.3): review results of own
    agents and humans of the project, a human's signature in `approvals` on the current
    report, and `mover`, a human whose own move to `done` or signature counts as one approval
    itself. Each member counts once.

    An `approve` counts when it may (`_review_approvers`: recorded as a signer's, not
    bridged, from the author's current membership) and its author stands now: an agent the
    project's own (`_own_agent`), a human of the project. A signature counts while its signer
    stands (`cards.standing`) and only for the report it was given on (its `revision`)."""
    report = card.report or {}
    head = report.get("head")
    excluded = _excluded_owners(conn, card)
    found: set[str] = set()
    if isinstance(head, str) and head:
        for principal, kind in _review_approvers(conn, card, project, head).items():
            if kind == "agent":
                if _own_agent(conn, project, principal, excluded):
                    found.add(principal)
            elif principal not in excluded and _human_of_the_project(conn, project, principal):
                found.add(principal)
    marks = cards.standing(conn, card.project_id, card.approvals) if card.approvals else {}
    signers = [
        mark.get("by")
        for mark in marks.values()
        if isinstance(mark, dict) and mark.get("revision") == report.get("revision")
    ]
    for human_id in [*signers, mover]:
        if (
            isinstance(human_id, str)
            and human_id.startswith("hum-")
            and human_id not in excluded
            and _human_of_the_project(conn, project, human_id)
        ):
            found.add(human_id)
    return len(found)


def missing(conn: Connection, card: Any, project: Any, mover: str | None = None) -> tuple[int, int]:
    """`(needed, counted)` when the card is outsiders' work short of its own approvals, else
    `(0, 0)`."""
    if not outsiders_work(conn, card, project):
        return 0, 0
    needed = policy.own_approvals(project)
    have = counted(conn, card, project, mover)
    return (needed, have) if have < needed else (0, 0)


def refused(needed: int, have: int) -> ApiError:
    return ApiError(
        403,
        "forbidden",
        "outsiders' work needs the project's own approvals before it is done",
        {"reason": REASON, "needed": needed, "counted": have},
    )


def gate(conn: Connection, card: Any, project: Any, mover: str | None = None) -> None:
    """§2.3: every move of outsiders' work to `done` waits for its own approvals; it runs
    after the done-authority check, so it decides only for a caller that has it."""
    needed, have = missing(conn, card, project, mover)
    if needed:
        raise refused(needed, have)
