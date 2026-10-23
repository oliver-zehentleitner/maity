"""`GET /me` (docs/api.md §5.1)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, select

from maity_hub import avatars, clock, images
from maity_hub import tables as t
from maity_hub.admin import is_instance_admin
from maity_hub.auth.caller import Caller
from maity_hub.deps import AnyCaller, engine_of
from maity_hub.views import agent_member, human_member

router = APIRouter()


@router.get("/me")
def me(request: Request, caller: AnyCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        if caller.kind == "human":
            assert caller.human_id is not None
            body = human_body(conn, caller.human_id)
        else:
            agent = conn.execute(
                select(t.agent_profile).where(t.agent_profile.c.id == caller.agent_id)
            ).one()
            body = {
                "member": {**agent_member(agent, avatar_url=None), **avatars.state(conn, agent.id)},
                "projects": _agent_project(conn, caller),
            }
    body["server_time"] = clock.rfc3339(clock.now())
    return JSONResponse(body)


def human_body(conn: Connection, human_id: str) -> dict[str, Any]:
    """A human's `/me` without `server_time`; also the answer of `POST /me/limit`."""
    human = conn.execute(select(t.human).where(t.human.c.id == human_id)).one()
    return {
        "member": {
            **human_member(human, avatar_url=None),
            **avatars.state(conn, human.id),
            "instance_admin": is_instance_admin(conn, human.id),
            # The human's own limit, with the reason other readers may not see (§6.12).
            "limit": limit_view(human),
        },
        "projects": _human_projects(conn, human.id),
    }


def limit_view(human: Any) -> dict[str, Any] | None:
    if human.limit_until is None or human.limit_until <= clock.now():
        return None
    return {
        "until": clock.rfc3339(human.limit_until),
        "since": clock.rfc3339(human.limit_since),
        "reason": human.limit_reason,
        "show_reason_in": list(human.limit_show_reason_in or []),
    }


def _project_row(project: Any, role: str, shown: dict[str, Any]) -> dict[str, Any]:
    logo = shown["logo"]
    return {
        "slug": project.slug,
        "name": project.name,
        "state": project.state,
        "role": role,
        # A project switcher shows each project's image without reading every project.
        "logo": {"available": logo["available"], "etag": logo.get("etag")},
    }


def _human_projects(conn: Connection, human_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        select(
            t.membership.c.id,
            t.membership.c.role,
            t.project.c.id.label("project_id"),
            t.project.c.slug,
            t.project.c.name,
            t.project.c.state,
        )
        .join(t.project, t.project.c.id == t.membership.c.project_id)
        .where(t.membership.c.human_id == human_id, t.membership.c.removed_at.is_(None))
        .order_by(t.project.c.slug)
    ).all()
    shown = images.views(conn, [row.project_id for row in rows])
    return [
        {
            **_project_row(row, row.role, shown[row.project_id]),
            "open_requests": open_requests(conn, row.id, row.role),
        }
        for row in rows
    ]


def _agent_project(conn: Connection, caller: Caller) -> list[dict[str, Any]]:
    row = conn.execute(
        select(t.membership.c.role, t.project)
        .join(t.project, t.project.c.id == t.membership.c.project_id)
        .where(t.membership.c.id == caller.membership_id)
    ).one()
    return [_project_row(row, row.role, images.views(conn, [row.id])[row.id])]


def open_requests(conn: Connection, membership_id: int, role: str) -> int:
    """Open requests addressed to this membership: `GET …/requests` with `to=me` (§7),
    through the listing's own rule so that the two cannot drift."""
    from maity_hub import inbox
    from maity_hub.access import Membership

    row = conn.execute(select(t.membership).where(t.membership.c.id == membership_id)).one()
    project = conn.execute(select(t.project).where(t.project.c.id == row.project_id)).one()
    mine = Membership(project, row, "agent" if row.agent_id else "human")
    open_rows = conn.execute(
        select(t.request).where(
            t.request.c.project_id == row.project_id, t.request.c.status == "open"
        )
    ).all()
    return sum(1 for r in open_rows if inbox.addressed_to(conn, r, mine))
