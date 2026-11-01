"""Isolating an agent member (docs/api.md §6.2, "Isolation").

A human with `members:admin` stops any agent of the project at once, whoever brought it,
and lifts that again. The membership stays with its history; what it held is let go
(claims, group chats, runner placements), what it reads and is told ends, and every call
of its credentials into the project answers `forbidden` with `details.reason: isolated`.
Lifting gives access back, nothing else. The seats that name it stay, and routing skips it
(`principals`, `ids`): see the callers.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, case, func, select, update

from maity_hub import clock, group_chats, longpoll, placements
from maity_hub import tables as t
from maity_hub.errors import ApiError
from maity_hub.events import Actor, emit, lock_project, on_commit
from maity_hub.views import isolated, member_view

REASON = "membership_isolated"
BY_HUB = "hub"  # `isolated.by` of an isolation the hub made itself (§6.2)
CLOSED = ("done", "cancelled")


def is_isolated(row: Any) -> bool:
    return bool(row.isolated_since is not None)


def refusal(row: Any) -> ApiError:
    """Every call of an isolated agent's credentials, but the two that tell it why."""
    shown = isolated(row)
    return ApiError(
        403,
        "forbidden",
        "this agent is isolated in the project",
        {"reason": "isolated", "isolated": shown},
    )


def release_claims(conn: Connection, membership_id: int) -> None:
    """Every open card the member holds goes back to the board (§6.5); a card that left
    `in_progress` that way tells its watchers (§6.4)."""
    moved = (
        conn.execute(
            select(t.card.c.id).where(
                t.card.c.claim_holder == membership_id, t.card.c.status == "in_progress"
            )
        )
        .scalars()
        .all()
    )
    conn.execute(
        update(t.card)
        .where(t.card.c.claim_holder == membership_id, t.card.c.status.notin_(CLOSED))
        .values(
            claim_holder=None,
            claim_instance=None,
            claim_session_id=None,
            claim_since=None,
            lease_until=None,
            status=case((t.card.c.status == "in_progress", "open"), else_=t.card.c.status),
            updated_at=clock.now(),
        )
    )
    if moved:
        from maity_hub.routes.tasks import status_moved  # tasks reads availability, and this

        for card in conn.execute(select(t.card).where(t.card.c.id.in_(moved))).all():
            state = conn.execute(
                select(t.project.c.state).where(t.project.c.id == card.project_id)
            ).scalar_one()
            status_moved(conn, card, state, None)


def _announce(conn: Connection, project: Any, target: Any, actor: Actor) -> None:
    row = conn.execute(select(t.membership).where(t.membership.c.id == target.id)).one()
    view = member_view(conn, row)  # to everyone: never the briefing
    view["changed"] = ["isolated"]
    emit(
        conn,
        project.id,
        "member_updated",
        ["all"],
        view,
        actor=actor,
        subject=("member", view["id"]),
    )


def _tell_owner(
    conn: Connection, project: Any, target: Any, human_id: str, title: str, lines: list[str]
) -> None:
    from maity_hub import namespace
    from maity_hub.routes.requests import file_hub_notice

    handle = conn.execute(
        select(t.agent_profile.c.handle).where(t.agent_profile.c.id == target.agent_id)
    ).scalar_one()
    who = (
        "the hub"
        if human_id == BY_HUB
        else conn.execute(select(t.human.c.handle).where(t.human.c.id == human_id)).scalar_one()
    )
    summary = "\n".join(
        [f"Project: `{namespace.full_name(conn, project)}`.", *lines, f"By: `{who}`."]
    )
    file_hub_notice(
        conn, project.id, target.id, target.agent_id, title.format(handle=handle), summary
    )


def isolate(
    conn: Connection, project: Any, target: Any, reason: str, human_id: str, actor: Actor
) -> None:
    """Isolate `target`; an isolated agent stays as it is (§6.2)."""
    lock_project(conn, project.id)
    target = conn.execute(select(t.membership).where(t.membership.c.id == target.id)).one()
    if is_isolated(target) or target.active is None:
        return
    conn.execute(
        update(t.membership)
        .where(t.membership.c.id == target.id)
        .values(
            isolated_reason=reason,
            isolated_since=clock.now(),
            isolated_by=human_id,
            # Where a hidden window would start: the first event this isolation makes (§6.2).
            isolated_from_seq=_head(conn, project.id) + 1,
        )
    )
    release_claims(conn, target.id)
    group_chats.membership_removed(conn, target, actor, human_id, REASON)
    placements.membership_isolated(conn, target.id, actor, human_id)
    _announce(conn, project, target, actor)
    _tell_owner(
        conn,
        project,
        target,
        human_id,
        "{handle} was isolated",
        [f"Reason: {reason}"],
    )
    on_commit(conn, lambda: longpoll.registry.end(target.id))


def _head(conn: Connection, project_id: str) -> int:
    """The project's newest event seq, 0 for none."""
    head = conn.execute(
        select(func.max(t.event.c.seq)).where(t.event.c.project_id == project_id)
    ).scalar()
    return int(head or 0)


def lift(
    conn: Connection,
    project: Any,
    target: Any,
    human_id: str,
    actor: Actor,
    *,
    hide: bool = False,
) -> None:
    """Lift the isolation: access only, not the claims or the chats (§6.2). With `hide` the
    events between the isolation and now stay out of what the agent may read for good: the
    window `{from_seq, to_seq}`, both ends included, joins its `isolation_windows`."""
    lock_project(conn, project.id)
    target = conn.execute(select(t.membership).where(t.membership.c.id == target.id)).one()
    if not is_isolated(target) or target.active is None:
        return
    windows = list(target.isolation_windows or [])
    to_seq = _head(conn, project.id)  # before the lift's own events: the agent reads those
    from_seq = target.isolated_from_seq
    if hide and from_seq is None:
        # An isolation made before the column existed: its first event is the first one at or
        # after the moment it began.
        from_seq = conn.execute(
            select(func.min(t.event.c.seq)).where(
                t.event.c.project_id == project.id, t.event.c.at >= target.isolated_since
            )
        ).scalar()
    if hide and from_seq is not None and from_seq <= to_seq:
        windows.append({"from_seq": from_seq, "to_seq": to_seq})
    conn.execute(
        update(t.membership)
        .where(t.membership.c.id == target.id)
        .values(
            isolated_reason=None,
            isolated_since=None,
            isolated_by=None,
            isolated_from_seq=None,
            isolation_windows=windows or None,
        )
    )
    # What happened while it was left out is not read afterwards: its sessions' cursors
    # move to the project's head, where the next resume starts (§6.2).
    if to_seq:
        conn.execute(
            update(t.agent_session)
            .where(
                t.agent_session.c.membership_id == target.id,
                t.agent_session.c.acknowledged_seq < to_seq,
            )
            .values(acknowledged_seq=to_seq)
        )
    _announce(conn, project, target, actor)
    _tell_owner(
        conn,
        project,
        target,
        human_id,
        "The isolation of {handle} was lifted",
        [],
    )
