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
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import Connection, Engine, delete, insert, select

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.auth import caller as auth_caller
from maity_hub.config import Settings
from maity_hub.deps import engine_of, origin_of, settings_of
from maity_hub.errors import rate_limited
from maity_hub.ratelimit import Limiter

log = logging.getLogger(__name__)

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


# --- the engine: rendering again and taking off --------------------------------------------


@dataclass(frozen=True)
class Page:
    """One rendered address: the HTML, a digest of the inputs it was made from, and when
    those inputs last changed (the `lastmod` of the sitemap, not the time of a render)."""

    path: str
    body: str
    inputs: str
    lastmod: datetime


@dataclass(frozen=True)
class Kind:
    """A kind of page: how to render the pages of one target (a person, a project, …), and
    which targets exist. `render` returns no page for a target that is not public."""

    name: str
    render: Callable[[Connection, Settings, str], list[Page]]
    targets: Callable[[Connection], list[str]]
    # The pages of other kinds that show this target (a person on the pages of their
    # projects): `touch` renders them again with it, `(kind, target_id)` each.
    dependents: Callable[[Connection, str], list[tuple[str, str]]] | None = None


KINDS: dict[str, Kind] = {}
_hub: Settings | None = None


def register(kind: Kind) -> None:
    if kind.name in KINDS:
        raise ValueError(f"public page kind {kind.name} is registered twice")
    KINDS[kind.name] = kind


def configure(hub: Settings | None) -> None:
    """The settings `touch` reads: the write paths do not carry them."""
    global _hub
    _hub = hub


def refresh(conn: Connection, hub: Settings, kind: str, target_id: str) -> None:
    """Render the pages of one target again, in the caller's transaction. A page whose inputs
    are the digest stored is left as it is (its ETag and `lastmod` stay); one whose inputs
    changed is replaced; one that is no longer rendered is deleted. A render that fails takes
    the target's pages off: nothing stale is served for the sake of a bug."""
    existing = {
        row.path: row.inputs
        for row in conn.execute(
            select(t.public_page.c.path, t.public_page.c.inputs).where(
                t.public_page.c.kind == kind, t.public_page.c.target_id == target_id
            )
        )
    }
    try:
        with conn.begin_nested():
            rendered = KINDS[kind].render(conn, hub, target_id)
    except Exception:
        log.exception("rendering the public pages of %s %s failed; taken off", kind, target_id)
        remove(conn, kind, target_id)
        return
    for page in rendered:
        if existing.get(page.path) != page.inputs:
            put(
                conn,
                path=page.path,
                kind=kind,
                target_id=target_id,
                body=page.body,
                inputs=page.inputs,
                lastmod=page.lastmod,
            )
    gone = existing.keys() - {page.path for page in rendered}
    if gone:
        conn.execute(delete(t.public_page).where(t.public_page.c.path.in_(gone)))


def touch(conn: Connection, kind: str, target_id: str, *, removal: bool = True) -> None:
    """An input of the target's pages changed, in the transaction that changed it. A change
    that takes anything off a page (`removal`, the default) renders it again at once under
    either mode; under `on_change` so does every other change; under `interval` a new entry or
    a count waits for the next run (§16.9). Nothing happens while the instance serves no
    pages."""
    hub = _hub
    if hub is None or not hub.public_pages:
        return
    if removal or hub.public_pages_render == "on_change":
        refresh(conn, hub, kind, target_id)
        dependents = KINDS[kind].dependents
        for other, other_id in dependents(conn, target_id) if dependents else []:
            refresh(conn, hub, other, other_id)


def render_all(engine: Engine, hub: Settings) -> None:
    """Every page of every kind from the inputs as they are now: the targets that exist are
    rendered again, the pages of targets that no longer exist are deleted."""
    for kind in KINDS.values():
        with engine.begin() as conn:
            ids = kind.targets(conn)
        for target_id in ids:
            with engine.begin() as conn:
                refresh(conn, hub, kind.name, target_id)
        with engine.begin() as conn:
            stored = set(
                conn.execute(
                    select(t.public_page.c.target_id).where(t.public_page.c.kind == kind.name)
                ).scalars()
            )
            for target_id in stored - set(ids):
                remove(conn, kind.name, target_id)


def startup(engine: Engine, hub: Settings) -> None:
    """When the instance serves pages, every page is rendered again before any is served, so
    nothing made under an earlier state is (§16.9)."""
    configure(hub)
    if not hub.public_pages:
        return
    with engine.begin() as conn:
        clear(conn)
    render_all(engine, hub)


class Worker:
    """Renders every page again every `public_pages_interval_hours`: the safety net under
    `on_change`, the way new entries and counts arrive under `interval` (§16.9)."""

    def __init__(self, engine: Engine, hub: Settings, interval: float | None = None) -> None:
        self.engine = engine
        self.hub = hub
        self.interval = hub.public_pages_interval_hours * 3600.0 if interval is None else interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.hub.public_pages:
            return
        self._thread = threading.Thread(target=self._run, name="maity-public-pages", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                render_all(self.engine, self.hub)
            except Exception:
                log.exception("rendering the public pages again failed")
