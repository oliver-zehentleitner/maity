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

from maity_hub import agent_owners, policy, review_delivery, scopes
from maity_hub import tables as t
from maity_hub.errors import ApiError

OUTSIDE_TRUST = "outside"
REASON = "own_approvals"


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
    if row is None:
        return False
    return row.trust == "owner" or any(
        scopes.has_scope(row.trust, row.role_base, "human", scope)
        for scope in ("tasks:review", "tasks:test")
    )


def _own_agent(conn: Connection, project: Any, agent_id: str, excluded: set[str]) -> bool:
    """An agent `policy.own_agents` counts as the project's own (§6.1): not an outside agent,
    not one of an excluded owner, active and not isolated, and its owner picked by the
    setting."""
    if outside_agent(conn, project, agent_id):
        return False
    owner = conn.execute(
        select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == agent_id)
    ).scalar()
    if owner is None or str(owner) in excluded:
        return False
    standing = conn.execute(
        select(t.membership.c.id).where(
            t.membership.c.project_id == project.id,
            t.membership.c.agent_id == agent_id,
            t.membership.c.active.is_(True),
            t.membership.c.removed_at.is_(None),
            t.membership.c.isolated_since.is_(None),
        )
    ).first()
    if standing is None:
        return False
    setting = policy.own_agents(project)
    owner_row = conn.execute(
        select(t.membership.c.trust).where(
            t.membership.c.project_id == project.id,
            t.membership.c.human_id == str(owner),
            t.membership.c.active.is_(True),
        )
    ).first()
    if owner_row is None:
        return False
    if setting == "owners":
        return bool(owner_row.trust == "owner")
    if isinstance(setting, dict):
        return str(owner) in setting.get(policy.OWNERS_OF, [])
    return True  # members: the agents of every human member


def _review_approvers(conn: Connection, card: Any, head: str) -> dict[str, str]:
    """The members whose latest review result for the card (§8.4: its `task_id`, or a
    subject that is exactly `#<n>`) is an `approve` on exactly `head`, by member id, with
    `agent` or `human`. A later `changes` or `comment` withdraws an earlier `approve`."""
    rows = conn.execute(
        select(t.event.c.payload, t.event.c.actor_membership)
        .where(
            t.event.c.project_id == card.project_id,
            t.event.c.kind == "message",
            t.event.c.redacted.is_(False),
            t.event.c.actor_membership.is_not(None),
            (t.event.c.subject_id == card.id) | t.event.c.subject_id.is_(None),
        )
        .order_by(t.event.c.seq)
    ).all()
    latest: dict[int, dict[str, Any]] = {}
    for payload, membership_id in rows:
        if (payload or {}).get("type") != "review_result":
            continue
        review = payload.get("review") or {}
        task_id = payload.get("task_id")
        if task_id is None:
            resolved = review_delivery._card(conn, card.project_id, None, review)
            if resolved is None or resolved.id != card.id:
                continue
        elif task_id != card.id:
            continue
        latest[int(membership_id)] = review
    approvers: dict[str, str] = {}
    for membership_id, review in latest.items():
        if review.get("verdict") != "approve" or review.get("head") != head:
            continue
        member = conn.execute(
            select(t.membership.c.agent_id, t.membership.c.human_id).where(
                t.membership.c.id == membership_id
            )
        ).first()
        if member is None:
            continue
        if member.agent_id is not None:
            approvers[str(member.agent_id)] = "agent"
        elif member.human_id is not None:
            approvers[str(member.human_id)] = "human"
    return approvers


def counted(conn: Connection, card: Any, project: Any, mover: str | None = None) -> int:
    """The own approvals the card has on its reported head (§2.3): review results of own
    agents and humans of the project, a human's signature in `approvals`, and `mover`, a
    human whose own move to `done` or signature counts as one approval itself. Each member
    counts once."""
    head = (card.report or {}).get("head")
    excluded = _excluded_owners(conn, card)
    found: set[str] = set()
    if isinstance(head, str) and head:
        for member_id, kind in _review_approvers(conn, card, head).items():
            if kind == "agent":
                if _own_agent(conn, project, member_id, excluded):
                    found.add(member_id)
            elif member_id not in excluded and _human_of_the_project(conn, project, member_id):
                found.add(member_id)
    signers = [
        (entry or {}).get("by")
        for entry in ((card.approvals or {}).values() if isinstance(card.approvals, dict) else [])
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
