"""`GET /admin/users` (docs/api.md §16.1): the instance's humans, for the instance admin."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from maity_hub import avatars
from maity_hub import tables as t
from maity_hub.admin import instance_admin_id, require_instance_admin
from maity_hub.auth import second_factor, second_factor_reset
from maity_hub.deps import HumanCaller, engine_of, settings_of
from maity_hub.errors import forbidden, invalid
from maity_hub.views import ts

router = APIRouter()

PAGE_DEFAULT, PAGE_MAX = 50, 200


@router.get("/admin/users")
def list_users(
    request: Request,
    caller: HumanCaller,
    q: str | None = Query(default=None, min_length=1, max_length=64),
    disabled: bool | None = None,
    limit: int = Query(default=PAGE_DEFAULT, ge=1, le=PAGE_MAX),
    cursor: str | None = Query(default=None, max_length=64),
) -> JSONResponse:
    with engine_of(request).begin() as conn:
        admin = instance_admin_id(conn)
        if caller.principal_id != admin:
            raise forbidden("instance:admin")
        if disabled is True:  # no account is disabled before the accounts design (§16.1)
            return JSONResponse({"items": [], "next_cursor": None})
        query = select(t.human)
        if cursor is not None:
            if not cursor:
                raise invalid({"cursor": "invalid"})
            query = query.where(t.human.c.handle > cursor)
        query = query.order_by(t.human.c.handle)
        if q is None:
            rows = conn.execute(query.limit(limit + 1)).all()
        else:
            # Matched here, not with LIKE: no wildcard in `q` to escape, and the same
            # case folding on every database (SQLite's lower() is ASCII only). An
            # instance's humans are few; the whole list is read.
            needle = q.casefold()
            rows = [
                row
                for row in conn.execute(query).all()
                if needle in row.handle.casefold() or needle in row.display_name.casefold()
            ][: limit + 1]
        page = rows[:limit]
        ids = [r.id for r in page]
        memberships = _counts(
            conn,
            select(t.membership.c.human_id, func.count())
            .where(t.membership.c.human_id.in_(ids), t.membership.c.active.is_(True))
            .group_by(t.membership.c.human_id),
        )
        agents = _counts(
            conn,
            select(t.agent_profile.c.owner_id, func.count())
            .where(t.agent_profile.c.owner_id.in_(ids))
            .group_by(t.agent_profile.c.owner_id),
        )
        pictures = avatars.urls(conn, ids)
        items = [
            {
                "id": r.id,
                "handle": r.handle,
                "display_name": r.display_name,
                "avatar_url": pictures[r.id],
                "instance_admin": r.id == admin,
                "disabled": False,
                "created_at": ts(r.created_at),
                "last_login_at": ts(r.last_login_at),
                "last_seen_at": ts(r.last_seen_at),
                "memberships": memberships.get(r.id, 0),
                "agents": agents.get(r.id, 0),
            }
            for r in page
        ]
        next_cursor = page[-1].handle if len(rows) > limit else None
        return JSONResponse({"items": items, "next_cursor": next_cursor})


def _counts(conn: Any, query: Any) -> dict[str, int]:
    return {key: int(count) for key, count in conn.execute(query).all()}


class ResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


@router.post("/admin/users/{human_id}/second-factor/reset")
def reset_second_factor(
    human_id: str, body: ResetRequest, request: Request, caller: HumanCaller
) -> JSONResponse:
    """Mails the human a link; the reset takes effect only when they confirm it (§2.8.3)."""
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        require_instance_admin(conn, caller.principal_id)
        second_factor.require_step_up(conn, hub, caller)  # §2.8.4
        expires = second_factor_reset.request_reset(
            conn, hub, caller.principal_id, human_id, body.reason.strip() or body.reason
        )
    return JSONResponse({"expires_at": expires}, status_code=202)
