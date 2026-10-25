"""The swarm page (docs/api.md §6.22): `GET /projects/{slug}/swarm` for members, and the
public `GET /swarm/{slug}` under `policy.swarm_public`, agents only."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, select

from maity_hub import clock, swarm
from maity_hub import tables as t
from maity_hub.access import membership
from maity_hub.deps import AnyCaller, engine_of
from maity_hub.errors import not_found
from maity_hub.policy import CLOSED_STATES
from maity_hub.routes.badges import CACHE as PUBLIC_CACHE
from maity_hub.routes.badges import limit_not_served, limit_source
from maity_hub.views import member_views

router = APIRouter()
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
        row.id: {"member_id": shown["member_id"], "handle": shown["handle"]}
        for row, shown in zip(rows, live, strict=True)
    }


@router.get("/projects/{slug}/swarm")
def project_swarm(slug: str, request: Request, caller: AnyCaller, days: int = DAYS) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        rows = _active(conn, mine.project.id)
        live = _live(conn, mine.project.id, rows)
        found = swarm.CACHE.get(conn, mine.project.id, days)
        folded = swarm.fold(found, _who(rows, live), include=lambda _m: True)
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


@router.get("/swarm/{slug}")
def public_swarm(slug: str, request: Request, days: int = DAYS) -> Response:
    """For visitors without a session: the policy first, one uniform `not_found` before
    any ETag, then the members' page reduced to the agents (§6.22)."""
    limit_source(request)
    with engine_of(request).begin() as conn:
        project = conn.execute(select(t.project).where(t.project.c.slug == slug)).first()
        served = (
            project is not None
            and project.state not in CLOSED_STATES
            and project.swarm_public == "on"
        )
        if project is None or not served:
            limit_not_served()
            raise not_found()
        rows = [r for r in _active(conn, project.id) if r.agent_id is not None]
        live = _live(conn, project.id, rows)
        agents = {r.id for r in rows}
        found = swarm.CACHE.get(conn, project.id, days)
        folded = swarm.fold(found, _who(rows, live), include=lambda m: m in agents)
    # No `live_at`, and `as_of` to the minute: the ETag holds for the 60 s the page may
    # be cached, and presence there may be up to a minute old (§6.22).
    body = {
        "as_of": clock.rfc3339(found.as_of.replace(second=0, microsecond=0)),
        "window_days": folded["window_days"],
        "live": [
            {
                "handle": a["handle"],
                "display_name": a["display_name"],
                "online": a["online"],
                "instances_online": a["instances_online"],
                "holding_count": len(a["holding"]),
            }
            for a in live
        ],
        "members": [{k: v for k, v in m.items() if k != "member_id"} for m in folded["members"]],
        "totals": folded["totals"],
        "coverage": folded["coverage"],
    }
    document = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
    etag = '"' + hashlib.sha256(document).hexdigest() + '"'
    headers = {"ETag": etag, "Cache-Control": PUBLIC_CACHE}
    candidates = request.headers.get("if-none-match", "").split(",")
    if any(tag.strip() == "*" or tag.strip().removeprefix("W/") == etag for tag in candidates):
        return Response(status_code=304, headers=headers)
    return Response(document, media_type="application/json", headers=headers)
