"""Takeovers: opening one on a held card, reading them, the holder's answer, the
requester's withdrawal and the admin team's override (docs/api.md §6.19). The rules
are in `takeovers.py`."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection, and_, or_, select

from maity_hub import idempotency, paging, takeovers
from maity_hub import tables as t
from maity_hub.access import Membership, membership
from maity_hub.deps import AnyCaller, engine_of
from maity_hub.errors import invalid, not_found
from maity_hub.events import transaction
from maity_hub.models import Strict, markdown

router = APIRouter()

PAGE_DEFAULT, PAGE_MAX = 50, 200


class TakeoverIn(Strict):
    reason: str = markdown(min_length=1)
    to: str | None = Field(default=None, max_length=64)


class ObjectionIn(Strict):
    reasons: str = markdown(min_length=1)


class RespondIn(Strict):
    accept: Literal[True] | None = None
    object: ObjectionIn | None = None


class ReasonIn(Strict):
    reason: str | None = markdown(default=None)


class OverrideIn(Strict):
    reason: str = markdown(min_length=1)


def _load(conn: Connection, takeover_id: str, request: Request | None = None) -> dict[str, Any]:
    return takeovers.view(conn, takeovers.load(conn, takeover_id))


idempotency.LOADERS["takeover"] = _load


def _takeover(conn: Connection, mine: Membership, takeover_id: str) -> Any:
    """The takeover in the caller's project, after time has moved it on."""
    takeovers.settle(conn, mine.project.id)
    row = conn.execute(
        select(t.takeover).where(
            t.takeover.c.id == takeover_id, t.takeover.c.project_id == mine.project.id
        )
    ).first()
    if row is None:
        raise not_found()
    return row


def _outcome(conn: Connection, takeover_id: str, status: int = 200) -> idempotency.Outcome:
    return idempotency.Outcome(status, "takeover", takeover_id, _load(conn, takeover_id))


@router.post("/projects/{slug}/tasks/{card_id}/takeover")
def open_takeover(
    slug: str, card_id: str, body: TakeoverIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        takeovers.settle(conn, mine.project.id)
        card = conn.execute(
            select(t.card).where(t.card.c.id == card_id, t.card.c.project_id == mine.project.id)
        ).first()
        if card is None:
            raise not_found()
        # A card a human holds is never taken over, by anyone: said before the scope and
        # the lease, as on the card routes (§2.3, §6.19).
        takeovers.refuse_human_holder(conn, card)
        mine.require("tasks:write")
        row, status = takeovers.open_takeover(conn, mine, caller, card, body.reason, body.to)
        return _outcome(conn, row.id, status)

    return idempotency.run(engine_of(request), request, caller, action)


@router.get("/projects/{slug}/takeovers")
def list_takeovers(
    slug: str,
    request: Request,
    caller: AnyCaller,
    status: Literal["open", "all"] = "open",
    task_id: str | None = None,
    limit: int = Query(default=PAGE_DEFAULT, ge=1, le=PAGE_MAX),
    cursor: str | None = None,
) -> JSONResponse:
    c = t.takeover.c
    bound = paging.scope(status=status, task_id=task_id)
    with transaction(engine_of(request)) as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        takeovers.settle(conn, mine.project.id)
        query = select(t.takeover).where(c.project_id == mine.project.id)
        if status == "open":
            query = query.where(c.status.in_(takeovers.OPEN))
        if task_id is not None:
            query = query.where(c.task_id == task_id)
        if cursor is not None:
            after_at, after_id = paging.uncursor(cursor, bound)
            query = query.where(
                or_(c.created_at < after_at, and_(c.created_at == after_at, c.id < after_id))
            )
        rows = conn.execute(query.order_by(c.created_at.desc(), c.id.desc()).limit(limit + 1)).all()
        page = rows[:limit]
        next_cursor = (
            paging.cursor(page[-1].created_at, page[-1].id, bound) if len(rows) > limit else None
        )
        items = [takeovers.view(conn, r) for r in page]
    return JSONResponse({"items": items, "next_cursor": next_cursor})


@router.get("/projects/{slug}/takeovers/{takeover_id}")
def get_takeover(slug: str, takeover_id: str, request: Request, caller: AnyCaller) -> JSONResponse:
    with transaction(engine_of(request)) as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        return JSONResponse(takeovers.view(conn, _takeover(conn, mine, takeover_id)))


@router.post("/projects/{slug}/takeovers/{takeover_id}/respond")
def respond(
    slug: str, takeover_id: str, body: RespondIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    if (body.accept is None) == (body.object is None):
        raise invalid({"respond": "one_of"}, "answer with accept or object")

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        row = _takeover(conn, mine, takeover_id)
        takeovers.refuse_closed(row)
        takeovers.respond(
            conn,
            mine,
            caller,
            row,
            accept=body.accept is True,
            reasons=body.object.reasons if body.object else None,
        )
        return _outcome(conn, row.id)

    return idempotency.run(engine_of(request), request, caller, action)


@router.post("/projects/{slug}/takeovers/{takeover_id}/withdraw")
def withdraw(
    slug: str, takeover_id: str, body: ReasonIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        row = _takeover(conn, mine, takeover_id)
        takeovers.refuse_closed(row)
        takeovers.withdraw(conn, mine, caller, row, body.reason)
        return _outcome(conn, row.id)

    return idempotency.run(engine_of(request), request, caller, action)


@router.post("/projects/{slug}/takeovers/{takeover_id}/escalate")
def escalate(
    slug: str, takeover_id: str, body: ReasonIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        row = _takeover(conn, mine, takeover_id)
        takeovers.refuse_closed(row)
        takeovers.request_escalation(conn, mine, caller, row, body.reason)
        return _outcome(conn, row.id)

    return idempotency.run(engine_of(request), request, caller, action)


@router.post("/projects/{slug}/takeovers/{takeover_id}/override")
def override(
    slug: str, takeover_id: str, body: OverrideIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        row = _takeover(conn, mine, takeover_id)
        takeovers.refuse_closed(row)
        takeovers.override(conn, mine, caller, row, body.reason)
        return _outcome(conn, row.id)

    return idempotency.run(engine_of(request), request, caller, action)
