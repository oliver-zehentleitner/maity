"""`GET /me/notifications`, `POST /me/notifications/read` (docs/api.md §18.2, §18.3) and a
human's watch on a card (§6.4). For a human's cookie session only: an agent credential
is `forbidden` with `humans_only`, a runner credential `forbidden`."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Annotated, Any

import anyio
from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, delete, insert, select
from starlette.concurrency import run_in_threadpool

from maity_hub import clock, longpoll, namespace
from maity_hub import tables as t
from maity_hub.access import membership
from maity_hub.auth.caller import Caller, session_alive
from maity_hub.deps import AnyCaller, engine_of, reader_of, settings_of, wait_of
from maity_hub.errors import forbidden, humans_only, invalid, not_found, unauthenticated
from maity_hub.namespace import ProjectRoute
from maity_hub.notifications import items, listing, positions
from maity_hub.notifications.items import KINDS, REMOVED_KINDS, Item, Scope
from maity_hub.notifications.positions import Position
from maity_hub.views import task_view

router = APIRouter(route_class=ProjectRoute)

LIMIT_DEFAULT, LIMIT_MAX = 20, 50
IDS_MAX = 200
POLL = 0.5  # seconds between looks while a long-poll holds
# Full answers (and marks) at once per hub process. Each derives every item of 30 days
# and holds a pooled connection while it does; more of them would take the pool from
# every other call. A held long-poll looks at `listing.stamp` between them instead.
AT_ONCE = 4

# One notifications long-poll per cookie session; a newer one supersedes it (§18.2).
_holding: dict[str, object] = {}


def _limit(request: Request) -> anyio.Semaphore:
    """The app's semaphore for full answers, made in its event loop at first use."""
    found: anyio.Semaphore | None = getattr(request.app.state, "notifications_at_once", None)
    if found is None:
        found = anyio.Semaphore(AT_ONCE)
        request.app.state.notifications_at_once = found
    return found


async def _limited[T](request: Request, work: Callable[[], T]) -> T:
    async with _limit(request):
        return await run_in_threadpool(work)


def _human(caller: Caller) -> str:
    if caller.kind == "agent":
        raise humans_only("notifications are for humans")
    if caller.kind != "human" or caller.human_session is None:
        raise forbidden(message="notifications are for a human's dashboard session")
    return caller.human_session


@contextmanager
def _snapshot(request: Request) -> Iterator[Connection]:
    """One transaction at REPEATABLE READ (a SQLite transaction is serializable), so
    items, counts and positions describe one moment (§18.2)."""
    engine = engine_of(request)
    options = {} if engine.dialect.name == "sqlite" else {"isolation_level": "REPEATABLE READ"}
    with engine.connect().execution_options(**options) as conn, conn.begin():
        yield conn


def _require_live(conn: Connection, session_hash: str) -> None:
    row = conn.execute(
        select(t.human_session).where(t.human_session.c.id_hash == session_hash)
    ).first()
    if row is None or row.ended_at is not None or not session_alive(row, clock.now()):
        raise unauthenticated("the session has ended or expired")


def _kinds(values: set[str] | None) -> set[str] | None:
    """§18.2: a kind removed on 2026-10-26 is `removed_kind`, any other unknown one
    `unknown`."""
    if values is None:
        return None
    if values & set(REMOVED_KINDS):
        raise invalid({"kind": "removed_kind"})
    if not values <= set(KINDS):
        raise invalid({"kind": "unknown"})
    return values


def _filters(raw: str | None, allowed: tuple[str, ...] | None, name: str) -> set[str] | None:
    if raw is None:
        return None
    values = {v for v in raw.split(",") if v}
    if not values or len(values) > 50 or (allowed and not values <= set(allowed)):
        raise invalid({name: "invalid"})
    return values


def _open(conn: Connection, request: Request, human_id: str, token: str, name: str) -> Position:
    found = positions.read(conn, settings_of(request).secret_key, human_id, token)
    if found is None:
        raise invalid({name: "position"})  # never which reason, never read as the head
    return found


@router.get("/me/notifications")
async def list_notifications(
    request: Request,
    caller: AnyCaller,
    limit: int = Query(default=LIMIT_DEFAULT, ge=0, le=LIMIT_MAX),
    cursor: str | None = Query(default=None, max_length=512),
    unread: bool = False,
    kind: str | None = Query(default=None, max_length=512),
    project: str | None = Query(default=None, max_length=4096),
    after: str | None = Query(default=None, max_length=positions.MAX_LENGTH),
) -> JSONResponse:
    session = _human(caller)
    wait = wait_of(request)
    if wait and after is None:
        raise invalid({"wait": "needs_after"})
    kinds = _kinds(_filters(kind, None, "kind"))
    slugs = _filters(project, None, "project")
    older = None
    if cursor is not None:
        older = listing.older_than(cursor)
        if older is None:
            raise invalid({"cursor": "invalid"})
    human_id = caller.principal_id
    prepared = [False]

    def answer() -> tuple[dict[str, Any], tuple[Any, ...]]:
        # Every database read runs here, in the worker, never on the event loop: the key's
        # first use in a transaction of its own, before the snapshot.
        if not prepared[0]:
            positions.prepare(engine_of(request), settings_of(request).secret_key)
            prepared[0] = True
        with _snapshot(request) as conn:
            # Every snapshot, a held one included, checks the session again: one ended
            # while the request waited receives nothing more (§18.2).
            _require_live(conn, session)
            found = _answer(conn, request, human_id, limit, older, unread, kinds, slugs, after)
            return found, listing.stamp(conn, human_id)

    def unchanged(seen: tuple[Any, ...]) -> bool:
        """Whether nothing an answer reads moved since `seen`: a few aggregates, not
        the derivation of every item."""
        with engine_of(request).begin() as conn:
            _require_live(conn, session)
            return listing.stamp(conn, human_id) == seen

    def still_live() -> None:
        with engine_of(request).begin() as conn:
            _require_live(conn, session)

    first, seen = await _limited(request, answer)
    if not wait or first["items"]:
        return JSONResponse(first)
    token = object()
    _holding[session] = token
    deadline = time.monotonic() + wait
    try:
        # A stopping hub answers with what it has; the dashboard simply waits again.
        while time.monotonic() < deadline and not longpoll.stopping.is_set():
            await asyncio.sleep(POLL)
            if _holding.get(session) is not token:
                await run_in_threadpool(still_live)
                return JSONResponse({**first, "superseded": True})
            if await run_in_threadpool(unchanged, seen):
                continue
            again, seen = await _limited(request, answer)
            if again["items"]:
                return JSONResponse(again)
        last, _ = await _limited(request, answer)
        return JSONResponse(last)
    finally:
        if _holding.get(session) is token:
            del _holding[session]


def _answer(
    conn: Connection,
    request: Request,
    human_id: str,
    limit: int,
    older: Any,
    unread: bool,
    kinds: set[str] | None,
    slugs: set[str] | None,
    after: str | None,
) -> dict[str, Any]:
    hub = settings_of(request)
    since = _open(conn, request, human_id, after, "after") if after is not None else None
    where = items.scope(conn, human_id, hub.public_url)
    found = items.derive(conn, where)
    answer: dict[str, Any] = listing.counts(conn, where, found)
    project_ids = _project_ids(conn, slugs)
    chosen = listing.select_items(found, kinds=kinds, projects=project_ids, unread=unread)
    head = listing.head(conn, where)
    next_cursor = None
    if since is not None:
        past = sorted(
            (i for i in chosen if not listing.behind(i, since, where)), key=lambda i: i.order
        )
        page = past[:limit]
        if limit and len(past) > limit:
            next_position = listing.advanced(since, page, where)
        elif limit:
            next_position = listing.at_least(head, since)
        else:  # lists nothing and moves nothing, with the membership rules applied
            next_position = listing.advanced(since, [], where)
    else:
        newest = [i for i in chosen if older is None or i.order < older]
        page = newest[:limit]
        if limit and len(newest) > limit:
            next_cursor = listing.cursor_of(page[-1])
        next_position = head
    answer["items"] = [items.view(conn, where, item) for item in page]
    answer["next_cursor"] = next_cursor
    answer["next_after"] = positions.issue(conn, hub.secret_key, human_id, next_position)
    answer["server_time"] = clock.rfc3339(clock.now())
    return answer


def _project_ids(conn: Connection, slugs: set[str] | None) -> set[str] | None:
    """The projects a `projects` filter names by full name (§6.25); an unknown one none."""
    if slugs is None:
        return None
    found = (namespace.resolve(conn, name) for name in slugs)
    return {project.id for project in found if project is not None}


@router.post("/me/notifications/read")
async def read_notifications(
    request: Request, caller: AnyCaller, body: Annotated[dict[str, Any], Body()]
) -> JSONResponse:
    session_hash = _human(caller)
    human_id = caller.principal_id
    given = {"ids", "up_to"} & set(body)
    extra = set(body) - {"ids", "up_to", "kind", "project"}
    if len(given) != 1 or extra or ("ids" in body and ({"kind", "project"} & set(body))):
        raise invalid({name: "extra_forbidden" for name in extra} or {"body": "ids_or_up_to"})

    def mark() -> dict[str, Any]:
        """Choose in a snapshot, write the marks at READ COMMITTED, count in a fresh
        snapshot: a mark racing another of the same items waits for it and skips what
        it wrote, where a snapshot's insert would fail on the key (§18.3). All of it in
        the worker; the key's first use in a transaction of its own, before them."""
        positions.prepare(engine_of(request), settings_of(request).secret_key)
        with _snapshot(request) as conn:
            session = conn.execute(
                select(t.human_session).where(t.human_session.c.id_hash == session_hash)
            ).one()
            where = items.scope(conn, human_id, settings_of(request).public_url)
            found = items.derive(conn, where)
            chosen = _chosen(conn, request, human_id, where, found, body)
        with engine_of(request).begin() as conn:
            listing.mark(conn, where, found, chosen, session)
        with _snapshot(request) as conn:
            where = items.scope(conn, human_id, settings_of(request).public_url)
            return listing.counts(conn, where, items.derive(conn, where))

    return JSONResponse(await _limited(request, mark))


def _chosen(
    conn: Connection,
    request: Request,
    human_id: str,
    where: Scope,
    found: list[Item],
    body: dict[str, Any],
) -> list[Item]:
    if "ids" in body:
        ids = body["ids"]
        if not isinstance(ids, list) or not 0 < len(ids) <= IDS_MAX:
            raise invalid({"ids": "invalid"})
        wanted = {i for i in ids if isinstance(i, str)}
        # An id without an item is ignored: it may have dropped out (§18.3).
        return [item for item in found if item.id in wanted]
    up_to = body["up_to"]
    if not isinstance(up_to, str):
        raise invalid({"up_to": "position"})
    position = _open(conn, request, human_id, up_to, "up_to")
    kinds = {body["kind"]} if body.get("kind") is not None else None
    kinds = _kinds(kinds)
    project_ids = _project_ids(conn, {body["project"]}) if body.get("project") else None
    chosen = listing.select_items(found, kinds=kinds, projects=project_ids, unread=True)
    # "Mark all read" never confirms a sign-in or an address change (§18.3).
    return [
        item for item in chosen if item.kind != "security" and listing.behind(item, position, where)
    ]


# --- watching a card (§6.4) -----------------------------------------------------------


@router.put("/projects/{owner}/{slug}/tasks/{task_id}/watch")
def watch(slug: str, task_id: str, request: Request, caller: AnyCaller) -> JSONResponse:
    return _watch(request, caller, slug, task_id, on=True)


@router.delete("/projects/{owner}/{slug}/tasks/{task_id}/watch")
def unwatch(slug: str, task_id: str, request: Request, caller: AnyCaller) -> JSONResponse:
    return _watch(request, caller, slug, task_id, on=False)


def _watch(request: Request, caller: Caller, slug: str, task_id: str, *, on: bool) -> JSONResponse:
    """Idempotent; no event. A watch is the human's own mark on the card, shown as
    `watching`, and notifies nothing since cards make no notification (§6.4, §18.1)."""
    if caller.kind == "agent":
        raise humans_only("watching is for the notifications of humans")
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        card = conn.execute(
            select(t.card).where(t.card.c.id == task_id, t.card.c.project_id == mine.project.id)
        ).first()
        if card is None:
            raise not_found()
        conn.execute(
            delete(t.card_watch).where(
                t.card_watch.c.card_id == card.id, t.card_watch.c.membership_id == mine.id
            )
        )
        if on:
            conn.execute(
                insert(t.card_watch).values(
                    card_id=card.id, membership_id=mine.id, created_at=clock.now()
                )
            )
        view = task_view(conn, card, reader_of(request), mine)
        return JSONResponse(view)
