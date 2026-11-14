"""Isolating an agent member (docs/api.md §6.2, "Isolation").

A human with `members:admin` stops any agent of the project at once, whoever brought it,
and lifts that again. The membership stays with its history; what it held is let go
(claims, group chats, runner placements), what it reads and is told ends, and every call
of its credentials into the project answers `forbidden` with `details.reason: isolated`.
Lifting gives access back, nothing else. The seats that name it stay, and routing skips it
(`principals`, `ids`): see the callers.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from sqlalchemy import Connection, case, func, select, update

from maity_hub import cards, clock, group_chats, longpoll, placements, restricted
from maity_hub import tables as t
from maity_hub.errors import ApiError
from maity_hub.events import Actor, emit, lock_project, on_commit
from maity_hub.views import isolated, member_view

REASON = "membership_isolated"
BY_HUB = "hub"  # `isolated.by` of an isolation the hub made itself (§6.2)


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


class Released(NamedTuple):
    """The cards `release_claims` gave back, for `tell_released`."""

    moved: list[str]  # left `in_progress`: a status change, told to their watchers
    kept: list[str]  # in another status: only the holder went, which their pages show


def release_claims(conn: Connection, membership_id: int) -> Released:
    """Every open card the member holds goes back to the board (§6.5). Returns those cards,
    for `tell_released` after the caller's own event."""
    held = conn.execute(
        select(t.card.c.id, t.card.c.status).where(cards.open_claims(membership_id))
    ).all()
    conn.execute(
        update(t.card)
        .where(cards.open_claims(membership_id))
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
    return Released(
        moved=sorted(card_id for card_id, status in held if status == "in_progress"),
        kept=sorted(card_id for card_id, status in held if status != "in_progress"),
    )


def tell_released(conn: Connection, released: Released, actor: Actor | None, project: Any) -> None:
    """The status change of cards `release_claims` gave back, for their watchers (§6.4),
    which renders their public pages too. A card that kept its status (`review`, `blocked`)
    makes no event, but its page named the holder: in a project with a public page it is
    touched here, after the caller's event took the project lock, since the member's own
    event no longer finds it by its holder (hub/context/public-pages.md fe966f9c). Without
    one there is no card page to touch, as `events.emit` gates its own touches."""
    if project.public_page == "on":
        from maity_hub import public_pages

        for card_id in released.kept:
            public_pages.touch(conn, "card", card_id)
    if not released.moved:
        return
    from maity_hub.routes.tasks import status_moved  # tasks reads availability, and this

    for card in conn.execute(select(t.card).where(t.card.c.id.in_(released.moved))).all():
        state = conn.execute(
            select(t.project.c.state).where(t.project.c.id == card.project_id)
        ).scalar_one()
        status_moved(conn, card, state, actor)


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
    released = release_claims(conn, target.id)
    group_chats.membership_removed(conn, target, actor, human_id, REASON)
    if target.agent_id is not None:
        from maity_hub import cross_chats

        cross_chats.isolation_settled(conn, target.agent_id, human_id)
    placements.membership_isolated(conn, target.id, actor, human_id)
    _announce(conn, project, target, actor)
    cards.drop_signatures(conn, project.id, target.agent_id or target.human_id, actor)  # §6.4
    tell_released(conn, released, actor, project)
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
    in_set_before = restricted.resolve(conn, project)
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
    from maity_hub import cards

    # A signature left from while it stood isolated goes before the lift gives the
    # standing back, so the lift never makes it count again (§6.4).
    cards.drop_signatures(conn, project.id, target.agent_id, actor)
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
    # The end of an isolation is a way into the restricted-access set (§6.1).
    restricted.entered(
        conn,
        project.id,
        in_set_before,
        "isolation_ended",
        restricted.person(conn, actor.membership_id) if actor.membership_id else "hub",
        actor,
    )
    _tell_owner(
        conn,
        project,
        target,
        human_id,
        "The isolation of {handle} was lifted",
        [],
    )
