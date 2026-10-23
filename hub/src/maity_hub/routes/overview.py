"""`GET /projects/{slug}/overview` (docs/api.md §6.11): what the project overview cannot
get cheaply from the reads that exist — the board's column counts, the open requests
the caller may see, and the latest reports. Counts and facts only, read at call time in
one transaction; no title of a request, no member view repeated."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, func, or_, select

from maity_hub import avatars, cards, clock, inbox
from maity_hub import tables as t
from maity_hub.access import Membership, membership
from maity_hub.deps import AnyCaller, engine_of
from maity_hub.errors import invalid
from maity_hub.routes.requests import _filtered

router = APIRouter()

REPORTS_DEFAULT, REPORTS_MAX = 10, 50


def board_counts(
    conn: Connection, project_id: str, closed_after: datetime | None
) -> dict[str, int]:
    """Cards per status, all seven always present; with `closed_after` the closed
    statuses count only cards closed after it, as the board's columns do (§6.4)."""
    c = t.card.c
    query = select(c.status, func.count()).where(c.project_id == project_id)
    if closed_after is not None:
        query = query.where(or_(c.closed_at.is_(None), c.closed_at > closed_after))
    counts = {status: 0 for status in cards.STATUSES}
    for status, n in conn.execute(query.group_by(c.status)):
        counts[status] = int(n)
    return counts


def request_counts(conn: Connection, mine: Membership) -> dict[str, Any]:
    """Over exactly what `GET …/requests?status=open&to=all` lists for this caller."""
    rows = _filtered(conn, mine, status="open", class_=None, asked_by=None, to="all")
    by_priority = {p: 0 for p in reversed(inbox.PRIORITIES)}
    for row in rows:
        by_priority[row.priority] = by_priority.get(row.priority, 0) + 1
    oldest = min((r.created_at for r in rows), default=None)
    return {
        "open": len(rows),
        "to_me": sum(1 for r in rows if inbox.addressed_to(conn, r, mine)),
        "by_priority": by_priority,
        "oldest_open_at": clock.rfc3339(oldest) if oldest is not None else None,
    }


def _reporters(conn: Connection, member_ids: set[str]) -> dict[str, dict[str, Any]]:
    """`reported_by` per member id, a removed member's handle and name included."""
    found: dict[str, dict[str, Any]] = {}
    agents = {i for i in member_ids if i.startswith("agt-")}
    humans = member_ids - agents
    if agents:
        for row in conn.execute(select(t.agent_profile).where(t.agent_profile.c.id.in_(agents))):
            found[row.id] = {"handle": row.handle, "display_name": row.display_name}
    if humans:
        for row in conn.execute(select(t.human).where(t.human.c.id.in_(humans))):
            found[row.id] = {"handle": row.handle, "display_name": row.display_name}
    pictures = avatars.urls(conn, list(found))
    return {
        member_id: {"member_id": member_id, **shown, "avatar_url": pictures[member_id]}
        for member_id, shown in found.items()
    }


def latest_reports(conn: Connection, project_id: str, limit: int) -> list[dict[str, Any]]:
    """The latest report of up to `limit` cards, newest `reported_at` first, from the
    cards' `report` field (§6.6); earlier reports live only in limited events."""
    rows = conn.execute(
        select(
            t.card.c.id,
            t.card.c.title,
            t.card.c.status,
            t.card.c.kind,
            t.card.c.label,
            t.card.c.report,
            t.card.c.updated_at,
        ).where(t.card.c.project_id == project_id, t.card.c.report.isnot(None))
    ).all()
    # `reported_at` has whole seconds: within one, the card changed last came last.
    rows = sorted(
        rows, key=lambda r: (r.report.get("reported_at") or "", r.updated_at, r.id), reverse=True
    )
    rows = rows[:limit]
    people = _reporters(
        conn, {r.report["reported_by"] for r in rows if r.report.get("reported_by")}
    )
    shown = []
    for row in rows:
        report = row.report
        observed = report.get("observed") or None
        found_pr = report.get("pr_status") == "found" and report.get("code") is not False
        pr = report.get("pr") if found_pr else None
        shown.append(
            {
                "task": {
                    "id": row.id,
                    "title": row.title,
                    "status": row.status,
                    "kind": row.kind,
                    "label": row.label,
                },
                "reported_by": people.get(report.get("reported_by")),
                "reported_at": report.get("reported_at"),
                "code": report.get("code") is not False,
                "verification": report.get("verification"),
                "pr": {"number": pr["number"], "url": pr["url"]} if pr else None,
                # The probe's facts, null while nothing is observed; so is mismatch (§6.6).
                "pr_state": observed.get("pr_state") if observed else None,
                "observed_at": observed.get("observed_at") if observed else None,
                "mismatch": report.get("mismatch") if observed else None,
            }
        )
    return shown


@router.get("/projects/{slug}/overview")
def overview(
    slug: str,
    request: Request,
    caller: AnyCaller,
    closed_after: datetime | None = None,
    limit: int = Query(default=REPORTS_DEFAULT, ge=1, le=REPORTS_MAX),
) -> JSONResponse:
    if closed_after is not None and closed_after.tzinfo is None:
        raise invalid({"closed_after": "needs_a_zone"})
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        return JSONResponse(
            {
                "server_time": clock.rfc3339(clock.now()),
                "board": {
                    "counts": board_counts(conn, mine.project.id, closed_after),
                    "closed_after": (
                        clock.rfc3339(closed_after) if closed_after is not None else None
                    ),
                },
                "requests": request_counts(conn, mine),
                "reports": latest_reports(conn, mine.project.id, limit),
            }
        )
