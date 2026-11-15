"""`Idempotency-Key` on state-changing calls (docs/api.md §1.5).

The key is unique per caller (an agent's credential, or a human) and kept
for 24 hours. A repeat with the same body answers with the first call's
status and the resource as it is now, marked `Idempotent-Replayed: true`;
the hub stores a reference to the resource, not the response. A repeat
with a different body, or on another method, route or resource, another
project's included, is `idempotency_mismatch`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, Engine, delete, insert, select
from sqlalchemy.exc import IntegrityError

from maity_hub import clock, events, namespace
from maity_hub import tables as t
from maity_hub.auth.caller import Caller
from maity_hub.db import retrying
from maity_hub.errors import ApiError, invalid, not_found

HEADER = "idempotency-key"
RETENTION = timedelta(hours=24)
# A repeat of these is harmless by itself (§1.5).
EXEMPT_PREFIXES = ("/api/v1/join/", "/api/v1/auth/")
EXEMPT_PATHS = ("/api/v1/me/resume",)

# loader(conn, id, request) -> the resource as GET returns it; the request gives a loader
# what its view needs from the app (settings, the forge reader)
Loader = Callable[[Connection, str, Request], dict[str, Any]]
# may_see(conn, id, caller): whether the caller may still read the resource now, as a GET
# of it would let them. A replay asks it before the loader runs (§1.5).
Check = Callable[[Connection, str, Caller], bool]


@dataclass(frozen=True)
class Replay:
    load: Loader
    may_see: Check


# resource type -> how a replay re-checks the caller and loads the resource
LOADERS: dict[str, Replay] = {}


def register(resource_type: str, load: Loader, may_see: Check) -> None:
    """How a stored key of `resource_type` replays: `may_see` first, then `load`.

    A replay passes the same read a fresh request would: the stored answer is the resource
    as it is now, so a caller who lost access since (left the project, lost the right that
    reads it) gets `not_found`, as their GET does."""
    if resource_type in LOADERS:
        raise RuntimeError(f"replay of {resource_type!r} registered twice")
    LOADERS[resource_type] = Replay(load, may_see)


def plain(load: Callable[[Connection, str], dict[str, Any]]) -> Loader:
    """A loader whose view needs nothing from the app."""
    return lambda conn, resource_id, _request: load(conn, resource_id)


def own(_conn: Connection, _resource_id: str, _caller: Caller) -> bool:
    """The caller's own record (their profile, preferences, lists, reports): the key is the
    caller's, so the id it stored can only name what is theirs."""
    return True


def checked_by_route(_conn: Connection, _resource_id: str, _caller: Caller) -> bool:
    """The route re-checks the caller itself before it replays (`replay_first` after its own
    check), so the stored id needs no further look here."""
    return True


def is_caller(_conn: Connection, human_id: str, caller: Caller) -> bool:
    """A human's own record stored by their id (`/me`, their preferences)."""
    return caller.kind == "human" and caller.human_id == human_id


def in_project(
    project_of: Callable[[Connection, str], str | None],
    may_read: Callable[[Connection, Any, str], bool] | None = None,
) -> Check:
    """A project's resource: the caller's active membership in it with `project:read`, as
    its GET checks, and `may_read(conn, membership, id)` where that GET checks more."""

    def may_see(conn: Connection, resource_id: str, caller: Caller) -> bool:
        from maity_hub.access import membership  # access reads the caller, as this does

        project_id = project_of(conn, resource_id)
        if project_id is None:
            return False
        try:
            mine = membership(conn, caller, namespace.name_of(conn, project_id))
        except ApiError:
            return False
        if not mine.may("project:read"):
            return False
        return may_read is None or may_read(conn, mine, resource_id)

    return may_see


def the_project(_conn: Connection, project_id: str) -> str | None:
    """A resource stored by its project's id (the project, its roles, images, webhook)."""
    return project_id


def column_of(
    table: Any,
    column: str = "project_id",
    *,
    by: str = "id",
    key: Callable[[str], Any] = str,
) -> Callable[[Connection, str], str | None]:
    """The project of the row of `table` whose `by` is the stored id (`key` turns that into
    the column's type): its `column`; None once it is gone."""

    def project_of(conn: Connection, resource_id: str) -> str | None:
        found: str | None = conn.execute(
            select(table.c[column]).where(table.c[by] == key(resource_id))
        ).scalar()
        return found

    return project_of


@dataclass(frozen=True)
class Outcome:
    status: int
    resource_type: str | None
    resource_id: str | None
    body: dict[str, Any]


def key_for(request: Request, caller: Caller) -> str | None:
    """The request's key; required on an agent's or a runner's POST and PATCH outside
    the exemptions."""
    key = request.headers.get(HEADER)
    path = request.url.path
    exempt = path in EXEMPT_PATHS or path.startswith(EXEMPT_PREFIXES)
    required = caller.kind in ("agent", "runner") and request.method in ("POST", "PATCH")
    required = required and not exempt
    if key is None:
        if required:
            raise invalid({"Idempotency-Key": "required"}, "Idempotency-Key is required")
        return None
    if not 16 <= len(key) <= 128:
        raise invalid({"Idempotency-Key": "length"}, "Idempotency-Key must be 16–128 characters")
    return key


def fingerprint(conn: Connection, request: Request) -> str:
    """What a repeat must match: the method, the route, its path parameters and the body.
    The project is named by its id, so its current name and an old one (§6.25) are the
    same call, and the same key in another project is not."""
    route = request.scope.get("route")
    template = getattr(route, "path", None) or request.url.path
    params = dict(request.path_params)
    slug = params.get("slug")
    if isinstance(slug, str):
        project = namespace.resolve(conn, slug)
        if project is not None:
            params["slug"] = project.id
    head = json.dumps([request.method, template, sorted(params.items())])
    body: bytes = request.scope["state"].get("body", b"")
    return hashlib.sha256(head.encode() + b"\n" + body).hexdigest()


def run(
    engine: Engine,
    request: Request,
    caller: Caller,
    action: Callable[[Connection], Outcome],
) -> JSONResponse:
    """Run `action` once per key: in one transaction with the stored reference.

    The action runs inside an `events.transaction`: it must not commit, and
    the events it emits are announced once the transaction committed.
    """
    key = key_for(request, caller)
    who = caller.idempotency_caller

    def attempt() -> JSONResponse | None:
        try:
            with events.transaction(engine) as conn:
                body_hash = fingerprint(conn, request) if key else ""
                replay = _replay(conn, caller, key, body_hash, request) if key else None
                if replay is not None:
                    return replay
                # The action's own errors (a unique conflict included) propagate.
                outcome = action(conn)
                # Only a success is stored: a failed call changed nothing (§1.5).
                if key and 200 <= outcome.status < 300:
                    try:
                        with conn.begin_nested():
                            _store(conn, who, key, body_hash, outcome)
                    except IntegrityError:
                        raise _KeyTaken from None
                return respond(outcome.body, outcome.status)
        except _KeyTaken:
            # A concurrent call with the same key committed first: this one
            # rolled back entirely and replays that one.
            return None

    for _race in range(2):
        response = retrying(attempt)
        if response is not None:
            return response
    raise RuntimeError("idempotent call neither ran nor replayed")


class _KeyTaken(Exception):
    pass


def replay_first(engine: Engine, request: Request, caller: Caller) -> JSONResponse | None:
    """The stored answer when this request repeats a stored one, before a route does
    work a repeat must not do again (an avatar's decode, its rate, §6.10): `None` when
    there is no key or nothing stored, `idempotency_mismatch` for another call."""
    key = key_for(request, caller)
    if key is None:
        return None
    with engine.begin() as conn:
        return _replay(conn, caller, key, fingerprint(conn, request), request)


def _replay(
    conn: Connection, caller: Caller, key: str, body_hash: str, request: Request
) -> JSONResponse | None:
    row = conn.execute(
        select(t.idempotency_key).where(
            t.idempotency_key.c.caller == caller.idempotency_caller,
            t.idempotency_key.c.idem_key == key,
            t.idempotency_key.c.created_at > clock.now() - RETENTION,
        )
    ).first()
    if row is None:
        return None
    if row.body_hash != body_hash:
        raise ApiError(
            409,
            "idempotency_mismatch",
            "this Idempotency-Key was used with a different body, method, route or resource",
        )
    body: dict[str, Any] = {}
    if row.resource_type is not None and row.resource_id is not None:
        replay = LOADERS[row.resource_type]
        # The read a fresh request would pass, before anything is loaded (§1.5).
        if not replay.may_see(conn, row.resource_id, caller):
            raise not_found()
        body = replay.load(conn, row.resource_id, request)
    return respond(body, row.status_code, {"Idempotent-Replayed": "true"})


class _NoContent(JSONResponse):
    """A `204`: no body at all, a replay included."""

    def render(self, content: Any) -> bytes:
        return b""


def respond(
    body: dict[str, Any], status: int, headers: dict[str, str] | None = None
) -> JSONResponse:
    if status == 204:
        return _NoContent(None, status_code=204, headers=headers)
    return JSONResponse(body, status_code=status, headers=headers)


def _store(conn: Connection, who: str, key: str, body_hash: str, outcome: Outcome) -> None:
    now = clock.now()
    conn.execute(delete(t.idempotency_key).where(t.idempotency_key.c.created_at <= now - RETENTION))
    conn.execute(
        insert(t.idempotency_key).values(
            caller=who,
            idem_key=key,
            body_hash=body_hash,
            status_code=outcome.status,
            resource_type=outcome.resource_type,
            resource_id=outcome.resource_id,
            created_at=now,
        )
    )
