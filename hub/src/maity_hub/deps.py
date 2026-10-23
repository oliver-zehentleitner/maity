"""FastAPI dependencies: the engine, the origin, and the authenticated caller."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Connection, Engine, select
from starlette.concurrency import run_in_threadpool

from maity_hub import runner_revoke
from maity_hub import tables as t
from maity_hub.auth.caller import Caller, RequestFacts, authenticate
from maity_hub.config import Settings
from maity_hub.db import retrying
from maity_hub.errors import ApiError, forbidden, invalid, not_found
from maity_hub.forge import Forge
from maity_hub.net import Origin


def engine_of(request: Request) -> Engine:
    engine: Engine = request.app.state.engine
    return engine


def settings_of(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def reader_of(request: Request) -> Forge:
    """The forge reader with the operator's token; the token lives in the settings only."""
    return Forge(settings_of(request).forge_github_token)


def origin_of(request: Request) -> Origin:
    origin: Origin = request.scope["state"]["origin"]
    return origin


def facts_of(request: Request) -> RequestFacts:
    return RequestFacts(
        method=request.method,
        raw_path=request.scope.get("raw_path") or request.url.path.encode(),
        raw_query=request.scope["state"].get("raw_query", b""),
        headers={k.lower(): v for k, v in request.headers.items()},
        cookies=dict(request.cookies),
        body=request.scope["state"].get("body", b""),
        origin=origin_of(request),
        allow_plain_http=settings_of(request).allow_plain_http,
        cli_install=settings_of(request).cli_install,
    )


async def _resolve(request: Request, renew_leases: bool) -> Caller:
    facts = facts_of(request)
    engine = engine_of(request)

    slug = request.path_params.get("slug")
    path = request.url.path

    def run() -> Caller:
        try:
            with engine.begin() as conn:
                caller = authenticate(conn, facts, renew_leases=renew_leases)
                if caller.kind == "runner":
                    _confine_runner(path)
                if caller.kind == "agent" and slug is not None:
                    _refuse_other_project(conn, caller, slug)
                return caller
        except runner_revoke.RevocationDue as due:
            # Written in its own transaction: the refusal rolls the call's back (§15.3).
            with engine.begin() as conn:
                runner_revoke.revoke_due(conn, due.credential_id, due.by)
            raise ApiError(
                401,
                "credential_revoked",
                "this credential was revoked",
                {"reason": runner_revoke.REASON},
            ) from None

    caller = await run_in_threadpool(retrying, run)
    request.state.caller = caller
    return caller


def _refuse_other_project(conn: Connection, caller: Caller, slug: str) -> None:
    """An agent credential reaches its own project only (§2.2). Checked here, before
    any route runs, so that nothing (an idempotent replay included) answers for
    another project; raising inside the transaction also undoes the call's
    presence and lease side effects."""
    project_id = conn.execute(select(t.project.c.id).where(t.project.c.slug == slug)).scalar()
    if project_id != caller.project_id:
        raise not_found()


RUNNER_PATH = "/api/v1/runner"


def _confine_runner(path: str) -> None:
    """A runner calls `/runner/*` and nothing else (§15.1). Decided here, once, so that
    no route ever sees a runner it was not written for: a project route answers as
    for a project the runner is not a member of, every other route `forbidden`."""
    if path == RUNNER_PATH or path.startswith(RUNNER_PATH + "/"):
        return
    if path.startswith("/api/v1/projects/"):
        raise not_found()
    raise forbidden(message="a runner credential calls /runner/* only")


async def current_caller(request: Request) -> Caller:
    return await _resolve(request, renew_leases=True)


WAIT_MAX = 55  # seconds; a larger `wait` is clamped (§1.7)


def wait_of(request: Request) -> int:
    raw = request.query_params.get("wait", "0")
    if not raw.isascii() or not raw.isdigit():
        raise invalid({"wait": "not_a_number"})
    return min(int(raw[:6]), WAIT_MAX)  # a larger value is clamped (§8.3)


async def events_caller(request: Request) -> Caller:
    """The events read: a long-poll (`wait > 0`) is presence, not work, and renews no
    lease; a plain read (`wait=0`) renews like any call (§2.4). Authentication comes
    first; the endpoint validates `wait` (an invalid one counts as a read here)."""
    raw = request.query_params.get("wait", "0")
    waiting = raw.isascii() and raw.isdigit() and int(raw) > 0
    return await _resolve(request, renew_leases=not waiting)


async def human_caller(request: Request) -> Caller:
    caller = await current_caller(request)
    if caller.kind != "human":
        raise forbidden(message="this endpoint is for humans")
    return caller


async def agent_caller(request: Request) -> Caller:
    caller = await current_caller(request)
    if caller.kind != "agent":
        raise forbidden(message="this endpoint is for agent credentials")
    return caller


async def runner_caller(request: Request) -> Caller:
    """`/runner/*` is the runner's alone (§15.1); the long-poll renews nothing either way."""
    caller = await current_caller(request)
    if caller.kind != "runner":
        raise forbidden(message="this endpoint is for runner credentials")
    return caller


# Annotated forms for route signatures.
AnyCaller = Annotated[Caller, Depends(current_caller)]
HumanCaller = Annotated[Caller, Depends(human_caller)]
AgentCaller = Annotated[Caller, Depends(agent_caller)]
EventsCaller = Annotated[Caller, Depends(events_caller)]
RunnerCaller = Annotated[Caller, Depends(runner_caller)]
