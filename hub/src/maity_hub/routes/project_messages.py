"""`GET /projects/{slug}/messages` (docs/api.md §8.8): the project's messages as one listing.

The readable set of `GET /events` (§8.2), restricted to the `message` events that belong to
no conversation. The conversation is read off the event row, which survives a redaction, so
a redacted chat message is never listed here.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, select

from maity_hub import events, paging
from maity_hub import tables as t
from maity_hub.access import Membership, membership
from maity_hub.deps import AnyCaller, engine_of
from maity_hub.errors import invalid
from maity_hub.routes.events import MESSAGE_TYPES, PAGE_DEFAULT, PAGE_MAX
from maity_hub.views import _without_reason, principal_ids, ts

router = APIRouter()

SEQ_MAX = 2**63 - 1  # BIGINT
LISTED_TYPES = tuple(kind for kind in MESSAGE_TYPES if kind != "chat")
BATCH = 500


def _seq(request: Request, name: str) -> int | None:
    raw = request.query_params.get(name)
    if raw is None:
        return None
    if not raw.isascii() or not raw.isdigit() or int(raw) > SEQ_MAX:
        raise invalid({name: "not_a_seq"})
    return int(raw)


def _types(request: Request) -> tuple[str, ...]:
    """`type`, repeatable or a comma list, compared as a set (§8.8)."""
    given = {
        part.strip()
        for value in request.query_params.getlist("type")
        for part in value.split(",")
        if part.strip()
    }
    if not given <= set(LISTED_TYPES):
        raise invalid({"type": "unknown"})
    return tuple(sorted(given))


def _limit(request: Request) -> int:
    raw = request.query_params.get("limit", str(PAGE_DEFAULT))
    if not raw.isdigit() or not 1 <= int(raw) <= PAGE_MAX:
        raise invalid({"limit": "out_of_range"})
    return int(raw)


def _listed(row: Any, types: tuple[str, ...]) -> bool:
    """A tombstone has no type: it is listed only without a `type` filter."""
    if not types:
        return True
    return not row.redacted and (row.payload or {}).get("type") in types


def _scan(
    conn: Connection,
    mine: Membership,
    types: tuple[str, ...],
    start: int,
    limit: int,
    *,
    oldest_first: bool,
) -> list[Any]:
    """Up to `limit` readable messages past `start` in the direction, and one more when
    there is a further page."""
    found: list[Any] = []
    position = start
    while True:
        query = select(t.event).where(
            t.event.c.project_id == mine.project.id,
            t.event.c.kind == "message",
            t.event.c.conversation_id.is_(None),
        )
        if oldest_first:
            query = query.where(t.event.c.seq > position).order_by(t.event.c.seq)
        else:
            query = query.where(t.event.c.seq < position).order_by(t.event.c.seq.desc())
        batch = conn.execute(query.limit(BATCH)).all()
        hidden = events.hidden_redactions(conn, batch, mine.row)
        for row in batch:
            if events.readable_by(row, mine.row, mine.principal_id, hidden) and _listed(row, types):
                found.append(row)
                if len(found) > limit:
                    return found
            position = row.seq
        if len(batch) < BATCH:
            return found


def _items(conn: Connection, rows: list[Any], mine: Membership) -> list[dict[str, Any]]:
    senders = principal_ids(conn, (r.actor_membership for r in rows))
    items = []
    for row in rows:
        payload = row.payload or {}
        tomb = _without_reason(row, mine) if row.redacted else None
        items.append(
            {
                "id": f"evt-{row.seq}",
                "seq": row.seq,
                "type": None if row.redacted else payload.get("type"),
                "from": senders.get(row.actor_membership),
                "to": None if row.redacted else payload.get("to"),
                "task_id": None if row.redacted else payload.get("task_id"),
                "body": None if row.redacted else payload.get("body"),
                "sent_at": ts(row.at),
                "mentions": [] if row.redacted else payload.get("mentions") or [],
                "attachments": [],  # the contract's shape before attachments land (§8.7)
                "redacted": bool(row.redacted),
                "redaction": (
                    {"at": tomb.get("at"), "by": tomb.get("by"), "reason": tomb.get("reason")}
                    if tomb
                    else None
                ),
            }
        )
    return items


@router.get("/projects/{slug}/messages")
def read_project_messages(slug: str, request: Request, caller: AnyCaller) -> JSONResponse:
    limit = _limit(request)
    after, before = _seq(request, "after"), _seq(request, "before")
    if after is not None and before is not None:
        raise invalid({"before": "with_after"}, "after or before, not both")
    types = _types(request)
    bound = paging.scope(after=after, before=before, type=list(types))
    cursor = request.query_params.get("cursor")
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        oldest_first = after is not None
        if cursor is not None:
            start = paging.unseq(cursor, bound)
        elif oldest_first:
            start = after or 0
        else:
            start = before if before is not None else SEQ_MAX
        rows = _scan(conn, mine, types, start, limit, oldest_first=oldest_first)
        page = rows[:limit]
        next_cursor = paging.seq_cursor(page[-1].seq, bound) if len(rows) > limit else None
        return JSONResponse({"items": _items(conn, page, mine), "next_cursor": next_cursor})
