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
from maity_hub.errors import ApiError, invalid

HEADER = "idempotency-key"
RETENTION = timedelta(hours=24)
# A repeat of these is harmless by itself (§1.5).
EXEMPT_PREFIXES = ("/api/v1/join/", "/api/v1/auth/")
EXEMPT_PATHS = ("/api/v1/me/resume",)

# resource type -> loader(conn, id, request) -> the resource as GET returns it; the
# request gives a loader what its view needs from the app (settings, the forge reader)
Loader = Callable[[Connection, str, Request], dict[str, Any]]
LOADERS: dict[str, Loader] = {}


def plain(load: Callable[[Connection, str], dict[str, Any]]) -> Loader:
    """A loader whose view needs nothing from the app."""
    return lambda conn, resource_id, _request: load(conn, resource_id)


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
                replay = _replay(conn, who, key, body_hash, request) if key else None
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
        return _replay(conn, caller.idempotency_caller, key, fingerprint(conn, request), request)


def _replay(
    conn: Connection, who: str, key: str, body_hash: str, request: Request
) -> JSONResponse | None:
    row = conn.execute(
        select(t.idempotency_key).where(
            t.idempotency_key.c.caller == who,
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
        body = LOADERS[row.resource_type](conn, row.resource_id, request)
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
