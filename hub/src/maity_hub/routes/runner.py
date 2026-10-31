"""The runner's own endpoints (docs/api.md §15.8): hello, its event stream, what it
advertises, its placements and its reports. The join pickup arrives with §15.9.

A runner reads only events whose audience names it, across every project it
was attached to, and never `all`; an event is a wake-up, the source of truth
is what it reads after it.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, Field, StringConstraints, model_validator
from sqlalchemy import Connection, insert, select, update
from starlette.concurrency import run_in_threadpool

from maity_hub import (
    allowed_projects,
    availability,
    clock,
    events,
    handles,
    idempotency,
    instances,
    longpoll,
    namespace,
)
from maity_hub import placements as pl
from maity_hub import tables as t
from maity_hub.auth.caller import Caller
from maity_hub.codes import digest, new_code, new_token, normalise_code
from maity_hub.deps import RunnerCaller, engine_of, settings_of, wait_of
from maity_hub.errors import ApiError, invalid, not_found
from maity_hub.ids import new_id
from maity_hub.models import Strict
from maity_hub.routes.events import FALLBACK_SECONDS, answer, parse_after, parse_limit
from maity_hub.routes.joins import join_link
from maity_hub.runners import (
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
    "pending", "starting", "running", "stopping", "stopped", "exited", "failed", "rate_limited"
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
    unreachable_since: AwareDatetime | None = None
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

    @model_validator(mode="after")
    def _reason_with_unavailable(self) -> HarnessOffer:
        """`available: false` comes with its reason, and only then (§15.3)."""
        if (self.reason is None) != self.available:
            raise ValueError("reason goes with available: false, and only with it")
        return self


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

    @model_validator(mode="after")
    def _one_offer_per_harness(self) -> Capabilities:
        ids = [h.id for h in self.harnesses]
        if len(ids) != len(set(ids)):
            raise ValueError("each harness is offered once")
        return self


class Actual(Strict):
    placement_id: Name
    generation: int = Field(ge=0)
    state: REPORTED_STATES
    target: Text | None = None


class Hello(Strict):
    client: Name  # shown to humans as the runner's version
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
    """The projects a runner reads: attached, or with an active placement of it (§15.8)."""
    ids = pl.reading_projects(conn, runner_id)
    rows = conn.execute(
        namespace.join_owner(
            select(
                t.project.c.slug,
                t.project.c.name,
                t.project.c.repository_url,
                namespace.owner_handle().label("handle"),
            )
        )
        .where(t.project.c.id.in_(ids))
        .order_by(t.project.c.slug)
    ).all()
    return [
        {
            "slug": r.slug,
            "full_name": f"{r.handle}/{r.slug}",
            "name": r.name,
            "repository": r.repository_url,
        }
        for r in rows
    ]


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
        # Rows in the order every authenticated runner call touches them (credential,
        # runner, session), so that two calls never wait on each other in a cycle; the
        # credential row also serialises two hellos of one credential (one live session).
        conn.execute(
            update(t.runner_credential)
            .where(t.runner_credential.c.id == caller.credential_id)
            .values(last_used_at=now)
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
        name = conn.execute(select(t.runner.c.name).where(t.runner.c.id == runner_id)).scalar()
        packet = {
            "server_time": clock.rfc3339(now),
            "runner": {"id": runner_id, "name": name, "session_id": session_id},
            "projects": _projects(conn, runner_id),
            "placements": [pl.for_runner(conn, p) for p in pl.runner_reads(conn, runner_id)],
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
            if remaining <= 0 or longpoll.stopping.is_set():
                # Also when the process stops: the client simply waits again (§8.3).
                return answer([], cursor, superseded=False)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(waiter.event.wait(), min(remaining, FALLBACK_SECONDS))
    finally:
        longpoll.registry.leave(waiter)


# --- placements and reports (§15.7, §15.8) ---------------------------------------------------


class Status(Strict):
    seq: int = Field(ge=1, le=2**31 - 1)
    observed_generation: int = Field(ge=0, le=2**31 - 1)
    state: REPORTED_STATES
    reason: str | None = None
    detail: str | None = None
    exit_code: int | None = Field(default=None, ge=-(2**31), le=2**31 - 1)
    restarts: int = Field(ge=0, le=2**31 - 1)
    retry_at: AwareDatetime | None = None
    crash_count: int | None = Field(default=None, ge=0, le=2**31 - 1)
    crash_window_seconds: int | None = Field(default=None, ge=0, le=2**31 - 1)
    deadline_at: AwareDatetime | None = None
    target: Name
    since: AwareDatetime
    session_hint: Text | None = None


def _check_codes(body: Status) -> None:
    """The closed lists of §15.7, and which reason and detail go with which state."""
    errors: dict[str, str] = {}
    if body.reason is None:
        if body.state == "pending":
            errors["reason"] = "required_with_pending"
    elif body.reason not in pl.REASONS:
        errors["reason"] = "unknown"
    elif body.state not in pl.REASONS[body.reason]:
        errors["reason"] = "not_with_state"
    if body.detail is not None:
        rule = pl.DETAILS.get(body.detail)
        if rule is None:
            errors["detail"] = "unknown"
        elif (rule[0] == "reason" and body.reason != rule[1]) or (
            rule[0] == "state" and body.state != rule[1]
        ):
            errors["detail"] = "not_with_reason"
    if body.state == "rate_limited":
        # The reset time is the agent's limit (§15.7, §6.12): required, at most 7 days.
        if body.retry_at is None:
            errors["retry_at"] = "required_with_rate_limited"
        elif body.retry_at > clock.now() + availability.LIMIT_AHEAD:
            errors["retry_at"] = "too_far"
    if errors:
        raise invalid(errors)


def _own_placement(conn: Connection, runner_id: str, placement_id: str) -> Any:
    """A placement of this runner that it may read; closed ones included, which answer
    as they are (§15.8)."""
    found = conn.execute(
        select(t.placement).where(
            t.placement.c.id == placement_id,
            t.placement.c.runner_id == runner_id,
            t.placement.c.approval_status == "approved",
        )
    ).first()
    if found is None:
        raise not_found()
    return found


def _runner_answer(conn: Connection, placement: Any) -> dict[str, Any]:
    return {
        **pl.for_runner(conn, placement),
        "active": placement.active is True,
        "reported": pl.view(conn, placement, viewer_id="", briefing=False)["reported"],
    }


@router.get("/runner/placements")
def runner_placements(request: Request, caller: RunnerCaller) -> JSONResponse:
    runner_id = caller.runner_id
    assert runner_id is not None
    with engine_of(request).begin() as conn:
        items = [pl.for_runner(conn, p) for p in pl.runner_reads(conn, runner_id)]
        return JSONResponse({"items": items, "next_cursor": None})


@router.post("/runner/placements/{placement_id}/status")
def report_status(
    placement_id: str, body: Status, request: Request, caller: RunnerCaller
) -> JSONResponse:
    """No `Idempotency-Key`: a compare-and-set on `seq`, so a resend is applied as
    nothing (§15.8)."""
    runner_id = caller.runner_id
    assert runner_id is not None
    _check_codes(body)
    with events.transaction(engine_of(request)) as conn:
        placement = _own_placement(conn, runner_id, placement_id)
        events.lock_project(conn, placement.project_id)
        placement = pl.row(conn, placement.id)  # as it is under the lock
        try:
            after = pl.report(conn, placement, body.model_dump(), caller.runner_actor())
        except pl.Refusal as refusal:
            raise ApiError(refusal.status, refusal.code, refusal.message, refusal.details) from None
        return JSONResponse(_runner_answer(conn, after))


# --- the join pickup (§15.9) -------------------------------------------------------------

PICKUP_TTL = 300  # seconds
PICKUPS_PER_GENERATION = 3


class Pickup(Strict):
    observed_generation: int = Field(ge=0)


def _pickup_refused(why: str) -> ApiError:
    return ApiError(409, "pickup_not_allowed", "this placement cannot be picked up now",
                    {"why": why})  # fmt: skip


@router.post("/runner/placements/{placement_id}/join")
def pick_up(
    placement_id: str, body: Pickup, request: Request, caller: RunnerCaller
) -> JSONResponse:
    """A join for the placement's agent, as §3.1 would create one (§15.9). The URL and
    the code are in this answer only: no event, list or stored outcome carries them, so
    the call takes no `Idempotency-Key` and a lost answer is recovered by picking up
    again, which revokes the unused join of the same generation."""
    runner_id = caller.runner_id
    assert runner_id is not None
    settings = settings_of(request)
    with events.transaction(engine_of(request)) as conn:
        placement = _own_placement(conn, runner_id, placement_id)
        events.lock_project(conn, placement.project_id)
        placement = pl.row(conn, placement.id)  # as it is under the lock
        if placement.desired != "running" or placement.closed_at is not None:
            raise _pickup_refused("not_running")
        if body.observed_generation != placement.generation:
            raise _pickup_refused("stale_generation")
        if placement.credential_id is not None and not placement.rejoin:
            raise _pickup_refused("credential_issued")
        project = conn.execute(
            select(t.project).where(t.project.c.id == placement.project_id)
        ).one()
        if not allowed_projects.admits_membership(conn, placement.membership_id, project):
            # a rejoin included: a member its owner unticked keeps its membership (§6.3)
            raise _pickup_refused("project_not_allowed")
        j = t.join_link.c
        earlier = conn.execute(
            select(j.id, j.used_at, j.revoked_at).where(
                j.placement_id == placement.id, j.generation == placement.generation
            )
        ).all()
        if len(earlier) >= PICKUPS_PER_GENERATION:
            raise ApiError(409, "pickup_used", "this generation's pickups are used up")
        now = clock.now()
        conn.execute(  # never more than one live code per placement
            update(t.join_link)
            .where(
                j.placement_id == placement.id,
                j.used_at.is_(None),
                j.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        values, binds = _join_fields(conn, placement)  # the instance rules refuse here
        token, code = new_token(), new_code()
        via = "join" if settings.join_url else "public"
        join_id = new_id("join")
        expires = now + timedelta(seconds=PICKUP_TTL)
        conn.execute(
            insert(t.join_link).values(
                id=join_id,
                project_id=placement.project_id,
                token_hash=digest(token),
                code_hash=digest(normalise_code(code)),
                via=via,
                created_by=placement.created_by,
                created_at=now,
                expires_at=expires,
                failed_attempts=0,
                placement_id=placement.id,
                runner_id=runner_id,
                generation=placement.generation,
                **values,
            )
        )
        pickup = len(earlier) + 1
        events.emit(
            conn,
            placement.project_id,
            "join_picked_up",
            _owner_audience(conn, placement),
            {"placement_id": placement.id, "runner_id": runner_id, "join_id": join_id,
             "pickup": pickup},  # fmt: skip
            actor=caller.runner_actor(),
            subject=("placement", placement.id),
        )
        return JSONResponse(
            {
                "join_url": join_link(settings, via, token),
                "code": code,
                "expires_at": clock.rfc3339(expires),
                "credential_will_bind": binds,
                "pickup": pickup,
            },
            status_code=201,
        )


def _join_fields(conn: Connection, placement: Any) -> tuple[dict[str, Any], str]:
    """The join's agent, assignment and instance: for a member, a new instance within
    the team's `max_instances`, or for a rejoin one that replaces the instance of the
    revoked credential (§6.17, §15.9); for a profile the exchange creates, its stored
    fields (§3.1). Also what the credential will bind."""
    if placement.membership_id is not None:
        member = conn.execute(
            select(t.membership).where(t.membership.c.id == placement.membership_id)
        ).one()
        replaces = None
        if placement.rejoin and placement.credential_id is not None:
            old = conn.execute(
                select(t.credential).where(t.credential.c.id == placement.credential_id)
            ).one()
            if old.revoked_at is None:  # a live instance is never taken over
                raise _pickup_refused("credential_issued")
            replaces = instances.require_replaceable(
                conn, member, old.instance, "replaces", revoked=True
            ).instance
        instances.refuse_over_quota(conn, member)  # either way one more active instance
        return {
            "agent_id": member.agent_id,
            "trust": member.trust,
            "role": member.role,
            "reports_to": member.reports_to,
            "areas": member.areas,
            "capabilities": member.capabilities,
            "new_instance": replaces is None,
            "replaces": replaces,
        }, str(member.agent_id)
    taken = conn.execute(
        select(t.agent_profile.c.id).where(
            t.agent_profile.c.owner_id == placement.created_by,
            t.agent_profile.c.handle == placement.new_handle,
        )
    ).first()
    aliased = handles.holder(conn, placement.created_by, placement.new_handle)
    if taken is not None or aliased not in (None, "placement"):
        # the exchange would refuse it: no code that can never work
        raise _pickup_refused("handle_taken")
    profile = placement.new_profile or {}
    return {
        "new_agent_handle": placement.new_handle,
        "new_agent_display_name": profile.get("display_name") or placement.new_handle,
        "trust": profile.get("trust") or "member",
        "role": profile.get("role") or "coder",
        "reports_to": profile.get("reports_to"),
        "areas": profile.get("areas") or [],
        "capabilities": profile.get("capabilities") or [],
        "briefing": profile.get("briefing"),
    }, str(placement.new_handle)


def _owner_audience(conn: Connection, placement: Any) -> list[str]:
    """`join_picked_up` goes to the agent profile's owner and `trust:owner` (§8.2). A
    profile the exchange will create is the placement creator's."""
    owner = placement.created_by
    if placement.membership_id is not None:
        owner = conn.execute(
            select(t.agent_profile.c.owner_id)
            .join(t.membership, t.membership.c.agent_id == t.agent_profile.c.id)
            .where(t.membership.c.id == placement.membership_id)
        ).scalar_one()
    return [f"member:{owner}", "trust:owner"]
