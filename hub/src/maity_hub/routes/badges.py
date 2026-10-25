"""The opt-in public SVG badge, outside the API prefix (§6.20)."""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from maity_hub import badges
from maity_hub import tables as t
from maity_hub.deps import engine_of, origin_of
from maity_hub.errors import not_found, rate_limited
from maity_hub.policy import CLOSED_STATES
from maity_hub.ratelimit import Limiter

router = APIRouter()
BY_ADDRESS = Limiter(60, 60)
CACHE = "public, max-age=60"


@router.get("/badge/{slug}.svg")
def badge(slug: str, request: Request) -> Response:
    wait = BY_ADDRESS.hit(origin_of(request).address)
    if wait:
        raise rate_limited(wait)
    with engine_of(request).begin() as conn:
        project = conn.execute(select(t.project).where(t.project.c.slug == slug)).first()
        if project is None or project.state in CLOSED_STATES or project.badge == "off":
            raise not_found()
        if project.badge == "members":
            value, color = badges.members(conn, project.id)
        elif project.badge == "agents_online":
            value, color = badges.agents_online(conn, project.id)
        else:  # an unrecognised stored policy never makes a project public
            raise not_found()
    document = badges.render(value, color)
    etag = '"' + hashlib.sha256(document).hexdigest() + '"'
    headers = {"ETag": etag, "Cache-Control": CACHE}
    candidates = request.headers.get("if-none-match", "").split(",")
    if any(tag.strip() == "*" or tag.strip().removeprefix("W/") == etag for tag in candidates):
        return Response(status_code=304, headers=headers)
    return Response(document, media_type="image/svg+xml", headers=headers)
