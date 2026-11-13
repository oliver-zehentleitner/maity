"""Revoking unused join links (docs/api.md §3.1): who revoked them, and the `join_revoked` event.

Every path that revokes a human's join goes through `revoke`: the `DELETE` of one join, a
profile's deletion by its owner (§6.3), and the end of the creator's membership (§6.2). Each
names the principal on whose authority it happens as `revoked_by` and writes one `join_revoked`
per join it revoked. The hub's own revocations, with no person behind them, do not come here
and leave `revoked_by` null with no event: a runner's pickups (`placements.revoke_unused_joins`
and the pickup's reissue, §15.9) and an account's deletion (§2.9), whose profiles' joins pass
`by=None`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, select, update

from maity_hub import clock, invitations
from maity_hub import tables as t
from maity_hub.events import Actor, emit

KIND = "join_revoked"


def announce(conn: Connection, row: Any, by: str, actor: Actor) -> None:
    """`join_revoked` to the join's creator and the project's human `members:admin` holders,
    as the invitation events (§3.4, §8.2); never the URL or the code."""
    emit(
        conn,
        row.project_id,
        KIND,
        invitations.audience(conn, row.project_id, f"member:{row.created_by}"),
        {
            "id": row.id,
            "agent_id": row.agent_id,
            "trust": row.trust,
            "role": row.role,
            "revoked_by": by,
        },
        actor=actor,
        subject=("join", row.id),
    )


def revoke(
    conn: Connection,
    *where: Any,
    by: str | None,
    actor_in: Any = None,
) -> list[str]:
    """Revoke the unrevoked joins `where` selects; returns their ids. With `by`, each is
    attributed to it and announced with `actor_in(project_id)` as the event's actor; without,
    it is the hub's own revocation. Each row is revoked by a conditional update of its own, so
    a join another call revoked meanwhile is neither attributed nor announced twice."""
    j = t.join_link.c
    rows = conn.execute(
        select(t.join_link).where(j.revoked_at.is_(None), *where).order_by(j.project_id, j.id)
    ).all()
    now = clock.now()
    done: list[str] = []
    for row in rows:
        changed = conn.execute(
            update(t.join_link)
            .where(j.id == row.id, j.revoked_at.is_(None))
            .values(revoked_at=now, revoked_by=by)
        ).rowcount
        if changed != 1:
            continue
        done.append(row.id)
        if by is not None and actor_in is not None:
            announce(conn, row, by, actor_in(row.project_id))
    return done
