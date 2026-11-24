"""The opt-in public SVG badge, outside the API prefix (§6.20)."""

from __future__ import annotations

import hashlib
from typing import Any

from fastapi import APIRouter, Request, Response
from sqlalchemy import Connection

from maity_hub import badges, namespace, public_projects
from maity_hub.deps import engine_of, origin_of
from maity_hub.errors import not_found, rate_limited
from maity_hub.policy import CLOSED_STATES
from maity_hub.ratelimit import Limiter

router = APIRouter()
# One budget per source address for the badge, and one shared budget for every slug not
# served, so that varying the slug multiplies nothing (§6.20).
BY_ADDRESS = Limiter(60, 60, name="routes.badges.BY_ADDRESS")
NOT_SERVED = Limiter(60, 60, name="routes.badges.NOT_SERVED")
CACHE = "public, max-age=60"


def limit_source(request: Request) -> None:
    """The caller's budget, taken before anything is read."""
    wait = BY_ADDRESS.hit(origin_of(request).limit_key)
    if wait:
        raise rate_limited(wait)


def limit_not_served() -> None:
    """The shared budget of the slugs not served: an unknown, private or closed project
    alike, so that none is told from the others."""
    wait = NOT_SERVED.hit("*")
    if wait:
        raise rate_limited(wait)


@router.get("/badge/{owner}/{slug}.svg")
def badge(owner: str, slug: str, request: Request) -> Response:
    limit_source(request)
    with engine_of(request).begin() as conn:
        project = namespace.resolve(conn, f"{owner}/{slug}")
        if project is None or not _served(conn, project):
            limit_not_served()
            raise not_found()
        animated = False
        if project.badge == "members":
            value, color = badges.members(conn, project.id)
        elif project.badge == "agents_online":
            value, color, animated = badges.agents_online(conn, project.id)
        else:  # an unrecognised stored policy never makes a project public
            raise not_found()
    document = badges.render(value, color, animated=animated)
    etag = '"' + hashlib.sha256(document).hexdigest() + '"'
    headers = {"ETag": etag, "Cache-Control": CACHE}
    candidates = request.headers.get("if-none-match", "").split(",")
    if any(tag.strip() == "*" or tag.strip().removeprefix("W/") == etag for tag in candidates):
        return Response(status_code=304, headers=headers)
    return Response(document, media_type="image/svg+xml", headers=headers)


def _served(conn: Connection, project: Any) -> bool:
    """The badge's own switch on an open project, and the standing a public page needs
    beside its own columns (`public_projects.standing_of`): no hold on the project, its owner
    neither suspended, pending nor deleted, an organisation neither held nor deleted (§6.20).
    It needs no public page of the project."""
    if project.state in CLOSED_STATES or project.badge not in ("members", "agents_online"):
        return False
    return project.id in public_projects.standing_of(conn, [project])
