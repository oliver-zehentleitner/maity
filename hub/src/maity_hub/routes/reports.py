"""Abuse reports (docs/api.md §16.8): `POST /reports` and `GET /me/reports` for whoever is
signed in, `GET /admin/reports`, `GET /admin/reports/{id}` and its `resolve` for the
instance admin."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, and_, case, or_, select

from maity_hub import idempotency, paging, reports
from maity_hub import tables as t
from maity_hub.admin import require_instance_admin
from maity_hub.deps import AnyCaller, HumanCaller, engine_of
from maity_hub.errors import forbidden, invalid, not_found
from maity_hub.views import ts

router = APIRouter()

PAGE_DEFAULT, PAGE_MAX = 50, 200
STATUSES = ("open", "resolved", "all")


def _load(conn: Connection, report_id: str) -> dict[str, Any]:
    row = conn.execute(select(t.abuse_report).where(t.abuse_report.c.id == report_id)).one()
    return {"id": row.id, "created_at": ts(row.created_at)}


idempotency.LOADERS["abuse_report"] = idempotency.plain(_load)


@router.post("/reports")
async def file_report(request: Request, caller: AnyCaller) -> JSONResponse:
    if caller.kind not in ("human", "agent"):
        raise forbidden(message="a report is a human's or an agent's")
    try:
        body = await request.json()
    except ValueError:
        raise invalid({"body": "not_json"}) from None
    if not isinstance(body, dict) or set(body) - {"target", "reason", "text"}:
        raise invalid({"body": "unknown_field"})

    def action(conn: Connection) -> idempotency.Outcome:
        made = reports.create(conn, caller, body)
        return idempotency.Outcome(201, "abuse_report", made["id"], made)

    return idempotency.run(engine_of(request), request, caller, action)


@router.get("/me/reports")
def my_reports(
    request: Request,
    caller: AnyCaller,
    limit: int = Query(default=PAGE_DEFAULT, ge=1, le=PAGE_MAX),
    cursor: str | None = None,
) -> JSONResponse:
    """The caller's own reports, newest first: status and action only (§16.8)."""
    if caller.kind not in ("human", "agent"):
        raise forbidden(message="a report is a human's or an agent's")
    bound = paging.scope(list="me/reports")
    with engine_of(request).begin() as conn:
        reports.expire(conn)
        r = t.abuse_report.c
        query = select(t.abuse_report).where(r.reporter == caller.principal_id)
        if cursor is not None:
            at, after = paging.uncursor(cursor, bound)
            query = query.where(or_(r.created_at < at, and_(r.created_at == at, r.id < after)))
        rows = conn.execute(query.order_by(r.created_at.desc(), r.id.desc()).limit(limit + 1)).all()
        page = rows[:limit]
        next_cursor = (
            paging.cursor(page[-1].created_at, page[-1].id, bound) if len(rows) > limit else None
        )
        return JSONResponse(
            {"items": [reports.own_view(conn, row) for row in page], "next_cursor": next_cursor}
        )


@router.get("/admin/reports")
def list_reports(
    request: Request,
    caller: HumanCaller,
    status: str = "all",
    type: str | None = None,
    limit: int = Query(default=PAGE_DEFAULT, ge=1, le=PAGE_MAX),
    cursor: str | None = None,
) -> JSONResponse:
    """Open reports first, then the rest, each newest first (§16.8). `resolved` lists
    every closed report, the expired ones included."""
    if status not in STATUSES:
        raise invalid({"status": "unknown"})
    if type is not None and type not in reports.TYPES:
        raise invalid({"type": "unknown"})
    bound = paging.scope(list="admin/reports", status=status, type=type)
    with engine_of(request).begin() as conn:
        require_instance_admin(conn, caller.principal_id)
        reports.expire(conn)
        r = t.abuse_report.c
        rank = case((r.status == "open", 0), else_=1)
        query = select(t.abuse_report, rank.label("rank"))
        if status == "open":
            query = query.where(r.status == "open")
        elif status == "resolved":
            query = query.where(r.status != "open")
        if type is not None:
            query = query.where(r.target_type == type)
        if cursor is not None:
            at, key = paging.uncursor(cursor, bound)
            after_rank, _, after_id = key.partition(":")
            if after_rank not in ("0", "1"):
                raise invalid({"cursor": "invalid"})
            query = query.where(
                or_(
                    rank > int(after_rank),
                    and_(
                        rank == int(after_rank),
                        or_(r.created_at < at, and_(r.created_at == at, r.id < after_id)),
                    ),
                )
            )
        rows = conn.execute(
            query.order_by(rank, r.created_at.desc(), r.id.desc()).limit(limit + 1)
        ).all()
        page = rows[:limit]
        next_cursor = (
            paging.cursor(page[-1].created_at, f"{page[-1].rank}:{page[-1].id}", bound)
            if len(rows) > limit
            else None
        )
        items = [reports.admin_view(conn, row, snapshot=False) for row in page]
        return JSONResponse({"items": items, "next_cursor": next_cursor})


@router.get("/admin/reports/{report_id}")
def get_report(report_id: str, request: Request, caller: HumanCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        require_instance_admin(conn, caller.principal_id)
        reports.expire(conn)
        row = conn.execute(select(t.abuse_report).where(t.abuse_report.c.id == report_id)).first()
        if row is None:
            raise not_found()
        return JSONResponse(reports.admin_view(conn, row, snapshot=True))


@router.post("/admin/reports/{report_id}/resolve")
async def resolve_report(report_id: str, request: Request, caller: HumanCaller) -> JSONResponse:
    try:
        body = await request.json()
    except ValueError:
        raise invalid({"body": "not_json"}) from None
    if not isinstance(body, dict) or set(body) - {"action", "note"}:
        raise invalid({"body": "unknown_field"})

    def action(conn: Connection) -> idempotency.Outcome:
        require_instance_admin(conn, caller.principal_id)
        shown = reports.resolve(
            conn, caller.principal_id, report_id, body.get("action"), body.get("note")
        )
        return idempotency.Outcome(200, None, None, shown)

    return idempotency.run(engine_of(request), request, caller, action)
