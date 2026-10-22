"""`GET /admin/users` (docs/api.md §16.1): the instance's humans, for the instance admin."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from maity_hub import tables as t
from maity_hub.admin import instance_admin_id
from maity_hub.deps import HumanCaller, engine_of
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
        if q is not None:
            needle = f"%{q.lower()}%"
            query = query.where(
                func.lower(t.human.c.handle).like(needle)
                | func.lower(t.human.c.display_name).like(needle)
            )
        if cursor is not None:
            if not cursor:
                raise invalid({"cursor": "invalid"})
            query = query.where(t.human.c.handle > cursor)
        rows = conn.execute(query.order_by(t.human.c.handle).limit(limit + 1)).all()
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
        items = [
            {
                "id": r.id,
                "handle": r.handle,
                "display_name": r.display_name,
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
