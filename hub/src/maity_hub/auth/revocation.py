"""Credential revocation: every path that revokes an agent or a runner credential ends here.

`revoke` is the one function every agent credential revocation passes (a leak, the
revoke routes, a replacement, a member's removal, a suspension, a runner's stop): it ends
the live session and the open waits, a revoked lead stops being lead, the holder that
stops is reported (§6.5) and a placement naming the credential stops (§15.5).
`revoke_runner_credential` does the same for a runner credential, with what the runner's
placements lose and the `runner_credential_revoked` event per attached project (§15.10).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import Connection, select, update

from maity_hub import clock, environment, placements
from maity_hub import tables as t
from maity_hub.events import emit, lock_projects
from maity_hub.runners import attached_project_ids, human_actor


def projects_of(conn: Connection, credential_ids: Iterable[str]) -> set[str]:
    """The projects revoking these agent credentials writes in: each one an instance is
    attached to now (§6.17), its `holder_stalled`, its lead's end, its overlaps, and each one
    of an active placement that names one (§15.5), which stops."""
    ids = sorted(set(credential_ids))
    if not ids:
        return set()
    a = t.instance_attachment
    found = set(
        conn.execute(
            select(t.membership.c.project_id)
            .join(a, a.c.membership_id == t.membership.c.id)
            .where(a.c.credential_id.in_(ids), a.c.detached_at.is_(None))
        ).scalars()
    )
    found.update(
        conn.execute(
            select(t.placement.c.project_id).where(
                t.placement.c.credential_id.in_(ids), t.placement.c.active.is_(True)
            )
        ).scalars()
    )
    return found


def revoke(
    conn: Connection,
    credential_id: str,
    reason: str,
    by: str | None,
    *,
    holder_moves: bool = False,
    member_goes: bool = False,
    stops_placements: bool = True,
) -> bool:
    """Revoke a credential and end its live session; True when this call revoked it
    (a conditional UPDATE decides between two at once), False when it was revoked
    already. `holder_moves`: the caller moves or releases the instance's claims in the same
    transaction (a replacement, a member's removal), so no `holder_stalled` is said; it is
    the caller's word, never read from `reason`, which a revoking human writes freely.
    `member_goes`: the whole member is removed in the same transaction, so `member_removed`
    says the lead's end; also the caller's word, for the same reason.
    `stops_placements: False`: the revocation follows a clone the runner removed, whose
    placement rejoins at its next start instead of being stopped (§15.5).

    Every project it writes in is locked first, in the order of their ids, before any write
    (`projects_of`): a caller that writes in more projects took those, with these, in one
    such pass before calling this, and the locks taken again here are harmless."""
    lock_projects(conn, projects_of(conn, [credential_id]))
    now = clock.now()
    won = conn.execute(
        update(t.credential)
        .where(t.credential.c.id == credential_id, t.credential.c.revoked_at.is_(None))
        .values(revoked_at=now, revoked_by=by, revoked_reason=reason)
    ).rowcount
    ended = conn.execute(
        update(t.agent_session)
        .where(t.agent_session.c.credential_id == credential_id, t.agent_session.c.live.is_(True))
        .values(live=None, ended_at=now)
    ).rowcount
    if ended:
        # Every project the instance is attached to now, as `holder_stalled.revoked` reads
        # them; not `attached_now()`, as the credential is revoked by now (§6.17).
        for member in conn.execute(
            select(t.membership.c.id, t.membership.c.project_id)
            .join(
                t.instance_attachment,
                t.instance_attachment.c.membership_id == t.membership.c.id,
            )
            .where(
                t.instance_attachment.c.credential_id == credential_id,
                t.instance_attachment.c.detached_at.is_(None),
            )
            .order_by(t.instance_attachment.c.id)
        ).all():
            environment.refresh(conn, member.project_id, member.id)
    _lead_revoked(conn, credential_id, announce=not member_goes)
    if won == 1:
        # Its open wait ends at once in this process; another replica's ends at its next
        # pass, which reads `revoked_at` (`routes/events`).
        from maity_hub import longpoll

        longpoll.registry.end_keys_after(conn, {credential_id})
    if won == 1 and not holder_moves:  # a holder that stops (§6.5)
        from maity_hub import holder_stalled

        holder_stalled.revoked(conn, credential_id)
    # Every path ends here (the leak, §10's revoke, member removal): a placement that
    # names the credential stops in the same transaction (§15.5).
    if stops_placements:
        placements.credential_revoked(conn, credential_id, by)
    return won == 1


def _lead_revoked(conn: Connection, credential_id: str, *, announce: bool) -> None:
    """A revoked lead stops being lead: `lead_instance: null`, `member_updated` (§6.17), in
    every membership the instance leads and is attached to now (a detach clears its lead
    there, §6.17). Not announced when the whole member is being removed: `member_removed`
    says it."""
    from maity_hub.views import member_view  # views reads the auth modules

    attachment = t.instance_attachment
    rows = conn.execute(
        select(t.membership)
        .join(attachment, attachment.c.membership_id == t.membership.c.id)
        .where(
            attachment.c.credential_id == credential_id,
            attachment.c.detached_at.is_(None),
            t.membership.c.lead_instance == attachment.c.instance,
        )
        .order_by(t.membership.c.id)
    ).all()
    for row in rows:
        conn.execute(
            update(t.membership).where(t.membership.c.id == row.id).values(lead_instance=None)
        )
        if row.active and announce:
            member = conn.execute(select(t.membership).where(t.membership.c.id == row.id)).one()
            emit(
                conn,
                row.project_id,
                "member_updated",
                ["all"],
                {**member_view(conn, member), "changed": ["team"]},
                subject=("member", row.agent_id),
            )


def revoke_runner_credential(
    conn: Connection,
    credential_id: str,
    reason: str | None,
    by: str | None,
    applied: list[dict[str, Any]] | None = None,
    *,
    replaced: bool = False,
) -> bool:
    """Revoke a runner credential and end its live session; False when it was revoked
    already. What the runner's placements lose with it follows in the same transaction,
    so no caller has to remember it (`placements.runner_credential_gone`): its unused
    pickups end, and what was closing closes now unless `replaced`, a re-pair whose new
    credential takes over the same placements (§15.3). Every project the runner is
    attached to learns it from its own `runner_credential_revoked` (§15.10), with the
    rule `runner_revoke.apply` applied there (`keep` where nothing was applied: a leak's
    revocation keeps, §15.3) and the placements it stopped, which the runner is also
    told on its next call."""
    now = clock.now()
    by_project = {a["project_id"]: a for a in applied or []}
    revoked = conn.execute(
        update(t.runner_credential)
        .where(
            t.runner_credential.c.id == credential_id,
            t.runner_credential.c.revoked_at.is_(None),
        )
        .values(
            revoked_at=now, revoked_by=by, revoked_reason=reason, live=None, stopped=applied or []
        )
    ).rowcount
    if revoked != 1:
        return False
    conn.execute(
        update(t.runner_session)
        .where(
            t.runner_session.c.credential_id == credential_id,
            t.runner_session.c.live.is_(True),
        )
        .values(live=None, ended_at=now)
    )
    runner_id = conn.execute(
        select(t.runner_credential.c.runner_id).where(t.runner_credential.c.id == credential_id)
    ).scalar_one()
    for project_id in attached_project_ids(conn, runner_id):
        emit(
            conn,
            project_id,
            "runner_credential_revoked",
            ["trust:owner"],
            {
                "runner_id": runner_id,
                "credential_id": credential_id,
                "reason": reason,
                "on_runner_revoke": by_project.get(project_id, {}).get("rule", "keep"),
                "stopped": by_project.get(project_id, {}).get("stopped", []),
            },
            actor=human_actor(conn, project_id, by),
            subject=("runner", runner_id),
        )
    placements.runner_credential_gone(conn, runner_id, by, replaced=replaced)
    return True
