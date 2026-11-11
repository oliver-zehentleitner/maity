"""`GET /bootstrap`: the dashboard's first reads in one call (§5.4).

Each part is the single route's answer, built by that route's own body function for the
same caller: `auth.session_body`, `me.me_body`, `events.head_body`, `projects.project_body`
and `members.members_body`. The request authenticates once, so it has the effects of one
authenticated call (§2.4); the refusals a single route gets before it runs (the maintenance
window, an isolated agent, the second factor, a pending account, an agent outside its
project) are decided per part, in the middleware's and `deps._resolve`'s order. The parts
are read concurrently, the head before the project and its members (context/performance.md
b77c193d).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Connection
from starlette.concurrency import run_in_threadpool

from maity_hub import clock, maintenance
from maity_hub.auth import second_factor
from maity_hub.auth.caller import Caller, refuse_isolated
from maity_hub.deps import (  # the single routes' own refusals, per part
    _confine_pending,
    _confine_runner,
    _refuse_other_project,
    authenticated,
    engine_of,
    settings_of,
)
from maity_hub.errors import ApiError, envelope, invalid, unauthenticated
from maity_hub.routes.auth import session_body
from maity_hub.routes.events import head_body
from maity_hub.routes.me import me_body
from maity_hub.routes.members import members_body
from maity_hub.routes.projects import project_body

router = APIRouter()

PATH = "/api/v1/bootstrap"
# The refusals of authentication that answer the whole request: the route's own rule for a
# caller it would refuse (§5.4). Every other one is each caller part's answer, as on its
# single route.
WHOLE = {"csrf_mismatch", "insecure_transport"}

Part = dict[str, Any]


def _part(status: int, body: dict[str, Any]) -> Part:
    return {"status": status, "body": body}


def _refusal(error: ApiError) -> Part:
    """The single route's error, without its headers (§1.3, §5.4)."""
    return _part(error.status, envelope(error.code, error.message, error.details))


@router.get("/bootstrap")
async def bootstrap(request: Request) -> JSONResponse:
    if "maity-for" in request.headers:
        # No project route: a bridge reads the served agent's project through the single
        # routes (§2.3).
        raise invalid({"Maity-For": "route"}, "Maity-For is not taken by this route")
    project = request.query_params.get("project")
    caller, refused = await _caller(request)
    engine = engine_of(request)
    settings = settings_of(request)

    def part(path: str, body: Callable[[Connection, Caller], dict[str, Any]], **kw: Any) -> Part:
        """One caller part, in its own transaction, refused as its single route would be."""
        found = maintenance.window_now(engine) if kw.get("project_route") else None
        if found is not None and found["state"] == "running":
            details = {k: found[k] for k in ("from", "until", "text")}
            return _part(
                503, envelope("maintenance", "the hub is in a maintenance window", details)
            )
        if refused is not None:
            return _refusal(refused)
        if caller is None:
            return _refusal(unauthenticated())
        try:
            with engine.begin() as conn:
                refuse_isolated(conn, caller, "GET", path)  # authentication's own, per path
                second_factor.gate(conn, settings, caller, "GET", path)
                if caller.kind == "agent" and project is not None and kw.get("project_route"):
                    _refuse_other_project(conn, caller, project)
                if caller.kind == "human":
                    _confine_pending(conn, caller, "GET", path)
                return _part(200, body(conn, caller))
        except ApiError as error:
            return _refusal(error)

    def read_maintenance() -> Part:
        return _part(200, {"window": maintenance.window_now(engine)})

    def read_session() -> Part:
        return part("/api/v1/auth/session", lambda conn, c: session_body(conn, settings, c))

    def read_me() -> Part:
        found = part("/api/v1/me", me_body)
        if found["status"] == 200:
            found["body"]["server_time"] = clock.rfc3339(clock.now())
        return found

    async def thread(fn: Callable[[], Part]) -> Part:
        return await run_in_threadpool(fn)

    async def project_chain() -> dict[str, Part]:
        assert project is not None
        base = f"/api/v1/projects/{project}"
        head = await thread(
            lambda: part(
                f"{base}/events", lambda c, w: head_body(c, w, project), project_route=True
            )
        )
        # The head first: whatever changes while the project and its members are read comes
        # as an event past its cursor (§5.4).
        found, members = await asyncio.gather(
            thread(
                lambda: part(
                    base, lambda c, w: project_body(c, request, w, project), project_route=True
                )
            ),
            thread(
                lambda: part(
                    f"{base}/members", lambda c, w: members_body(c, w, project), project_route=True
                )
            ),
        )
        return {"head": head, "project": found, "members": members}

    reads: list[Any] = [thread(read_maintenance), thread(read_session), thread(read_me)]
    if project is not None:
        reads.append(project_chain())
    answered = await asyncio.gather(*reads)
    answer: dict[str, Part] = {
        "maintenance": answered[0],
        "session": answered[1],
        "me": answered[2],
    }
    if project is not None:
        answer.update(answered[3])
    return JSONResponse(answer)


async def _caller(request: Request) -> tuple[Caller | None, ApiError | None]:
    """The caller once for all parts, with one call's effects (§2.4), or the refusal its
    caller parts answer. A request with no credential is no caller and touches nothing."""
    if "authorization" not in request.headers and not request.cookies:
        return None, None

    def confine(conn: Connection, caller: Caller) -> Caller:
        # Decided for the route; the parts' own refusals come per part.
        second_factor.gate(conn, settings_of(request), caller, "GET", PATH)
        if caller.kind == "runner":
            try:
                _confine_runner(PATH)  # neither under /runner/ nor under /projects/ (§15.1)
            except ApiError as error:
                raise _Whole(error) from None
        return caller

    try:
        return await authenticated(request, True, confine), None
    except _Whole as whole:
        raise whole.error from None
    except ApiError as error:
        if error.code in WHOLE:
            raise
        return None, error


class _Whole(Exception):
    """A refusal of the caller that answers the whole request, not its parts."""

    def __init__(self, error: ApiError) -> None:
        super().__init__(error.message)
        self.error = error
