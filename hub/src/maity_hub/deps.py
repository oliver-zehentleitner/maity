"""FastAPI dependencies: the engine, the origin, and the authenticated caller."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy import Connection, Engine, select
from sqlalchemy.ext.asyncio import AsyncEngine

from maity_hub import events, namespace, request_stats, runner_revoke, write_guard
from maity_hub import tables as t
from maity_hub.auth import second_factor, sessions
from maity_hub.auth.caller import (
    Caller,
    RequestFacts,
    attachment_in,
    authenticate,
    count_agent_read,
    keep_nonces_spent,
    settle_in_project,
    settle_project_less,
)
from maity_hub.auth.permitted import Calls
from maity_hub.config import Settings
from maity_hub.db import retrying_async
from maity_hub.errors import ApiError, forbidden, humans_only, invalid, not_found, unauthenticated
from maity_hub.forge import Forge
from maity_hub.net import Origin

log = logging.getLogger(__name__)


def engine_of(request: Request) -> Engine:
    engine: Engine = request.app.state.engine
    return engine


def async_engine_of(request: Request) -> AsyncEngine:
    async_engine: AsyncEngine = request.app.state.async_engine
    return async_engine


def settings_of(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def reader_of(request: Request) -> Forge:
    """The forge reader with the operator's token; the token lives in the settings only.
    `for_project` on it chooses a project's source (§11.4)."""
    return Forge(settings_of(request).forge_github_token, access=request.app.state.forge_access)


def origin_of(request: Request) -> Origin:
    origin: Origin = request.scope["state"]["origin"]
    return origin


def facts_of(request: Request) -> RequestFacts:
    return RequestFacts(
        method=request.method,
        raw_path=request.scope.get("raw_path") or request.url.path.encode(),
        path=request.scope.get("path", ""),
        raw_query=request.scope["state"].get("raw_query", b""),
        headers={k.lower(): v for k, v in request.headers.items()},
        cookies=dict(request.cookies),
        body=request.scope["state"].get("body", b""),
        origin=origin_of(request),
        allow_plain_http=settings_of(request).allow_plain_http,
        cli_install=settings_of(request).cli_install,
        max_reads_env=settings_of(request).max_reads_per_minute,
        route=request_stats.route_of(request.scope),
    )


async def _resolve(
    request: Request, renew_leases: bool, seen: bool = True, counted: bool = True
) -> Caller:
    """The caller, authenticated on the async engine (tsk-v874y63b4z8p, PR 2): the transaction's
    sync code runs through `run_sync` on the event loop, so no call waits for a thread of the
    pool for it. What it runs there is the database's work and a few hashes
    (`auth.caller`); nothing in it blocks otherwise (the audit in `hub/context/persistence.md`)."""
    facts = facts_of(request)
    slug = request.path_params.get("slug")
    path = request.url.path
    settings = settings_of(request)

    def confine(conn: Connection, caller: Caller) -> Caller:
        # A session that owes the second factor or an enrolment reaches only its
        # few calls (§2.8.2, §2.8.5), decided before any route runs.
        second_factor.gate(conn, settings, caller, request.method, path)
        if caller.kind == "runner":
            _confine_runner(path)
        if caller.kind == "agent":
            if slug is None:
                caller = settle_project_less(conn, caller, facts, renew_leases)
            else:
                # The route's project: its attachment (`not_found` without one, the read
                # counted first, as a probe of another project always was), then its
                # isolation (no count), then the read's count and this membership's presence
                # and leases, in that order.
                attachment = _route_attachment(conn, caller, slug)
                if attachment is None:
                    count_agent_read(conn, caller, facts)
                    raise not_found()
                caller = settle_in_project(conn, caller, attachment, facts, renew_leases)
        if "maity-for" in facts.headers:  # a bridge calling for an agent (§2.3)
            from maity_hub import bridges

            caller = bridges.carry(
                conn, caller, facts.headers["maity-for"], path, slug, renew_leases
            )
        if caller.kind == "human":
            _confine_pending(conn, caller, request.method, path)
        return caller

    return await authenticated(request, renew_leases, confine, seen=seen, counted=counted)


async def authenticated(
    request: Request,
    renew_leases: bool,
    confine: Callable[[Connection, Caller], Caller],
    seen: bool = True,
    counted: bool = True,
) -> Caller:
    """Authenticate the request in one transaction and run `confine` on its caller in the
    same one, so that a refusal there undoes the call's presence and lease effects; then
    bind the caller to the request. `GET /bootstrap` confines differently (§5.4). With `seen`
    false the call writes no `last_seen_at` (`POST /me/presence`, §18.4); with `counted` false
    a cookie session's read is not counted (the forge's setup, §11.4)."""
    facts = facts_of(request)
    engine = async_engine_of(request)

    def run_in(conn: Connection) -> Caller:
        return confine(
            conn,
            authenticate(conn, facts, renew_leases=renew_leases, seen=seen, counted=counted),
        )

    async def run() -> Caller:
        try:
            async with engine.begin() as conn:
                return await conn.run_sync(run_in)
        except runner_revoke.RevocationDue as due:
            # Written in its own transaction: the refusal rolls the call's back (§15.3);
            # an event one, since a revocation announces.
            async with events.async_transaction(engine) as revoking:
                await revoking.run_sync(runner_revoke.revoke_due, due.credential_id, due.by)
            raise ApiError(
                401,
                "credential_revoked",
                "this credential was revoked",
                {"reason": runner_revoke.REASON},
            ) from None

    try:
        caller = await retrying_async(run)
    except second_factor.SessionEnded as ended:
        # The refusal rolled the authentication transaction back; the end has to
        # commit on its own (§2.8.5).
        async with engine.begin() as conn:
            await conn.run_sync(_end_session, ended)
        raise unauthenticated("the sign-in has to start again") from None
    except Exception:
        # A refusal after the nonce was spent in the database rolled the spend back with the
        # rest; it is spent again, committed on its own, before the refusal is answered (§2.2).
        # Nothing is recorded where the process's window keeps the nonce, so nothing runs there.
        if facts.nonces_spent:
            try:
                await retrying_async(lambda: _keep_nonces_spent(engine, facts))
            except Exception as failed:
                # The refusal is still the answer, never a 500; the nonce stays unspent, as it
                # was before the claim again existed (hub/context/auth.md fbc8c3e0). The line
                # names the failure's type only: no nonce, credential or statement in it.
                log.warning(
                    "a refused request's nonce could not be claimed again (%s); it stays unspent",
                    type(failed).__name__,
                )
        raise
    request.state.caller = caller
    if caller.kind == "human" and caller.human_id is not None:
        write_guard.bind(caller.human_id)  # its writes commit only while it exists (§2.9)
    if caller.bridge is not None and caller.project_id is not None:
        # A bridge's writes for an agent commit only while the connection lives (§2.3).
        write_guard.bind_bridge(caller.project_id, caller.bridge.bridge_id)
    return caller


async def _keep_nonces_spent(engine: AsyncEngine, facts: RequestFacts) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(keep_nonces_spent, facts)


def _end_session(conn: Connection, ended: second_factor.SessionEnded) -> None:
    sessions.end_where(conn, t.human_session.c.id_hash == ended.id_hash, ended.by)


def _refuse_other_project(conn: Connection, caller: Caller, slug: str) -> Any:
    """The live attachment of the agent's credential in the project `slug` names (§2.2,
    §6.17): a credential reaches the projects its instance is attached to only, every other
    one is `not_found`. Checked here, before any route runs and before the isolation and the
    call's presence and leases, so that nothing (an idempotent replay included) answers for
    another project, and an isolation is not told to a project's non-member. Never another
    attachment in its place: an error of the lookup refuses the call."""
    attachment = _route_attachment(conn, caller, slug)
    if attachment is None:
        raise not_found()
    return attachment


def _route_attachment(conn: Connection, caller: Caller, slug: str) -> Any | None:
    """The live attachment of the agent's credential in the project `slug` names, or None
    when the project does not exist or the instance is not attached to it."""
    project = namespace.resolve(conn, slug)
    if project is None:
        return None
    return attachment_in(conn, caller, project.id)


# What an account that waits for approval may call (§2.7.5): its own account and
# sessions. `/auth/methods` needs no caller and is everyone's.
PENDING_MAY = Calls(
    ("GET", "/me"),
    ("GET", "/auth/session"),
    ("POST", "/auth/logout"),
    ("GET", "/auth/sessions"),
    ("POST", "/auth/sessions/end-others"),
    ("POST", "/auth/password"),
    # Its own session by id; `:path` keeps the check it has always been, anything below
    # `/auth/sessions/` (no other DELETE route is there).
    ("DELETE", "/auth/sessions/{public_id:path}"),
)


def _confine_pending(conn: Connection, caller: Caller, method: str, path: str) -> None:
    """A pending account holds no scope (§2.3, §2.7.5): everything outside `PENDING_MAY`
    is `account_pending`. Raised inside the transaction, before any route runs, so the
    call's presence side effects are undone with it."""
    status = caller.account_status  # read with the session (a cookie call)
    if status is None:
        status = conn.execute(
            select(t.human.c.account_status).where(t.human.c.id == caller.human_id)
        ).scalar()
    if status != "pending":
        return
    if PENDING_MAY.admits_api(method, path):
        return
    raise ApiError(
        403, "forbidden", "the account waits for approval", {"reason": "account_pending"}
    )


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
    wait = min(int(raw[:6]), WAIT_MAX)  # a larger value is clamped (§8.3)
    if wait:
        request.state.held = True  # its length says nothing about the route (`request_stats`)
    return wait


async def events_caller(request: Request) -> Caller:
    """The events read: a long-poll (`wait > 0`) is presence, not work, and renews no
    lease; a plain read (`wait=0`) renews like any call (§2.4). Authentication comes
    first; the endpoint validates `wait` (an invalid one counts as a read here)."""
    raw = request.query_params.get("wait", "0")
    waiting = raw.isascii() and raw.isdigit() and int(raw) > 0
    return await _resolve(request, renew_leases=not waiting)


async def conversations_caller(request: Request) -> Caller:
    """The conversation list (§9.3): with `renew=false` it is presence, not work, and
    renews no lease, so the unread-chats read `maity wait` makes on a timeout does not
    keep a holder's claims alive (§2.4). Presence is written as by any call. Authentication
    comes first, as for `events_caller`; the endpoint validates `renew` (an invalid one
    counts as an ordinary read here)."""
    return await _resolve(request, renew_leases=request.query_params.get("renew") != "false")


async def presence_caller(request: Request) -> Caller:
    """`POST /me/presence` (§18.4): a human's cookie session only, checked as any call but
    writing no `last_seen_at` and renewing no lease (§2.4). An `Authorization` header (an
    agent, a runner, a bridge) or `Maity-For` is refused before any credential is looked
    up, so no presence of theirs is written either."""
    headers = request.headers
    if "authorization" in headers or "maity-for" in headers:
        raise humans_only("this endpoint is for a human's dashboard session")
    caller = await _resolve(request, renew_leases=False, seen=False)
    if caller.kind != "human" or caller.via != "cookie":
        raise humans_only("this endpoint is for a human's dashboard session")
    return caller


async def forge_setup_caller(request: Request) -> Caller:
    """`GET /forge/github/setup` (§11.4): checked as any call, but writing no presence,
    renewing no lease and counting no read. It is the one call another site may start with
    the cookie (§2.1): a navigation another site forces leaves no trace before its `state`
    refuses it, and the forge's redirect, the only way the route is reached, loses nothing
    by it (hub/context/auth.md e3a7c1d5)."""
    return await _resolve(request, renew_leases=False, seen=False, counted=False)


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
ConversationsCaller = Annotated[Caller, Depends(conversations_caller)]
ForgeSetupCaller = Annotated[Caller, Depends(forge_setup_caller)]
RunnerCaller = Annotated[Caller, Depends(runner_caller)]
