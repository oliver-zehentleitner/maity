"""The frame of the mail link pages (docs/api.md §16.7.5): the sign-in link's page (§2.6.3) and
the pages of §18.6 stand in the landing page's header and footer around the door of
`public-pages.css`, as the dashboard draws `/login`, and answer with one policy.

The policy is `render.DOOR_CSP` on every one of them: the hub's own stylesheets, fonts and
images, the fallback style by its hash, no script, `form-action 'self'`, never framed. The
token is in the address, so no `Referer` carries it on (§1.1, §16.13).
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import HTMLResponse
from sqlalchemy import Connection

from maity_hub import landing, landing_stats, legal, render

HEADERS = {"Content-Security-Policy": render.DOOR_CSP, "Referrer-Policy": "no-referrer"}


def page(
    conn: Connection,
    request: Request,
    language: str,
    title: str,
    content: str,
    status: int = 200,
) -> HTMLResponse:
    """A link page in the frame: `content` (HTML of escaped text and elements) goes into the
    door's form column, the frame's footer ends it, with no product line."""
    frame = landing.stored(conn)
    body = render.door_document(
        lang=language,
        title=title,
        content=content,
        setting=frame,
        legal=legal.public(legal.stored(conn)),
        stats=landing_stats.for_frame(conn, frame),
        accept_language=request.headers.get("accept-language"),
    )
    return HTMLResponse(body, status_code=status, headers=HEADERS)
