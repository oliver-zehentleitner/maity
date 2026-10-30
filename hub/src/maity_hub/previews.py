"""The drafts of the landing page and the legal pages (docs/api.md §16.7, §16.7.1).

A draft is seen before it is saved in two steps: the dashboard posts it (with its CSRF token)
and opens the address that comes back in a new tab, where a top-level `GET` with the session
cookie answers the page as the hub would serve it. The draft lives in the database, for ten
minutes, bound to the admin's session and never to the setting; a session keeps at most twenty
at a time, the oldest goes. Another session, an expired id and an unknown one are all
`not_found`.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, delete, insert, select

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.errors import not_found

LIFETIME = timedelta(minutes=10)
KEPT = 20


def create(
    conn: Connection, session: str, kind: str, payload: dict[str, Any], page: str | None = None
) -> tuple[str, datetime]:
    """Store a draft; returns its id and when it expires."""
    now = clock.now()
    conn.execute(delete(t.preview_draft).where(t.preview_draft.c.expires_at <= now))
    draft_id = secrets.token_urlsafe(18)  # 24 characters
    expires = now + LIFETIME
    conn.execute(
        insert(t.preview_draft).values(
            id=draft_id,
            session=session,
            kind=kind,
            page=page,
            payload=payload,
            created_at=now,
            expires_at=expires,
        )
    )
    older = conn.execute(
        select(t.preview_draft.c.id)
        .where(t.preview_draft.c.session == session)
        .order_by(t.preview_draft.c.created_at.desc(), t.preview_draft.c.id.desc())
        .offset(KEPT)
    ).scalars()
    gone = list(older)
    if gone:
        conn.execute(delete(t.preview_draft).where(t.preview_draft.c.id.in_(gone)))
    return draft_id, expires


def read(conn: Connection, draft_id: str, session: str, kind: str) -> Any:
    """The draft row for this session, or `not_found`."""
    row = conn.execute(select(t.preview_draft).where(t.preview_draft.c.id == draft_id)).first()
    if row is None or row.session != session or row.kind != kind or row.expires_at <= clock.now():
        raise not_found()
    return row
