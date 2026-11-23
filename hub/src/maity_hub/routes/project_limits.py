"""`GET /projects/{owner}/{slug}/limits` (docs/api.md §6.31): every limit a project holds, in
one answer for the dashboard's "Limits" view.

Each value carries its quota details but `name`, `scope` and `max`, and `editable`: whether
the caller sets it. `ceiling.value` only to those who set the value. `max_open_claims` is not
here yet: the hub has no claim limit (tsk-ybc2ma72dzvq).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, select

from maity_hub import ceilings, instances, namespace
from maity_hub import placements as pl
from maity_hub import tables as t
from maity_hub.access import Membership, membership
from maity_hub.deps import AnyCaller, engine_of
from maity_hub.namespace import ProjectRoute
from maity_hub.routes.joins import agents_held
from maity_hub.views import ts

router = APIRouter(route_class=ProjectRoute)


def _value(
    limit: ceilings.Limit,
    count: int,
    full: str,
    *,
    editable: bool,
    member_id: str | None = None,
) -> dict[str, Any]:
    return {
        "limit": limit.limit,
        "source": limit.source,
        "count": count,
        "ceiling": ceilings.ceiling_view(limit, editable),
        "editable": editable,
        "raise": ceilings.raise_of(limit, full, member_id),
    }


def _owner_of_caller(conn: Connection, mine: Membership) -> str:
    """The human whose agents `member_agents_max` counts: the caller, or an agent's owner."""
    if mine.kind == "human":
        return mine.principal_id
    owner: str = conn.execute(
        select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == mine.principal_id)
    ).scalar_one()
    return owner


def _agent_rows(conn: Connection, mine: Membership) -> list[Any]:
    """The agent memberships the caller reads: an agent its own; a human with
    `credentials:admin` every one; any other human those of the profiles they own."""
    m, a = t.membership.c, t.agent_profile.c
    query = (
        select(t.membership, a.handle, a.owner_id.label("profile_owner"))
        .join(t.agent_profile, a.id == m.agent_id)
        .where(m.project_id == mine.project.id, m.active.is_(True))
        .order_by(a.handle, m.agent_id)
    )
    if mine.kind == "agent":
        query = query.where(m.agent_id == mine.principal_id)
    elif not mine.may("credentials:admin"):
        query = query.where(a.owner_id == mine.principal_id)
    return list(conn.execute(query).all())


def _never_listened(conn: Connection, membership_id: int) -> list[dict[str, Any]]:
    """Active instances whose credential never opened a session (`resumed_at` null, §10),
    whatever `last_seen_at` says."""
    c = t.credential.c
    rows = conn.execute(
        select(c.id, c.instance, c.created_at)
        .select_from(instances.credential_join())
        .where(
            t.instance_attachment.c.membership_id == membership_id,
            instances.attached_now(),
            c.resumed_at.is_(None),
        )
        .order_by(c.created_at, c.id)
    ).all()
    return [
        {"credential_id": r.id, "instance": r.instance, "created_at": ts(r.created_at)}
        for r in rows
    ]


def _agents(conn: Connection, mine: Membership, full: str) -> list[dict[str, Any]]:
    found = []
    for row in _agent_rows(conn, mine):
        limit = ceilings.resolve(
            conn, "max_instances", mine.project, row.max_instances, row.profile_owner
        )
        owner = mine.kind == "human" and mine.principal_id == row.profile_owner
        found.append(
            {
                "member": row.agent_id,
                "handle": row.handle,
                "max_instances": _value(
                    limit,
                    pl.instances_held(conn, row.id),
                    full,
                    editable=owner,
                    member_id=row.agent_id,
                ),
                "never_listened": _never_listened(conn, row.id),
            }
        )
    return found


def _runners(conn: Connection, mine: Membership) -> list[dict[str, Any]]:
    """The attached runners, as `GET …/runners` shows them to the caller (§15.4): numbers
    and targets to those who see `capabilities` there and to the runner's owner."""
    sees = mine.may("members:admin") or mine.may("agents:propose")
    rows = conn.execute(
        select(t.runner)
        .join(t.runner_attachment, t.runner_attachment.c.runner_id == t.runner.c.id)
        .where(
            t.runner_attachment.c.project_id == mine.project.id,
            t.runner_attachment.c.active.is_(True),
        )
        .order_by(t.runner.c.name, t.runner.c.id)
    ).all()
    found = []
    for runner in rows:
        shown = sees or runner.owner_id == mine.principal_id
        capabilities = runner.capabilities if isinstance(runner.capabilities, dict) else None
        if not shown or capabilities is None:
            found.append(
                {
                    "id": runner.id,
                    "name": runner.name,
                    "max_agents": None,
                    "running": None,
                    "targets": [],
                }
            )
            continue
        found.append(
            {
                "id": runner.id,
                "name": runner.name,
                "max_agents": capabilities.get("max_agents"),
                "running": capabilities.get("running"),
                "targets": [
                    {
                        "name": target.get("name"),
                        "max_agents": target.get("max_agents"),
                        "running": target.get("running"),
                    }
                    for target in capabilities.get("targets") or []
                    if isinstance(target, dict)
                ],
            }
        )
    return found


@router.get("/projects/{owner}/{slug}/limits")
def project_limits(slug: str, request: Request, caller: AnyCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        project = mine.project
        full = namespace.full_name(conn, project)
        setter = mine.kind == "human" and mine.may("project:admin")
        placements = ceilings.resolve(conn, "max_placements", project, project.max_placements)
        member_agents = ceilings.resolve(
            conn, "member_agents_max", project, project.member_agents_max
        )
        answer: dict[str, Any] = {
            "project": {
                "max_placements": _value(
                    placements, pl.active_count(conn, project.id), full, editable=setter
                ),
                "member_agents_max": _value(
                    member_agents,
                    len(agents_held(conn, project.id, _owner_of_caller(conn, mine))),
                    full,
                    editable=setter,
                ),
            },
            "agents": _agents(conn, mine, full),
        }
        if mine.kind == "human" or mine.may("agents:propose"):
            answer["runners"] = _runners(conn, mine)
        return JSONResponse(answer)
