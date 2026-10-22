"""The runner's own endpoints (docs/api.md §15.8): hello, its event stream, and what
it advertises. Placements and the join pickup arrive with §15.5 and §15.9.

A runner reads only events whose audience names it, across every project it
was attached to, and never `all`; an event is a wake-up, the source of truth
is what it reads after it.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import Field, StringConstraints
from sqlalchemy import Connection, insert, select, update
from starlette.concurrency import run_in_threadpool

from maity_hub import clock, events, idempotency, longpoll
from maity_hub import tables as t
from maity_hub.auth.caller import Caller
from maity_hub.deps import RunnerCaller, engine_of, wait_of
from maity_hub.errors import ApiError
from maity_hub.ids import new_id
from maity_hub.models import Strict
from maity_hub.routes.events import FALLBACK_SECONDS, answer, parse_after, parse_limit
from maity_hub.runners import (
    attached_project_ids,
    event_project_ids,
    listening_key,
    load_runner,
)
from maity_hub.views import event_views

router = APIRouter()

# What a runner advertises is shown to humans as text: printable ASCII, short (§15.3).
Text = Annotated[str, StringConstraints(max_length=200, pattern=r"^[\x20-\x7e]*$")]
Name = Annotated[str, StringConstraints(min_length=1, max_length=200, pattern=r"^[\x20-\x7e]+$")]
Harness = Literal[
    "claude-code", "codex", "opencode", "pi", "hermes", "kimi", "cline", "omp", "stub"
]
Mode = Literal["interactive", "supervised"]
REPORTED_STATES = Literal[
    "pending", "starting", "running", "stopping", "stopped", "exited", "failed"
]


class Isolation(Strict):
    kind: Literal["shared_user", "own_user", "pod"]
    user: Text | None = None
    runner_separate: bool | None = None


class Target(Strict):
    name: Name
    max_agents: int = Field(ge=0, le=10_000)
    running: int = Field(ge=0, le=10_000)
    reachable: bool
    unreachable_since: datetime | None = None
    isolation: Isolation


class HarnessOffer(Strict):
    id: Harness
    version: Text | None = None
    available: bool
    reason: Literal["binary_not_found", "version_failed"] | None = None
    modes: list[Mode] = Field(max_length=2)
    default_mode: Mode
    models: list[Name] = Field(max_length=50)
    targets: list[Name] = Field(max_length=50)
    confinement: Literal["allowlist", "pod", "none"]
    sandbox: Literal["on", "off", "n/a"]


class Capabilities(Strict):
    backend: Name
    max_agents: int = Field(ge=0, le=10_000)
    running: int = Field(ge=0, le=10_000)
    targets: list[Target] = Field(max_length=50)
    harnesses: list[HarnessOffer] = Field(max_length=20)
    projects: list[Name] = Field(max_length=200)
    repositories: list[Name] = Field(max_length=200)
    require_local_approval: bool
    # Set by the hub (§15.8); a value the runner sends is replaced.
    reported_at: datetime | None = None


class Actual(Strict):
    placement_id: Name
    generation: int = Field(ge=0)
    state: REPORTED_STATES
    target: Text | None = None


class Hello(Strict):
    client: str = Field(min_length=1, max_length=200)
    capabilities: Capabilities
    # What runs on the runner now; read once placements exist (§15.5).
    actual: list[Actual] = Field(default_factory=list, max_length=1000)


class Advertise(Strict):
    capabilities: Capabilities


def _stored(capabilities: Capabilities) -> dict[str, Any]:
    data = capabilities.model_dump(mode="json")
    data["reported_at"] = clock.rfc3339(clock.now())
    return data


def _projects(conn: Connection, runner_id: str) -> list[dict[str, Any]]:
    ids = attached_project_ids(conn, runner_id)
    rows = conn.execute(
        select(t.project.c.slug, t.project.c.name, t.project.c.repository_url)
        .where(t.project.c.id.in_(ids))
        .order_by(t.project.c.slug)
    ).all()
    return [{"slug": r.slug, "name": r.name, "repository": r.repository_url} for r in rows]


def _refuse_revoked(conn: Connection, caller: Caller) -> None:
    """The long-poll outlives the call that authenticated it: a revocation in the
    meantime ends it on its next pass (§15.3)."""
    revoked = conn.execute(
        select(t.runner_credential.c.revoked_at, t.runner_credential.c.revoked_reason).where(
            t.runner_credential.c.id == caller.credential_id
        )
    ).one()
    if revoked.revoked_at is not None:
        raise ApiError(
            401,
            "credential_revoked",
            "this credential was revoked",
            {"reason": revoked.revoked_reason},
        )


@router.post("/runner/hello")
def hello(body: Hello, request: Request, caller: RunnerCaller) -> JSONResponse:
    """Opens a runner session and ends the previous one; no `Idempotency-Key`, like
    `resume` (§15.8)."""
    runner_id = caller.runner_id
    assert runner_id is not None
    with events.transaction(engine_of(request)) as conn:
        now = clock.now()
        conn.execute(
            update(t.runner_session)
            .where(
                t.runner_session.c.credential_id == caller.credential_id,
                t.runner_session.c.live.is_(True),
            )
            .values(live=None, ended_at=now)
        )
        session_id = new_id("runner_session")
        conn.execute(
            insert(t.runner_session).values(
                id=session_id,
                credential_id=caller.credential_id,
                client=body.client,
                started_at=now,
                last_seen_at=now,
                live=True,
            )
        )
        conn.execute(
            update(t.runner)
            .where(t.runner.c.id == runner_id)
            .values(
                version=body.client,
                capabilities=_stored(body.capabilities),
                capabilities_at=now,
            )
        )
        name = conn.execute(select(t.runner.c.name).where(t.runner.c.id == runner_id)).scalar()
        packet = {
            "server_time": clock.rfc3339(now),
            "runner": {"id": runner_id, "name": name, "session_id": session_id},
            "projects": _projects(conn, runner_id),
            "placements": [],
            "cursor": events.highest_for_runner(
                conn, event_project_ids(conn, runner_id), runner_id
            ),
        }
    return JSONResponse(packet)


@router.patch("/runner")
def advertise(body: Advertise, request: Request, caller: RunnerCaller) -> JSONResponse:
    runner_id = caller.runner_id
    assert runner_id is not None

    def action(conn: Connection) -> idempotency.Outcome:
        conn.execute(
            update(t.runner)
            .where(t.runner.c.id == runner_id)
            .values(capabilities=_stored(body.capabilities), capabilities_at=clock.now())
        )
        return idempotency.Outcome(200, "runner", runner_id, load_runner(conn, runner_id, None))

    return idempotency.run(engine_of(request), request, caller, action)


@router.get("/runner/events")
async def runner_events(request: Request, caller: RunnerCaller) -> JSONResponse:
    runner_id = caller.runner_id
    assert runner_id is not None
    wait = wait_of(request)
    after_param = parse_after(request.query_params.get("after"))
    limit = parse_limit(request)
    engine = engine_of(request)

    def start() -> int:
        if after_param != "latest":
            return after_param
        with engine.begin() as conn:
            return events.highest_for_runner(conn, event_project_ids(conn, runner_id), runner_id)

    after = await run_in_threadpool(start)
    if after_param == "latest" and wait == 0:
        return answer([], after, superseded=False)

    waiter = longpoll.Waiter(
        key=listening_key(runner_id),  # one open long-poll per runner (§15.8)
        project_id=None,
        session_id=listening_key(runner_id),
        loop=asyncio.get_running_loop(),
    )

    def read(since: int) -> tuple[list[dict[str, Any]], int]:
        with engine.begin() as conn:
            _refuse_revoked(conn, caller)
            project_ids = event_project_ids(conn, runner_id)
            waiter.project_ids = frozenset(project_ids)  # attached since the last pass
            rows, examined = events.read_for_runner(conn, project_ids, runner_id, since, limit)
            cursor = rows[-1].seq if rows else max(examined, since)
            return event_views(conn, rows), cursor

    if wait == 0:
        items, cursor = await run_in_threadpool(read, after)
        return answer(items, cursor, superseded=False)

    longpoll.registry.enter(waiter)
    try:
        deadline = time.monotonic() + wait
        since = after
        while True:
            if waiter.superseded:
                return answer([], after, superseded=True)
            if await request.is_disconnected():
                return answer([], since, superseded=False)
            waiter.event.clear()
            items, cursor = await run_in_threadpool(read, since)
            if waiter.superseded:
                return answer([], after, superseded=True)
            if items:
                return answer(items, cursor, superseded=False)
            since = cursor
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return answer([], cursor, superseded=False)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(waiter.event.wait(), min(remaining, FALLBACK_SECONDS))
    finally:
        longpoll.registry.leave(waiter)
