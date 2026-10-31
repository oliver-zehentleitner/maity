"""`GET /projects/{owner}/{slug}/messages` (docs/api.md §8.8): the project's messages, listed.

The readable set of `GET /events` (§8.2), restricted to the `message` events that belong to
no conversation. The conversation is read off the event row, which survives a redaction, so
a redacted chat message is never listed here.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, select

from maity_hub import events, instances, paging
from maity_hub import tables as t
from maity_hub.access import Membership, membership
from maity_hub.deps import AnyCaller, engine_of
from maity_hub.errors import invalid
from maity_hub.namespace import ProjectRoute
from maity_hub.routes.events import MESSAGE_TYPES, PAGE_DEFAULT, PAGE_MAX
from maity_hub.views import _without_reason, principal_ids, shape_deleted, ts

router = APIRouter(route_class=ProjectRoute)

SEQ_MAX = paging.SEQ_MAX
LISTED_TYPES = tuple(kind for kind in MESSAGE_TYPES if kind != "chat")
BATCH = 500
SCAN_BUDGET = 2000  # events examined per page; a sparse filter continues on the next one


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
) -> tuple[list[Any], int | None]:
    """The page past `start` in the direction, and where the next one goes on: after the
    last message shown when one more was found, else after the last row examined when the
    scan budget ran out (a page may then be short or empty), else `None` at the end of
    the history. A page examines at most `SCAN_BUDGET` events, however sparse the filter."""
    found: list[Any] = []
    position = start
    scanned = 0
    while True:
        wanted = min(BATCH, SCAN_BUDGET - scanned)
        query = select(t.event).where(
            t.event.c.project_id == mine.project.id,
            t.event.c.kind == "message",
            t.event.c.conversation_id.is_(None),
        )
        if oldest_first:
            query = query.where(t.event.c.seq > position).order_by(t.event.c.seq)
        else:
            query = query.where(t.event.c.seq < position).order_by(t.event.c.seq.desc())
        batch = conn.execute(query.limit(wanted)).all()
        hidden = events.hidden_redactions(conn, batch, mine.row)
        for row in batch:
            scanned += 1
            if events.readable_by(row, mine.row, mine.principal_id, hidden) and _listed(row, types):
                found.append(row)
                if len(found) > limit:
                    return found[:limit], found[limit - 1].seq
            position = row.seq
        if len(batch) < wanted:
            return found, None
        if scanned >= SCAN_BUDGET:
            return found, position


def _items(conn: Connection, rows: list[Any], mine: Membership) -> list[dict[str, Any]]:
    senders = principal_ids(conn, (r.actor_membership for r in rows))
    # A message from an agent names its instance (§8.8, §6.17); a human's has none.
    instance_of = instances.instances_of(conn, [r.actor_credential_id for r in rows])
    # A deleted account among the mentions is shown as one (§2.9).
    payloads = shape_deleted(conn, [r.payload or {} for r in rows])
    items = []
    for row, payload in zip(rows, payloads, strict=True):
        tomb = _without_reason(row, mine) if row.redacted else None
        items.append(
            {
                "id": f"evt-{row.seq}",
                "seq": row.seq,
                "type": None if row.redacted else payload.get("type"),
                "from": senders.get(row.actor_membership),
                "from_instance": instance_of.get(row.actor_credential_id or ""),
                "to": None if row.redacted else payload.get("to"),
                "task_id": None if row.redacted else payload.get("task_id"),
                "review": None if row.redacted else payload.get("review"),
                "body": None if row.redacted else payload.get("body"),
                "sent_at": ts(row.at),
                "mentions": [] if row.redacted else payload.get("mentions") or [],
                "attachments": [] if row.redacted else payload.get("attachments") or [],
                "redacted": bool(row.redacted),
                "redaction": (
                    {"at": tomb.get("at"), "by": tomb.get("by"), "reason": tomb.get("reason")}
                    if tomb
                    else None
                ),
                # Carried by a bridge for the sender (§2.3): only then.
                **({"via": row.actor_bridge} if row.actor_bridge else {}),
            }
        )
    return items


@router.get("/projects/{owner}/{slug}/messages")
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
        page, resume = _scan(conn, mine, types, start, limit, oldest_first=oldest_first)
        next_cursor = paging.seq_cursor(resume, bound) if resume is not None else None
        return JSONResponse({"items": _items(conn, page, mine), "next_cursor": next_cursor})
