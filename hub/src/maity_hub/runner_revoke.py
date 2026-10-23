"""What revoking or removing a runner does to its agents (docs/api.md §15.3).

Per attached project the rule is `keep` or `stop`: the owner's `agents: "stop"`
override, else the project's `on_runner_revoke` within the instance setting
(`policy.runner_revoke_rule`). `stop` closes the runner's active placements there at
once and revokes the agent credentials they named: at once under the override,
otherwise `stop_grace_seconds` later, so that an agent can park its work first. A
credential due is refused from then on (`credential_revoked`, `runner_revoked`) and
shown as revoked; its revocation is written the first time it is used after that.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, select, update

from maity_hub import clock, placements, policy
from maity_hub import tables as t
from maity_hub.runners import attached_project_ids, human_actor

REASON = "runner_revoked"


class RevocationDue(Exception):
    """An agent credential whose revocation fell due: written in a transaction of its
    own, since the call's own transaction rolls back with its refusal."""

    def __init__(self, credential_id: str, by: str | None) -> None:
        super().__init__(credential_id)
        self.credential_id = credential_id
        self.by = by


def due(row: Any) -> bool:
    """Whether a credential row's revocation after a runner's stop has fallen due."""
    when = getattr(row, "revoke_due_at", None)
    return row.revoked_at is None and when is not None and when <= clock.now()


def revoke_due(conn: Connection, credential_id: str, by: str | None) -> None:
    from maity_hub.auth.leaks import revoke

    row = conn.execute(select(t.credential).where(t.credential.c.id == credential_id)).one()
    if due(row):
        revoke(conn, credential_id, REASON, by)


def apply(
    conn: Connection,
    runner_id: str,
    *,
    agents: str,
    instance_rule: str,
    removing: bool,
    by: str,
) -> list[dict[str, Any]]:
    """Apply each attached project's rule; returns `[{project_id, rule, stopped}]`.
    Under `DELETE` the placements close as `runner_removed`, under a revoke as
    `runner_revoked`; under `keep` nothing here changes."""
    from maity_hub.auth.leaks import revoke

    now = clock.now()
    reason = "runner_removed" if removing else REASON
    results = []
    for project_id in attached_project_ids(conn, runner_id):
        project = conn.execute(select(t.project).where(t.project.c.id == project_id)).one()
        rule = "stop" if agents == "stop" else policy.runner_revoke_rule(project, instance_rule)
        stopped: list[str] = []
        if rule == "stop":
            actor = human_actor(conn, project_id, by)
            for placement in placements.active_rows(
                conn,
                t.placement.c.runner_id == runner_id,
                t.placement.c.project_id == project_id,
            ):
                placements.withdraw_open_request(conn, placement, "the runner was revoked", actor)
                placements.close_now(conn, placement, reason, actor, by)
                stopped.append(placement.id)
                if placement.credential_id is None:
                    continue
                if agents == "stop":  # the machine is in doubt: no grace (§15.3)
                    revoke(conn, placement.credential_id, REASON, by)
                else:
                    grace = timedelta(seconds=placement.stop_grace_seconds)
                    conn.execute(
                        update(t.credential)
                        .where(
                            t.credential.c.id == placement.credential_id,
                            t.credential.c.revoked_at.is_(None),
                        )
                        .values(revoke_due_at=now + grace, revoke_due_by=by)
                    )
        results.append({"project_id": project_id, "rule": rule, "stopped": stopped})
    return results


def answer(
    conn: Connection, results: list[dict[str, Any]], human_id: str | None
) -> list[dict[str, Any]]:
    """`on_runner_revoke` of the revoke's or the DELETE's answer: the projects the
    caller is a member of (§15.3)."""
    if human_id is None:
        return []
    member_of = set(
        conn.execute(
            select(t.membership.c.project_id).where(
                t.membership.c.human_id == human_id, t.membership.c.active.is_(True)
            )
        ).scalars()
    )
    slugs = {r.id: r.slug for r in conn.execute(select(t.project.c.id, t.project.c.slug))}
    return [
        {"project": slugs[r["project_id"]], "rule": r["rule"], "stopped": r["stopped"]}
        for r in results
        if r["project_id"] in member_of
    ]
