"""`GET /projects/{owner}/{slug}/overview` (docs/api.md §6.11): what the project overview cannot
get cheaply from the reads that exist — the board's column counts, the open requests
the caller may see, and the latest reports. Counts and facts only, read at call time in
one transaction; no title of a request, no member view repeated."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import ColumnElement, Connection, and_, case, func, not_, or_, select

from maity_hub import avatars, cards, clock, inbox, views
from maity_hub import tables as t
from maity_hub.access import Membership, membership
from maity_hub.db import read_transaction
from maity_hub.deps import AnyCaller, engine_of
from maity_hub.errors import invalid
from maity_hub.namespace import ProjectRoute
from maity_hub.routes.requests import listed_to_all, relayed
from maity_hub.scopes import tokens_of

router = APIRouter(route_class=ProjectRoute)

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


def _addressed_sql(mine: Membership) -> ColumnElement[bool]:
    """`inbox.addressed_to` in plain columns, for a request that is not personal and has no
    `held` and no `cover` (the caller's `where` sees to that): its holder, the admins'
    pool for an admin, else `to` in the caller's own right (`inbox._in_own_right`). A change
    there is a change here."""
    r = t.request.c
    tokens = sorted(tokens_of(mine.trust, mine.role, mine.role_base))
    own_right = [
        and_(r.to_kind == "member", r.to_member == mine.id),
        and_(r.to_kind.not_in(("member", "owner")), r.to_role.in_(tokens)),
    ]
    if mine.trust == "owner":
        own_right.append(r.to_kind == "owner")
    not_forwarded = and_(
        r.holder_member.is_(None), or_(r.holder_pool.is_(None), r.holder_pool.is_(False))
    )
    held_now = [r.holder_member == mine.id, and_(not_forwarded, or_(*own_right))]
    if "trust:admin" in tokens:
        held_now.append(and_(r.holder_member.is_(None), r.holder_pool.is_(True)))
    return or_(*held_now)


# What `relayed`, `listed_to_all` and `inbox.addressed_to` read of a request, and the counts.
_DECIDED_BY = (
    "id", "priority", "created_at", "personal", "to_kind", "to_member", "to_role",
    "holder_member", "holder_pool", "held", "cover", "jour_fixe", "proposal", "filed_by",
    "asked_by", "on_behalf_of",
)  # fmt: skip


def request_counts(conn: Connection, mine: Membership) -> dict[str, Any]:
    """Over exactly what `GET …/requests?status=open&to=all` lists for this caller, `to_me`
    over what `to=me` lists (§6.11).

    One grouped statement counts the plain requests: no `held`, no `cover` and, where they
    matter, no `jour_fixe` (for a holder of `requests:answer`: an owner's round opens to no
    scope) and no `proposal` (for a proxy: it never lists a bridge consent). Its `where`
    restates `routes/requests.py` `listed_to_all` and `_addressed_sql` restates
    `inbox.addressed_to`. The others, a few, are read with only the columns the Python rule
    needs and decided by it, unchanged: a JSON list or another table decides them, and
    each database reads JSON in its own syntax."""
    r = t.request.c
    answers = mine.may("requests:answer")
    open_here = [r.project_id == mine.project.id, r.personal.is_(False), r.status == "open"]
    plain = [r.held.is_(None), r.cover.is_(None)]
    if answers:
        plain.append(r.jour_fixe.is_(None))
    if mine.role_base == "proxy":
        plain.append(r.proposal.is_(None))
    addressed = _addressed_sql(mine)
    visible: list[ColumnElement[bool]] = []
    if not answers:  # what it asked (`inbox.is_asker`) and what is addressed to it
        asked = and_(
            or_(r.filed_by.is_(None), r.filed_by != "hub"),
            or_(r.asked_by == mine.id, r.on_behalf_of == mine.id),
        )
        visible.append(or_(asked, addressed))
    counted = conn.execute(
        select(
            r.priority,
            func.count(),
            func.sum(case((addressed, 1), else_=0)),
            func.min(r.created_at),
        )
        .where(*open_here, *plain, *visible)
        .group_by(r.priority)
    ).all()
    leftover = relayed(
        conn.execute(
            select(*(r[name] for name in _DECIDED_BY)).where(*open_here, not_(and_(*plain)))
        ).all(),
        mine,
    )
    by_priority = {p: 0 for p in reversed(inbox.PRIORITIES)}
    total = to_me = 0
    oldest: datetime | None = None
    for priority, n, addressed_n, first in counted:
        by_priority[priority] = by_priority.get(priority, 0) + int(n)
        total += int(n)
        to_me += int(addressed_n or 0)
        oldest = first if oldest is None or first < oldest else oldest
    for row in listed_to_all(conn, mine, leftover):
        by_priority[row.priority] = by_priority.get(row.priority, 0) + 1
        total += 1
        to_me += int(inbox.addressed_to(conn, row, mine))
        oldest = row.created_at if oldest is None or row.created_at < oldest else oldest
    return {
        "open": total,
        "to_me": to_me,
        "by_priority": by_priority,
        "oldest_open_at": clock.rfc3339_or_none(oldest),
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
            if views.deleted(row):  # a deleted account shows no handle (§2.9)
                found[row.id] = views.deleted_person()
            else:
                found[row.id] = {"handle": row.handle, "display_name": row.display_name}
    pictures = avatars.urls(conn, list(found))
    return {
        member_id: {"member_id": member_id, "avatar_url": pictures[member_id], **shown}
        for member_id, shown in found.items()
    }


def _reporter(people: dict[str, dict[str, Any]], report: dict[str, Any]) -> dict[str, Any] | None:
    """Who reported, with the instance that did for an agent (§6.17); null for a human's."""
    person = people.get(report.get("reported_by") or "")
    if not person or person.get("deleted"):  # a deleted account shows nothing more (§2.9)
        return person
    return {**person, "instance": report.get("reported_instance")}


def latest_reports(conn: Connection, project_id: str, limit: int) -> list[dict[str, Any]]:
    """The latest report of up to `limit` cards, newest `reported_at` first, from the
    cards' `report` field (§6.6); earlier reports live only in limited events.

    Keys first: the database sorts and limits the ids alone, then only those cards are read
    in full, put back in that order. `reported_at` has whole seconds: within one, the card
    changed last comes first, then the greater id; a report without one comes last."""
    c = t.card.c
    ids = list(
        conn.execute(
            select(c.id)
            .where(c.project_id == project_id, c.report.isnot(None))
            .order_by(
                func.coalesce(c.report["reported_at"].as_string(), "").desc(),
                c.updated_at.desc(),
                c.id.desc(),
            )
            .limit(limit)
        ).scalars()
    )
    if not ids:
        return []
    found = {
        row.id: row
        for row in conn.execute(
            select(c.id, c.title, c.status, c.kind, c.label, c.report).where(c.id.in_(ids))
        )
    }
    rows = [found[card_id] for card_id in ids if card_id in found]  # gone since the ids
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
                "reported_by": _reporter(people, report),
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


@router.get("/projects/{owner}/{slug}/overview")
def overview(
    slug: str,
    request: Request,
    caller: AnyCaller,
    closed_after: datetime | None = None,
    limit: int = Query(default=REPORTS_DEFAULT, ge=1, le=REPORTS_MAX),
) -> JSONResponse:
    with read_transaction(engine_of(request)) as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        # After the membership: a stranger learns nothing, not even about its query (§1.3).
        if closed_after is not None and closed_after.tzinfo is None:
            raise invalid({"closed_after": "needs_a_zone"})
        return JSONResponse(
            {
                "server_time": clock.rfc3339(clock.now()),
                "board": {
                    "counts": board_counts(conn, mine.project.id, closed_after),
                    "closed_after": clock.rfc3339_or_none(closed_after),
                },
                "requests": request_counts(conn, mine),
                "reports": latest_reports(conn, mine.project.id, limit),
            }
        )
