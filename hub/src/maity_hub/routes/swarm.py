"""The swarm statistics (docs/api.md §6.22): `GET /projects/{owner}/{slug}/swarm`, a section of
the project's Overview for members. There is no public swarm page; a public project's page
shows them reduced (§16.9)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, select

from maity_hub import clock, swarm
from maity_hub import tables as t
from maity_hub.access import membership
from maity_hub.deps import AnyCaller, engine_of
from maity_hub.namespace import ProjectRoute
from maity_hub.views import member_views

router = APIRouter(route_class=ProjectRoute)
DAYS = Query(default=30, ge=1, le=90)
HELD = ("done", "cancelled")  # a card in neither, with a holder, is held


def _active(conn: Connection, project_id: str) -> list[Any]:
    return list(
        conn.execute(
            select(t.membership)
            .where(t.membership.c.project_id == project_id, t.membership.c.active.is_(True))
            .order_by(t.membership.c.joined_at, t.membership.c.id)
        )
    )


def _live(conn: Connection, project_id: str, rows: list[Any]) -> list[dict[str, Any]]:
    """Every active member at the moment of the call (§2.4): presence, the instances
    online, the cards its instances hold, the latest call."""
    held: dict[int, list[dict[str, Any]]] = {r.id: [] for r in rows}
    for card in conn.execute(
        select(t.card.c.id, t.card.c.title, t.card.c.claim_holder, t.card.c.claim_since)
        .where(
            t.card.c.project_id == project_id,
            t.card.c.claim_holder.isnot(None),
            t.card.c.status.notin_(HELD),
        )
        .order_by(t.card.c.claim_since, t.card.c.id)
    ):
        if card.claim_holder in held:
            held[card.claim_holder].append(
                {
                    "task_id": card.id,
                    "title": card.title,
                    "since": clock.rfc3339(card.claim_since) if card.claim_since else None,
                }
            )
    found = []
    for row, view in zip(rows, member_views(conn, rows), strict=True):
        instances = view.get("instances")
        online = view["presence"] == "online"
        found.append(
            {
                "member_id": view["id"],
                "kind": view["kind"],
                "handle": view["handle"],
                **({"name": view["name"]} if "name" in view else {}),  # agents: owner/handle
                "display_name": view["display_name"],
                "avatar_url": view["avatar_url"],
                "online": online,
                "instances_online": (
                    sum(1 for i in instances if i.get("presence") == "online")
                    if instances is not None
                    else int(online)
                ),
                "holding": held[row.id],
                "last_seen_at": view["last_seen_at"],
            }
        )
    return found


def _who(rows: list[Any], live: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """The identity of each member row of the window part."""
    return {
        row.id: {
            "member_id": shown["member_id"],
            "handle": shown["handle"],
            **({"name": shown["name"]} if "name" in shown else {}),
        }
        for row, shown in zip(rows, live, strict=True)
    }


@router.get("/projects/{owner}/{slug}/swarm")
def project_swarm(slug: str, request: Request, caller: AnyCaller, days: int = DAYS) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        rows = _active(conn, mine.project.id)
        live = _live(conn, mine.project.id, rows)
        found = swarm.CACHE.get(conn, mine.project.id)
        folded = swarm.fold(found, _who(rows, live), days=days, include=lambda _m: True)
        return JSONResponse(
            {
                "as_of": folded["as_of"],
                "window_days": folded["window_days"],
                "live_at": clock.rfc3339(clock.now()),
                "live": live,
                "members": folded["members"],
                "totals": folded["totals"],
                "coverage": folded["coverage"],
            }
        )
