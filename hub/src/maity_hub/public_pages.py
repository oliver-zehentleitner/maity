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
import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import Connection, Engine, delete, insert, literal, select

from maity_hub import clock, worker_runs
from maity_hub import tables as t
from maity_hub.auth import caller as auth_caller
from maity_hub.config import Settings
from maity_hub.db import xact_lock
from maity_hub.deps import engine_of, origin_of, settings_of
from maity_hub.errors import not_found, rate_limited
from maity_hub.ratelimit import Limiter

log = logging.getLogger(__name__)

# `img-src 'self'` for the pictures of a person's and an agent's page (§6.10, §16.9).
CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'"
CACHE = "public, max-age=60"
READ_CACHE = "public, max-age=60"
# The rate limit of the badge, for the static page only (§16.9, §6.20): its own budget per
# source address, since a page is as cheap to serve as a badge.
BY_ADDRESS = Limiter(60, 60, name="public_pages.BY_ADDRESS")


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
    view: str,
    data: dict[str, Any],
    indexed: bool = True,
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
            view=view,
            data=data,
            indexed=indexed,
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


def _robots(page: Any) -> dict[str, str]:
    """A page kept out of search says so in its header as well as in its HTML (§16.9)."""
    return {} if page.indexed else {"X-Robots-Tag": "noindex"}


def answer(
    request: Request, inside_shell: Callable[[str], bytes | None] | None = None
) -> Response | None:
    """The stored page of the request's path for a visitor, or None for the shell. A visitor
    is a request without a live session, or one made with `?as=public` (§16.9). Without that
    query the page comes inside the app shell (`inside_shell`), so the dashboard takes over at
    the same address; `?as=public` is the bare page and its own security policy."""
    if not settings_of(request).public_pages:
        return None
    path = request.url.path
    with engine_of(request).begin() as conn:
        page = get(conn, path)
        # The same address with a slash at the end, as a hand or a mail client may write it.
        bare = path.rstrip("/") if page is None and path.endswith("/") else ""
        if bare and get(conn, bare) is None:
            return None
        if page is None and not bare:
            return None
        if request.query_params.get("as") != "public" and auth_caller.has_live_session(
            conn, request.cookies
        ):
            return None
    if bare:
        query = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(f"{bare}{query}", status_code=308)
    assert page is not None
    # A visitor gets the small 503 page while a window runs, bare or inside the shell (§16.12):
    # a crawler reads the status, not what the app would draw.
    from maity_hub import maintenance

    window = maintenance.window_now(engine_of(request))
    if window is not None and window["state"] == "running":
        return maintenance.refusal_page(window)  # type: ignore[no-any-return]
    wait = BY_ADDRESS.hit(origin_of(request).address)
    if wait:
        raise rate_limited(wait)
    shelled = None
    if inside_shell is not None and request.query_params.get("as") != "public":
        shelled = inside_shell(page.body)
    if shelled is not None:
        # The shell's files change with a deploy: its digest is part of the tag.
        tag = '"' + hashlib.sha256(shelled).hexdigest() + '"'
        candidates = request.headers.get("if-none-match", "").split(",")
        wrapped = {"Cache-Control": CACHE, "ETag": tag, "Vary": "Cookie", **_robots(page)}
        if any(c.strip() == "*" or c.strip().removeprefix("W/") == tag for c in candidates):
            return Response(status_code=304, headers=wrapped)
        if request.method == "HEAD":
            return Response(media_type="text/html", headers=wrapped)
        return Response(shelled, media_type="text/html", headers=wrapped)
    # The banner of an upcoming window is part of the answer, and so of its tag: a cache
    # holding the page from before (or after) the window gets it again, not a 304.
    tag = maintenance.etag(page.etag, window)
    headers = {
        "Cache-Control": CACHE,
        "ETag": tag,
        "Vary": "Cookie",
        "Content-Security-Policy": CSP,
        "X-Content-Type-Options": "nosniff",
        **_robots(page),
    }
    candidates = request.headers.get("if-none-match", "").split(",")
    if any(c.strip() == "*" or c.strip().removeprefix("W/") == tag for c in candidates):
        return Response(status_code=304, headers=headers)
    if request.method == "HEAD":
        return Response(media_type="text/html", headers=headers)
    return HTMLResponse(maintenance.with_banner(page.body, window), headers=headers)


def read(request: Request, path: str) -> Response:
    """`GET /public/pages/{path}`: the `data` stored with the page, the same for everyone. The
    session and the credentials of the request are never looked at (§16.9)."""
    if not settings_of(request).public_pages:
        raise not_found()
    wait = BY_ADDRESS.hit(origin_of(request).address)
    if wait:
        raise rate_limited(wait)
    with engine_of(request).begin() as conn:
        page = get(conn, f"/{path}")
    if page is None or page.view is None:
        raise not_found()
    payload = json.dumps(
        {"path": page.path, "kind": page.view, "data": page.data},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    tag = etag_of(payload)
    headers = {
        "Cache-Control": READ_CACHE,
        "ETag": tag,
        "X-Content-Type-Options": "nosniff",
    }
    candidates = request.headers.get("if-none-match", "").split(",")
    if any(c.strip() == "*" or c.strip().removeprefix("W/") == tag for c in candidates):
        return Response(status_code=304, headers=headers)
    return Response(payload, media_type="application/json", headers=headers)


# --- the engine: rendering again and taking off --------------------------------------------


@dataclass(frozen=True)
class Page:
    """One rendered address: the HTML, a digest of the inputs it was made from, when those
    inputs last changed (the `lastmod` of the sitemap, not the time of a render), and what a
    visitor's dashboard reads of it: `view`, the `kind` of the answer, and `data` (§16.9)."""

    path: str
    body: str
    inputs: str
    lastmod: datetime
    view: str
    data: dict[str, Any]
    indexed: bool = True  # false: `noindex` and out of the sitemap (§16.9)


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
    # What the worker fetches before its renders, outside any transaction: a render itself
    # never touches the network.
    prepare: Callable[[Engine, Settings], None] | None = None


KINDS: dict[str, Kind] = {}
_hub: Settings | None = None
_RENDERS = "public_pages.after_commit"


def register(kind: Kind) -> None:
    if kind.name in KINDS:
        raise ValueError(f"public page kind {kind.name} is registered twice")
    KINDS[kind.name] = kind


def configure(hub: Settings | None) -> None:
    """The settings `touch` reads: the write paths do not carry them."""
    global _hub
    _hub = hub


def refresh(
    conn: Connection, hub: Settings, kind: str, target_id: str, *, fresh: bool = False
) -> None:
    """Render the pages of one target again, in the caller's transaction. A page whose inputs
    are the digest stored is left as it is (its ETag and `lastmod` stay); one whose inputs
    changed is replaced; one that is no longer rendered is deleted. A render that fails takes
    the target's pages off: nothing stale is served for the sake of a bug. `fresh`: also
    replaced when only the HTML differs, as after a new version rendering the same inputs
    (`startup`). Under a lock per target, so two processes rendering it together (every pod
    at its start, a change and the worker) write it one after the other."""
    xact_lock(conn, f"public_page:{kind}:{target_id}")
    existing = {
        row.path: row
        for row in conn.execute(
            select(
                t.public_page.c.path,
                t.public_page.c.body if fresh else literal(None).label("body"),
                t.public_page.c.inputs,
                t.public_page.c.view,
                t.public_page.c.data,
                t.public_page.c.indexed,
                t.public_page.c.lastmod,
            ).where(t.public_page.c.kind == kind, t.public_page.c.target_id == target_id)
        )
    }
    started = time.monotonic()
    try:
        with conn.begin_nested():
            rendered = KINDS[kind].render(conn, hub, target_id)
    except Exception:
        log.exception("rendering the public pages of %s %s failed; taken off", kind, target_id)
        remove(conn, kind, target_id)
        return
    took = time.monotonic() - started
    if took > hub.public_pages_render_seconds:
        # A render that runs that long is treated as one that failed: the next one would
        # take as long again (§16.9).
        log.warning(
            "rendering the public pages of %s %s took %.1f s, over the limit of %d s; taken off",
            kind,
            target_id,
            took,
            hub.public_pages_render_seconds,
        )
        remove(conn, kind, target_id)
        return
    for page in rendered:
        stored = existing.get(page.path)
        same_inputs = stored is not None and stored.inputs == page.inputs
        if (
            stored is None
            or not same_inputs
            or (stored.view, stored.data, stored.indexed) != (page.view, page.data, page.indexed)
            or (fresh and stored.body != page.body)
        ):
            put(
                conn,
                path=page.path,
                kind=kind,
                target_id=target_id,
                body=page.body,
                inputs=page.inputs,
                # `data` alone changing is nothing a crawler reads: the sitemap's date stays.
                lastmod=stored.lastmod if stored is not None and same_inputs else page.lastmod,
                view=page.view,
                data=page.data,
                indexed=page.indexed,
            )
    gone = existing.keys() - {page.path for page in rendered}
    if gone:
        conn.execute(delete(t.public_page).where(t.public_page.c.path.in_(gone)))


def touch(
    conn: Connection, kind: str, target_id: str, *, removal: bool = True, dependents: bool = True
) -> None:
    """An input of the target's pages changed, in the transaction that changed it. A change
    that takes anything off a page (`removal`, the default) renders it again at once under
    either mode; under `on_change` so does every other change; under `interval` a new entry or
    a count waits for the next run (§16.9). Nothing happens while the instance serves no
    pages. `dependents=False` renders the target's own pages only, for a change that no other
    page shows: a project's dependents are every card page of the project, too many to render
    while the caller holds the project row (hub/context/public-pages.md 721bcdfa)."""
    from maity_hub import events

    hub = _hub
    if hub is None or not hub.public_pages:
        return
    if not (removal or hub.public_pages_render == "on_change"):
        return
    if not events.in_transaction(conn):  # a caller with a plain `engine.begin()`
        refresh(conn, hub, kind, target_id)
        others = KINDS[kind].dependents if dependents else None
        for other, other_id in others(conn, target_id) if others else []:
            refresh(conn, hub, other, other_id)
        return
    others = KINDS[kind].dependents if dependents else None
    targets = [(kind, target_id), *(others(conn, target_id) if others else [])]
    if removal:
        # Off in the writer's transaction, so nothing removed is served for a moment; the
        # render follows the commit. Under the target's lock, so a render of it that is still
        # running writes its page before this delete, not after it; in one order, so two writers
        # cannot each wait for the other.
        for other, other_id in sorted(set(targets)):
            xact_lock(conn, f"public_page:{other}:{other_id}")
            remove(conn, other, other_id)
    _render_after_commit(conn, hub, targets)


def _render_after_commit(conn: Connection, hub: Settings, targets: list[tuple[str, str]]) -> None:
    """Render `targets` once the caller's `events.transaction` has committed, each in a
    transaction of its own, so no render runs while the writer holds its locks: a project's
    row, and on SQLite the database's one write lock. Each target once per transaction."""
    from maity_hub import events

    scratch = events.scratch(conn)
    queued: dict[tuple[str, str], None] | None = scratch.get(_RENDERS)
    if queued is None:
        queued = scratch[_RENDERS] = {}
        engine = conn.engine
        pending = queued

        def render() -> None:
            for other, other_id in pending:
                with engine.begin() as fresh:
                    refresh(fresh, hub, other, other_id)

        events.on_commit(conn, render)
    for target in targets:
        queued.setdefault(target, None)


def render_all(
    engine: Engine,
    hub: Settings,
    stop: worker_runs.Stopping | None = None,
    *,
    fresh: bool = False,
    budget: float | None = None,
) -> list[tuple[str, str]]:
    """Every page of every kind from the inputs as they are now: the targets that exist are
    rendered again, the pages of targets that no longer exist are deleted (`fresh`: see
    `refresh`). With a `budget` in seconds, the targets not reached within it are not
    rendered: their pages are deleted, and they are returned."""
    started = time.monotonic()
    skipped: list[tuple[str, str]] = []
    for kind in KINDS.values():
        with engine.begin() as conn:
            ids = kind.targets(conn)
        for target_id in ids:
            if stop is not None and stop.is_set():
                return skipped
            if budget is not None and time.monotonic() - started > budget:
                skipped.append((kind.name, target_id))
                continue
            with engine.begin() as conn:
                refresh(conn, hub, kind.name, target_id, fresh=fresh)
        with engine.begin() as conn:
            stored = set(
                conn.execute(
                    select(t.public_page.c.target_id).where(t.public_page.c.kind == kind.name)
                ).scalars()
            )
            # The targets as they are now, not the pass's own list: one that turned public
            # meanwhile has its page from `on_change`, which this must not delete.
            for target_id in stored - set(kind.targets(conn)):
                remove(conn, kind.name, target_id)
    if skipped:
        with engine.begin() as conn:
            for kind_name, target_id in skipped:
                remove(conn, kind_name, target_id)
        log.warning(
            "%d public page targets were not rendered within %.0f s; taken off until rendered",
            len(skipped),
            budget,
        )
    return skipped


def startup(engine: Engine, hub: Settings) -> None:
    """When the instance serves pages, every page is rendered again before this process serves
    any, so nothing made under an earlier state is (§16.9). Page by page, never cleared first:
    the other processes and pods serving meanwhile find the old page or the new one, never
    none (hub/context/replicas.md, "Several workers per pod"). No further target is taken up
    after `public_pages_startup_seconds`: the pages of the targets not reached by then are
    deleted, and a worker renders them first. A target taken up before still waits for its
    lock and renders to the end, so this does not bound the start. The worker's first pass
    renders every target without a stored page, so it does not matter which process did the
    start (with `MAITY_WORKERS` above 1, the supervisor's parent, which runs no worker)."""
    configure(hub)
    if not hub.public_pages:
        return
    with engine.begin() as conn:  # a kind this version no longer renders
        conn.execute(delete(t.public_page).where(t.public_page.c.kind.not_in(list(KINDS))))
    render_all(engine, hub, fresh=True, budget=hub.public_pages_startup_seconds)


def _unrendered(conn: Connection, kind: Kind) -> list[str]:
    """The targets of `kind` without a stored page: the ones the start did not reach, in
    whichever process it ran, and the ones that are not public."""
    stored = set(
        conn.execute(
            select(t.public_page.c.target_id).where(t.public_page.c.kind == kind.name)
        ).scalars()
    )
    return [target_id for target_id in kind.targets(conn) if target_id not in stored]


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

    def _prepare(self) -> list[Kind]:
        kinds = [kind for kind in KINDS.values() if kind.prepare is not None]
        for kind in kinds:
            assert kind.prepare is not None
            kind.prepare(self.engine, self.hub)
        return kinds

    def _run(self) -> None:
        # What a kind prepares lives in this process's memory, and the start cleared its pages:
        # every process reads once, outside the pass that only one replica of them claims.
        try:
            # What the start did not reach; a kind that prepares renders every target below.
            for kind in [kind for kind in KINDS.values() if kind.prepare is None]:
                with self.engine.connect() as conn:
                    missing = _unrendered(conn, kind)
                for target_id in missing:
                    if self._stop.is_set():
                        return
                    with self.engine.begin() as conn:
                        refresh(conn, self.hub, kind.name, target_id, fresh=True)
            for kind in self._prepare():
                with self.engine.connect() as conn:
                    ids = kind.targets(conn)
                for target_id in ids:
                    with self.engine.begin() as conn:
                        refresh(conn, self.hub, kind.name, target_id)
        except Exception:
            log.exception("preparing the public pages failed")
        while not self._stop.wait(self.interval):
            try:
                with worker_runs.claim(
                    self.engine, "public-pages", self.interval, self._stop
                ) as held:
                    if held is not None:
                        self._prepare()
                        render_all(self.engine, self.hub, held)
            except Exception:
                log.exception("rendering the public pages again failed")
