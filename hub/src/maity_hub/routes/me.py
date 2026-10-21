"""`GET /me` (docs/api.md §5.1)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, and_, func, or_, select

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.auth.caller import Caller
from maity_hub.deps import AnyCaller, engine_of
from maity_hub.views import agent_member, human_member

router = APIRouter()


@router.get("/me")
def me(request: Request, caller: AnyCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        if caller.kind == "human":
            human = conn.execute(select(t.human).where(t.human.c.id == caller.human_id)).one()
            body: dict[str, Any] = {
                "member": human_member(human),
                "projects": _human_projects(conn, human.id),
            }
        else:
            agent = conn.execute(
                select(t.agent_profile).where(t.agent_profile.c.id == caller.agent_id)
            ).one()
            body = {
                "member": agent_member(agent),
                "projects": _agent_project(conn, caller),
            }
    body["server_time"] = clock.rfc3339(clock.now())
    return JSONResponse(body)


def _project_row(project: Any, role: str) -> dict[str, Any]:
    return {"slug": project.slug, "name": project.name, "state": project.state, "role": role}


def _human_projects(conn: Connection, human_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        select(t.membership.c.id, t.membership.c.role, t.project)
        .join(t.project, t.project.c.id == t.membership.c.project_id)
        .where(t.membership.c.human_id == human_id, t.membership.c.removed_at.is_(None))
        .order_by(t.project.c.slug)
    ).all()
    return [
        {**_project_row(row, row.role), "open_requests": open_requests(conn, row.id, row.role)}
        for row in rows
    ]


def _agent_project(conn: Connection, caller: Caller) -> list[dict[str, Any]]:
    row = conn.execute(
        select(t.membership.c.role, t.project)
        .join(t.project, t.project.c.id == t.membership.c.project_id)
        .where(t.membership.c.id == caller.membership_id)
    ).one()
    return [_project_row(row, row.role)]


def open_requests(conn: Connection, membership_id: int, role: str) -> int:
    """Open requests addressed to this membership: `GET …/requests` with `to=me` (§7)."""
    addressed = [t.request.c.to_member == membership_id, t.request.c.to_role == role]
    if role == "owner":
        addressed.append(t.request.c.to_kind == "owner")
    membership = select(t.membership.c.project_id).where(t.membership.c.id == membership_id)
    count = conn.execute(
        select(func.count()).where(
            and_(
                t.request.c.project_id == membership.scalar_subquery(),
                t.request.c.status == "open",
                or_(*addressed),
            )
        )
    ).scalar_one()
    return int(count)
