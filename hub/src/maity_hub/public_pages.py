"""Public pages (docs/api.md §16.9): the store of what the hub rendered, and the answer to a
visitor.

A page is a row of `public_page`, the HTML as it is served; taking a page off is deleting its row,
in the transaction that changed the input. The app shell's route asks `answer` first for every
`GET` that is no hub path: a stored page for a visitor without a session (or one who asks for
`?as=public`), else the shell, and the shell for every address while the instance serves no pages
(`MAITY_PUBLIC_PAGES`). Nothing here sets a cookie.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from fastapi import Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import Connection, delete, insert, select

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.auth import caller as auth_caller
from maity_hub.deps import engine_of, origin_of, settings_of
from maity_hub.errors import rate_limited
from maity_hub.ratelimit import Limiter

CSP = "default-src 'none'; style-src 'unsafe-inline'"
CACHE = "public, max-age=60"
# The rate limit of the badge, for the static page only (§16.9, §6.20): its own budget per
# source address, since a page is as cheap to serve as a badge.
BY_ADDRESS = Limiter(60, 60)


def etag_of(body: str) -> str:
    return '"' + hashlib.sha256(body.encode()).hexdigest() + '"'


def put(
    conn: Connection,
    *,
    path: str,
    kind: str,
    target_id: str,
    body: str,
    inputs: str,
    lastmod: datetime,
) -> None:
    """Store the page of `path`, replacing the one there."""
    conn.execute(delete(t.public_page).where(t.public_page.c.path == path))
    conn.execute(
        insert(t.public_page).values(
            path=path,
            kind=kind,
            target_id=target_id,
            body=body,
            etag=etag_of(body),
            inputs=inputs,
            lastmod=lastmod,
            rendered_at=clock.now(),
        )
    )


def get(conn: Connection, path: str) -> Any | None:
    return conn.execute(select(t.public_page).where(t.public_page.c.path == path)).first()


def remove(conn: Connection, kind: str, target_id: str) -> int:
    """Delete the pages of one target (a person, a project and all its views, …)."""
    found = conn.execute(
        delete(t.public_page).where(
            t.public_page.c.kind == kind, t.public_page.c.target_id == target_id
        )
    )
    return int(found.rowcount)


def clear(conn: Connection) -> int:
    """Delete every page: the next render starts from the inputs as they are."""
    return int(conn.execute(delete(t.public_page)).rowcount)


def answer(request: Request) -> Response | None:
    """The stored page of the request's path for a visitor, or None for the shell. A visitor
    is a request without a live session, or one made with `?as=public` (§16.9)."""
    if not settings_of(request).public_pages:
        return None
    with engine_of(request).begin() as conn:
        page = get(conn, request.url.path)
        if page is None:
            return None
        if request.query_params.get("as") != "public" and auth_caller.has_live_session(
            conn, request.cookies
        ):
            return None
    wait = BY_ADDRESS.hit(origin_of(request).address)
    if wait:
        raise rate_limited(wait)
    headers = {
        "Cache-Control": CACHE,
        "ETag": page.etag,
        "Vary": "Cookie",
        "Content-Security-Policy": CSP,
        "X-Content-Type-Options": "nosniff",
    }
    candidates = request.headers.get("if-none-match", "").split(",")
    if any(tag.strip() == "*" or tag.strip().removeprefix("W/") == page.etag for tag in candidates):
        return Response(status_code=304, headers=headers)
    if request.method == "HEAD":
        return Response(media_type="text/html", headers=headers)
    return HTMLResponse(page.body, headers=headers)
