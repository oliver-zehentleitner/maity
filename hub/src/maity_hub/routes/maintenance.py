"""Maintenance windows (docs/api.md §16.12): the public read, the instance admin's routes, and
each human's choice which of its agents receive the hub's broadcasts."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import Connection, or_, select, update

from maity_hub import clock, events, maintenance, paging
from maity_hub import tables as t
from maity_hub.admin import require_instance_admin
from maity_hub.deps import HumanCaller, engine_of
from maity_hub.errors import ApiError, invalid
from maity_hub.views import ts

router = APIRouter()

PAGE_DEFAULT, PAGE_MAX = 50, 200


class WindowBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The contract's name; `from` is a keyword in Python.
    from_: AwareDatetime = Field(alias="from")
    until: AwareDatetime
    text: str


class BroadcastsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str
    agents: list[str] = []


def _admin(conn: Connection, caller: Any) -> None:
    require_instance_admin(conn, caller.principal_id)


@router.get("/maintenance")
def read_window(request: Request) -> JSONResponse:
    """Anyone, no sign-in: what the web reads for its banner and the full page."""
    return JSONResponse({"window": maintenance.window_now(engine_of(request))})


@router.get("/admin/maintenance")
def admin_window(request: Request, caller: HumanCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        _admin(conn, caller)
        return JSONResponse({"window": maintenance.view(maintenance.current(conn), admin=True)})


@router.put("/admin/maintenance")
def put_window(request: Request, caller: HumanCaller, body: WindowBody) -> JSONResponse:
    text = body.text.strip()
    with events.transaction(engine_of(request)) as conn:
        _admin(conn, caller)
        row = maintenance.current(conn)
        errors = maintenance.check({"from": body.from_, "until": body.until, "text": text}, row)
        if errors:
            raise invalid(errors)
        saved = maintenance.put(conn, body.from_, body.until, text, caller.principal_id)
        return JSONResponse({"window": maintenance.view(saved, admin=True)})


@router.delete("/admin/maintenance")
def cancel_window(request: Request, caller: HumanCaller) -> JSONResponse:
    with events.transaction(engine_of(request)) as conn:
        _admin(conn, caller)
        row = maintenance.current(conn)
        if row is not None and maintenance.state(row) == "running":
            raise ApiError(409, "maintenance_running", "a running window is ended, not cancelled")
        if row is not None:
            maintenance.cancel(conn, row, caller.principal_id)
    return JSONResponse({"window": None})


@router.post("/admin/maintenance/end")
def end_window(request: Request, caller: HumanCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        _admin(conn, caller)
        row = maintenance.current(conn)
        if row is None or maintenance.state(row) != "running":
            raise ApiError(409, "maintenance_not_running", "no window is running")
        maintenance.end(conn, row, caller.principal_id)
    return JSONResponse({"window": None})


@router.get("/admin/maintenance/changes")
def list_changes(
    request: Request,
    caller: HumanCaller,
    limit: int = Query(default=PAGE_DEFAULT, ge=1, le=PAGE_MAX),
    cursor: str | None = Query(default=None, max_length=200),
) -> JSONResponse:
    c = t.maintenance_change.c
    with engine_of(request).begin() as conn:
        _admin(conn, caller)
        query = select(t.maintenance_change)
        if cursor is not None:
            at, row_id = paging.uncursor(cursor)
            query = query.where(or_(c.at < at, (c.at == at) & (c.id < row_id)))
        rows = conn.execute(query.order_by(c.at.desc(), c.id.desc()).limit(limit + 1)).all()
    page = rows[:limit]
    return JSONResponse(
        {
            "items": [
                {
                    "id": r.id,
                    "action": r.action,
                    "window": {
                        "id": r.window_id,
                        "from": clock.rfc3339(r.starts_at),
                        "until": clock.rfc3339(r.ends_at),
                        "text": r.text,
                    },
                    "by": r.by,
                    "at": ts(r.at),
                }
                for r in page
            ],
            "next_cursor": paging.cursor(page[-1].at, page[-1].id) if len(rows) > limit else None,
        }
    )


def _own_agents(conn: Connection, human_id: str) -> list[str]:
    return list(
        conn.execute(
            select(t.agent_profile.c.id).where(t.agent_profile.c.owner_id == human_id)
        ).scalars()
    )


@router.get("/me/broadcasts")
def get_broadcasts(request: Request, caller: HumanCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        value = conn.execute(
            select(t.human.c.broadcasts).where(t.human.c.id == caller.principal_id)
        ).scalar_one_or_none()
    return JSONResponse(maintenance.choice(value))


@router.patch("/me/broadcasts")
def patch_broadcasts(request: Request, caller: HumanCaller, body: BroadcastsBody) -> JSONResponse:
    with engine_of(request).begin() as conn:
        wanted = {"mode": body.mode, "agents": list(dict.fromkeys(body.agents))}
        errors = maintenance.check_choice(wanted, _own_agents(conn, caller.principal_id))
        if errors:
            raise invalid(errors)
        conn.execute(
            update(t.human).where(t.human.c.id == caller.principal_id).values(broadcasts=wanted)
        )
    return JSONResponse(wanted)
