"""Removing a member resets every seat that names it (docs/api.md §6.2).

A seat names one member to act for the project or a card, or to stand in for one. The
removal's transaction sets each seat the removed member held to its fallback — never to
another member chosen in passing, and never a reason to refuse the removal — and tells
the humans who name the next holder. Every removal comes through here: `DELETE
…/members/{id}` and an agent profile's cascade (§6.3) alike.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, select, update

from maity_hub import cards, clock, policy, rules
from maity_hub import tables as t
from maity_hub.events import Actor, emit

REASON = "member_removed"


def reset(conn: Connection, project_id: str, removed: Any, actor: Actor | None) -> None:
    """Reset the seats `removed` (its membership row, already inactive) held."""
    principal = removed.agent_id or removed.human_id
    project = conn.execute(select(t.project).where(t.project.c.id == project_id)).one()
    deciders = _deciders(conn, project_id)
    new = policy.of(project)
    if project.contract_arbiter == principal:
        new["contract_arbiter"] = _arbiter_fallback(conn, project_id, removed)
    if new != policy.of(project):
        conn.execute(
            update(t.project).where(t.project.c.id == project_id).values(**policy.columns(new))
        )
        rules.bump(
            conn,
            project,
            "policy_changed",
            ["all", *deciders],
            {"old": policy.of(project), "new": new, "reason": REASON},
            actor=actor,
        )
    _reset_card_arbiters(conn, project, principal, removed, new, deciders, actor)


def _deciders(conn: Connection, project_id: str) -> list[str]:
    """`member:<id>` of every human holding `owner` or `admin`: they name the next
    holder, so each reset is addressed to them, not only broadcast."""
    humans = conn.execute(
        select(t.membership.c.human_id)
        .where(
            t.membership.c.project_id == project_id,
            t.membership.c.human_id.is_not(None),
            t.membership.c.role.in_(("owner", "admin")),
            t.membership.c.active.is_(True),
        )
        .order_by(t.membership.c.joined_at)
    ).scalars()
    return [f"member:{human_id}" for human_id in humans]


def _owner(conn: Connection, project_id: str) -> str:
    """The human holding `owner` (with several, the one who joined first)."""
    owner: str = conn.execute(
        select(t.membership.c.human_id)
        .where(
            t.membership.c.project_id == project_id,
            t.membership.c.role == "owner",
            t.membership.c.active.is_(True),
        )
        .order_by(t.membership.c.joined_at)
        .limit(1)
    ).scalar_one()
    return owner


def _arbiter_fallback(conn: Connection, project_id: str, removed: Any) -> str:
    """An agent's seat goes to `role:admin` while an admin is left, a human's to the
    owner: a seat a human held never lands on an agent this way (§6.12)."""
    if removed.agent_id is not None:
        admin = conn.execute(
            select(t.membership.c.id)
            .where(
                t.membership.c.project_id == project_id,
                t.membership.c.role == "admin",
                t.membership.c.active.is_(True),
            )
            .limit(1)
        ).first()
        if admin is not None:
            return "role:admin"
    return _owner(conn, project_id)


def _reset_card_arbiters(
    conn: Connection,
    project: Any,
    principal: str,
    removed: Any,
    new_policy: dict[str, Any],
    deciders: list[str],
    actor: Actor | None,
) -> None:
    """An open contract card's arbiter: the policy's after the reset for an agent, the
    owner for a human — never `role:admin`. A closed card keeps it, as a record."""
    from maity_hub.routes.tasks import audience

    fallback = (
        new_policy["contract_arbiter"] if removed.agent_id is not None else _owner(conn, project.id)
    )
    found = conn.execute(
        select(t.card)
        .where(
            t.card.c.project_id == project.id,
            t.card.c.kind == "contract",
            t.card.c.status.notin_(cards.CLOSED),
        )
        .order_by(t.card.c.id)
    ).all()
    for card in found:
        contract = dict(card.contract or {})
        if contract.get("arbiter") != principal:
            continue
        contract["arbiter"] = fallback
        conn.execute(
            update(t.card)
            .where(t.card.c.id == card.id)
            .values(contract=contract, updated_at=clock.now())
        )
        updated = conn.execute(select(t.card).where(t.card.c.id == card.id)).one()
        usual = audience(conn, updated)
        emit(
            conn,
            project.id,
            "task_updated",
            [*usual, *(d for d in deciders if d not in usual)],
            {
                "id": card.id,
                "fields": ["contract"],
                "contract": contract,
                "project_state": project.state,
            },
            actor=actor,
            subject=("task", card.id),
        )
