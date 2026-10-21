"""FastAPI dependencies: the engine, the origin, and the authenticated caller."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Engine
from starlette.concurrency import run_in_threadpool

from maity_hub.auth.caller import Caller, RequestFacts, authenticate
from maity_hub.config import Settings
from maity_hub.db import retrying
from maity_hub.errors import forbidden, invalid
from maity_hub.net import Origin


def engine_of(request: Request) -> Engine:
    engine: Engine = request.app.state.engine
    return engine


def settings_of(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


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
    )


async def _resolve(request: Request, renew_leases: bool) -> Caller:
    facts = facts_of(request)
    engine = engine_of(request)

    def run() -> Caller:
        with engine.begin() as conn:
            return authenticate(conn, facts, renew_leases=renew_leases)

    caller = await run_in_threadpool(retrying, run)
    request.state.caller = caller
    return caller


async def current_caller(request: Request) -> Caller:
    return await _resolve(request, renew_leases=True)


WAIT_MAX = 55  # seconds; a larger `wait` is clamped (§1.7)


def wait_of(request: Request) -> int:
    raw = request.query_params.get("wait", "0")
    if not raw.isdigit():
        raise invalid({"wait": "not_a_number"})
    return min(int(raw), WAIT_MAX)


async def events_caller(request: Request) -> Caller:
    """The events read: a long-poll (`wait > 0`) is presence, not work, and renews no
    lease; a plain read (`wait=0`) renews like any call (§2.4)."""
    return await _resolve(request, renew_leases=wait_of(request) == 0)


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


# Annotated forms for route signatures.
AnyCaller = Annotated[Caller, Depends(current_caller)]
HumanCaller = Annotated[Caller, Depends(human_caller)]
AgentCaller = Annotated[Caller, Depends(agent_caller)]
EventsCaller = Annotated[Caller, Depends(events_caller)]
