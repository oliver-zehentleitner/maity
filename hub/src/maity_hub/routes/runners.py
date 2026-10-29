"""Runners: enrollments, the pairing exchange, the owner's runner calls, and
attaching runners to projects (docs/api.md §15.2–15.4).

Pairing is the join mechanism for the instance instead of a project: a
human creates an enrollment and gets one line with the URL (128-bit token)
and the code (60 bits); the exchange on the runner host trades the code for
the runner's credential once. The hub stores only hashes of token and code;
the credential is the response body and nothing else.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import Field
from sqlalchemy import Connection, and_, insert, or_, select, update
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from maity_hub import (
    clock,
    events,
    idempotency,
    moderation,
    namespace,
    paging,
    placements,
    runner_revoke,
)
from maity_hub import tables as t
from maity_hub.access import membership
from maity_hub.auth import credentials, second_factor
from maity_hub.auth.caller import Caller, require_secure_transport
from maity_hub.auth.leaks import revoke_runner_credential
from maity_hub.codes import code_matches, digest, new_code, new_token, normalise_code
from maity_hub.db import retrying
from maity_hub.deps import AnyCaller, HumanCaller, engine_of, origin_of, settings_of
from maity_hub.errors import ApiError, forbidden, invalid, not_found, rate_limited
from maity_hub.ids import new_id
from maity_hub.models import HANDLE_PATTERN, Strict, markdown
from maity_hub.namespace import ProjectRoute
from maity_hub.ratelimit import Limiter
from maity_hub.runners import (
    administers,
    attach,
    attached_project_ids,
    attachment_view,
    detach,
    enrollment_view,
    live_credential_id,
    load_runner,
    runner_view,
    visible_to,
)
from maity_hub.scopes import has_scope

router = APIRouter(route_class=ProjectRoute)
page_router = APIRouter(route_class=ProjectRoute)  # /r/{token}, outside the API prefix

TTL_DEFAULT, TTL_MIN, TTL_MAX = 900, 60, 900
WRONG_CODES_BEFORE_BURN = 3
PAIR_BY_ADDRESS = Limiter(10, 60)
PAGE_DEFAULT, PAGE_MAX = 50, 200


class EnrollmentCreate(Strict):
    name: str | None = Field(default=None, pattern=HANDLE_PATTERN)
    ttl_seconds: int = TTL_DEFAULT
    attach: list[str] = Field(default_factory=list, max_length=50)
    runner_id: str | None = None


class Pair(Strict):
    code: str = Field(min_length=1, max_length=64)
    client: str = Field(min_length=1, max_length=200)


class RunnerUpdate(Strict):
    name: str = Field(pattern=HANDLE_PATTERN)


class RunnerRevoke(Strict):
    reason: str | None = markdown(default=None)
    # The owner's override (§15.3): each project's rule, or stop everywhere.
    agents: Literal["policy", "stop"] = "policy"


class RunnerRemove(Strict):
    agents: Literal["policy", "stop"] = "policy"


class AttachIn(Strict):
    runner_id: str


def _viewer(request: Request) -> str | None:
    """The viewing human; None when the runner reads itself (`PATCH /runner`)."""
    caller: Caller = request.state.caller
    return None if caller.kind == "runner" else caller.principal_id


def load_enrollment(conn: Connection, enrollment_id: str) -> dict[str, Any]:
    row = conn.execute(
        select(t.runner_enrollment).where(t.runner_enrollment.c.id == enrollment_id)
    ).one()
    return enrollment_view(conn, row)


def load_attachment(conn: Connection, attachment_id: str, request: Request) -> dict[str, Any]:
    row = conn.execute(
        select(t.runner_attachment).where(t.runner_attachment.c.id == attachment_id)
    ).one()
    return attachment_view(conn, row, _viewer(request))


def _load_removal(conn: Connection, runner_id: str, request: Request) -> dict[str, Any]:
    """The removed runner, with the placements it closed whose last report said they
    were still running: the operator's to end now (§15.3)."""
    closed = conn.execute(
        select(t.placement.c.id, t.placement.c.reported)
        .where(
            t.placement.c.runner_id == runner_id,
            t.placement.c.closed_reason == "runner_removed",
        )
        .order_by(t.placement.c.id)
    ).all()
    still = [r.id for r in closed if (r.reported or {}).get("state") in placements.RUNNING_STATES]
    viewer = _viewer(request)
    return {
        **load_runner(conn, runner_id, viewer),
        "still_running": still,
        "on_runner_revoke": runner_revoke.answer(conn, _applied(conn, runner_id), viewer),
    }


def _applied(conn: Connection, runner_id: str) -> list[dict[str, Any]]:
    """What the runner's latest revocation applied (§15.3), as stored with it."""
    applied: list[dict[str, Any]] | None = conn.execute(
        select(t.runner_credential.c.stopped)
        .where(
            t.runner_credential.c.runner_id == runner_id,
            t.runner_credential.c.revoked_at.is_not(None),
        )
        .order_by(t.runner_credential.c.revoked_at.desc())
        .limit(1)
    ).scalar()
    return applied or []


def _record_applied(conn: Connection, runner_id: str, applied: list[dict[str, Any]]) -> None:
    """Add a later stop to the latest revoked key's record: the answer, its replay and
    the runner's `details.stop` read it from there."""
    latest = conn.execute(
        select(t.runner_credential.c.id, t.runner_credential.c.stopped)
        .where(t.runner_credential.c.runner_id == runner_id)
        .order_by(t.runner_credential.c.created_at.desc())
        .limit(1)
    ).first()
    if latest is None:
        return
    conn.execute(
        update(t.runner_credential)
        .where(t.runner_credential.c.id == latest.id)
        .values(stopped=runner_revoke.merge(latest.stopped, applied))
    )


def _load_revoked(conn: Connection, runner_id: str, request: Request) -> dict[str, Any]:
    """The runner after a revoke, with what it did to the agents (§15.3)."""
    viewer = _viewer(request)
    view = load_runner(conn, runner_id, viewer)
    return {
        **view,
        "on_runner_revoke": runner_revoke.answer(conn, _applied(conn, runner_id), viewer),
    }


idempotency.LOADERS["runner_enrollment"] = idempotency.plain(load_enrollment)
idempotency.LOADERS["runner"] = lambda conn, runner_id, request: load_runner(
    conn, runner_id, _viewer(request)
)
idempotency.LOADERS["runner_removal"] = _load_removal
idempotency.LOADERS["runner_revoked"] = lambda conn, runner_id, request: _load_revoked(
    conn, runner_id, request
)
idempotency.LOADERS["runner_attachment"] = load_attachment


def _name_taken(conn: Connection, owner_id: str, name: str, but: str | None = None) -> bool:
    found = conn.execute(
        select(t.runner.c.id).where(
            t.runner.c.owner_id == owner_id,
            t.runner.c.name == name,
            t.runner.c.active.is_(True),
        )
    ).scalar()
    return found is not None and found != but


# --- enrollments (human) ----------------------------------------------------------


@router.post("/runners/enrollments")
def create_enrollment(
    body: EnrollmentCreate, request: Request, caller: HumanCaller
) -> JSONResponse:
    if not TTL_MIN <= body.ttl_seconds <= TTL_MAX:
        raise invalid({"ttl_seconds": "out_of_range"})
    public_url = settings_of(request).public_url
    hub = settings_of(request)

    def action(conn: Connection) -> idempotency.Outcome:
        owner_id = caller.principal_id
        second_factor.require_step_up(conn, hub, caller)  # mints a credential (§2.8.4)
        if body.runner_id is None:
            if body.name is None:
                raise invalid({"name": "required"}, "a new runner needs a name")
            if _name_taken(conn, owner_id, body.name):
                raise invalid({"name": "taken"}, "you have a runner of that name")
        else:
            if body.name is not None:
                raise invalid({"name": "with_runner_id"}, "a re-pair keeps the runner's name")
            runner = conn.execute(
                select(t.runner.c.id).where(
                    t.runner.c.id == body.runner_id,
                    t.runner.c.owner_id == owner_id,
                    t.runner.c.active.is_(True),
                )
            ).first()
            if runner is None:
                raise invalid({"runner_id": "not_yours"}, "a re-pair names one of your runners")
        attach_ids = []
        for slug in dict.fromkeys(body.attach):
            # Checked now and again at the exchange (§15.2).
            mine = membership(conn, caller, slug)
            mine.require("members:admin")
            attach_ids.append(mine.project.id)
        token, code = new_token(), new_code()
        now = clock.now()
        expires_at = now + timedelta(seconds=body.ttl_seconds)
        enrollment_id = new_id("runner_enrollment")
        conn.execute(
            insert(t.runner_enrollment).values(
                id=enrollment_id,
                runner_id=body.runner_id,
                name=body.name,
                attach=attach_ids,
                token_hash=digest(token),
                code_hash=digest(normalise_code(code)),
                created_by=owner_id,
                created_at=now,
                expires_at=expires_at,
                failed_attempts=0,
            )
        )
        pair_url = f"{public_url}/r/{token}"
        return idempotency.Outcome(
            201,
            "runner_enrollment",
            enrollment_id,
            {
                "id": enrollment_id,
                # A new runner exists from the exchange on (§15.2).
                "runner_id": body.runner_id,
                "pair_url": pair_url,
                "code": code,
                "pair_line": f"maity runner pair {pair_url} --code {code}",
                "expires_at": clock.rfc3339(expires_at),
            },
        )

    return idempotency.run(engine_of(request), request, caller, action)


@router.get("/runners/enrollments")
def list_enrollments(
    request: Request,
    caller: HumanCaller,
    limit: int = Query(default=PAGE_DEFAULT, ge=1, le=PAGE_MAX),
    cursor: str | None = None,
) -> JSONResponse:
    enrollment = t.runner_enrollment.c
    query = select(t.runner_enrollment).where(enrollment.created_by == caller.principal_id)
    if cursor is not None:
        after_at, after_id = paging.uncursor(cursor)
        query = query.where(
            or_(
                enrollment.created_at < after_at,
                and_(enrollment.created_at == after_at, enrollment.id < after_id),
            )
        )
    with engine_of(request).begin() as conn:
        rows = conn.execute(
            query.order_by(enrollment.created_at.desc(), enrollment.id.desc()).limit(limit + 1)
        ).all()
        page = rows[:limit]
        next_cursor = paging.cursor(page[-1].created_at, page[-1].id) if len(rows) > limit else None
        items = [enrollment_view(conn, r) for r in page]
    return JSONResponse({"items": items, "next_cursor": next_cursor})


@router.delete("/runners/enrollments/{enrollment_id}")
def revoke_enrollment(enrollment_id: str, request: Request, caller: HumanCaller) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        row = conn.execute(
            select(t.runner_enrollment).where(
                t.runner_enrollment.c.id == enrollment_id,
                t.runner_enrollment.c.created_by == caller.principal_id,
            )
        ).first()
        if row is None:
            raise not_found()
        if row.revoked_at is None:
            state = _spent(row)
            if state is not None:
                raise ApiError(
                    409,
                    "invalid_transition",
                    f"a {state} enrollment cannot be revoked",
                    {"from": state, "to": "revoked"},
                )
            conn.execute(
                update(t.runner_enrollment)
                .where(t.runner_enrollment.c.id == enrollment_id)
                .values(revoked_at=clock.now())
            )
        return idempotency.Outcome(
            200, "runner_enrollment", enrollment_id, load_enrollment(conn, enrollment_id)
        )

    return idempotency.run(engine_of(request), request, caller, action)


def _spent(row: Any) -> str | None:
    if row.used_at is not None:
        return "used"
    if row.burned_at is not None:
        return "burned"
    if row.expires_at <= clock.now():
        return "expired"
    return None


def _usable(conn: Connection, token: str) -> Any:
    row = conn.execute(
        select(t.runner_enrollment).where(t.runner_enrollment.c.token_hash == digest(token))
    ).first()
    if row is None or row.revoked_at is not None or _spent(row) is not None:
        raise not_found()
    return row


# --- the pairing exchange (runner host) ---------------------------------------------


@page_router.get("/r/{token}")
def pairing_page(token: str) -> Response:
    """There is no pairing page: only the CLI pairs a runner (§15.2)."""
    raise not_found()


@router.post("/runners/pair/{token}")
async def pair(token: str, body: Pair, request: Request) -> Response:
    origin = origin_of(request)
    settings = settings_of(request)
    # The answer is a credential: it travels like one, under the join's rule (§2.5).
    require_secure_transport(origin, settings.allow_plain_http)
    if request.headers.get("authorization"):
        raise forbidden(message="the exchange takes no credential")
    wait = PAIR_BY_ADDRESS.hit(origin.address)
    if wait:
        raise rate_limited(wait)
    engine = engine_of(request)

    def run() -> tuple[str, str, str, list[str]] | None:
        """The credential facts, or None for a wrong code (recorded and committed)."""
        with events.transaction(engine) as conn:
            row = _usable(conn, token)
            # One conditional UPDATE takes an attempt slot before the comparison,
            # exactly as the join exchange does (routes/joins.py).
            now = clock.now()
            slot = conn.execute(
                update(t.runner_enrollment)
                .where(
                    t.runner_enrollment.c.id == row.id,
                    t.runner_enrollment.c.failed_attempts < WRONG_CODES_BEFORE_BURN,
                    t.runner_enrollment.c.used_at.is_(None),
                    t.runner_enrollment.c.burned_at.is_(None),
                    t.runner_enrollment.c.revoked_at.is_(None),
                    t.runner_enrollment.c.expires_at > now,
                )
                .values(failed_attempts=t.runner_enrollment.c.failed_attempts + 1)
            ).rowcount
            if slot != 1:
                raise not_found()
            if code_matches(body.code, row.code_hash):
                return _consume(conn, row, body.client)
            conn.execute(
                update(t.runner_enrollment)
                .where(
                    t.runner_enrollment.c.id == row.id,
                    t.runner_enrollment.c.failed_attempts >= WRONG_CODES_BEFORE_BURN,
                    t.runner_enrollment.c.burned_at.is_(None),
                )
                .values(burned_at=now)
            )
        return None

    outcome = await run_in_threadpool(retrying, run)
    if outcome is None:
        raise ApiError(403, "code_invalid", "the code does not match this enrollment")
    value, credential_id, runner_id, attached = outcome
    return Response(
        value,
        status_code=201,
        media_type="text/plain; charset=utf-8",
        headers={
            "Maity-Credential-Id": credential_id,
            "Maity-Runner-Id": runner_id,
            "Maity-Attached": ",".join(attached),
            "Maity-Hub": settings.public_url,
            "Maity-Signing": "required",  # a runner signs every call (§15.1)
        },
    )


def _consume(conn: Connection, row: Any, client: str) -> tuple[str, str, str, list[str]]:
    moderation.refuse_suspended(conn, row.created_by)  # no credential for it (§16.8)
    now = clock.now()
    consumed = conn.execute(
        update(t.runner_enrollment)
        .where(
            t.runner_enrollment.c.id == row.id,
            t.runner_enrollment.c.used_at.is_(None),
            t.runner_enrollment.c.burned_at.is_(None),
            t.runner_enrollment.c.revoked_at.is_(None),
        )
        .values(used_at=now)
    ).rowcount
    if consumed != 1:  # a concurrent exchange won
        raise not_found()
    if row.runner_id is None:
        runner_id = _create_runner(conn, row.created_by, row.name)
    else:
        runner_id = row.runner_id
        # The row lock orders two re-pairs of one runner: one live credential (§15.1).
        runner = conn.execute(
            select(t.runner.c.id)
            .where(t.runner.c.id == runner_id, t.runner.c.active.is_(True))
            .with_for_update()
        ).first()
        if runner is None:  # removed since the enrollment was created
            raise not_found()
        previous = live_credential_id(conn, runner_id)
        if previous is not None:
            revoke_runner_credential(conn, previous, "repaired", by=row.created_by)
    credential_id = new_id("runner_credential")
    value, verifier = credentials.issue(credential_id)
    conn.execute(
        insert(t.runner_credential).values(
            id=credential_id,
            runner_id=runner_id,
            verifier=verifier,
            enrollment_id=row.id,
            client=client,
            created_at=now,
            live=True,
        )
    )
    return value, credential_id, runner_id, _attach_at_exchange(conn, row, runner_id)


def _attach_at_exchange(conn: Connection, row: Any, runner_id: str) -> list[str]:
    """The enrollment's projects where its creator still holds `members:admin`; the
    slugs attached now, for `Maity-Attached` (§15.2)."""
    attached = []
    for project_id in row.attach:
        if not administers(conn, project_id, row.created_by):
            continue
        _, created = attach(conn, project_id, runner_id, row.created_by)
        if created:
            slug: str = namespace.name_of(conn, project_id)
            attached.append(slug)
    return attached


def _create_runner(conn: Connection, owner_id: str, name: str) -> str:
    # Checked when the enrollment was created, and again here: the owner may have
    # paired another runner of that name since. The enrollment stays unused.
    taken = invalid({"name": "taken"}, "you have a runner of that name")
    if _name_taken(conn, owner_id, name):
        raise taken
    runner_id = new_id("runner")
    now = clock.now()
    try:
        with conn.begin_nested():
            conn.execute(
                insert(t.runner).values(
                    id=runner_id,
                    owner_id=owner_id,
                    name=name,
                    created_at=now,
                    updated_at=now,
                    active=True,
                )
            )
    except IntegrityError:  # a concurrent exchange paired that name first
        raise taken from None
    return runner_id


# --- runners (human) ------------------------------------------------------------------


def _visible_runner(conn: Connection, caller: Caller, runner_id: str) -> Any:
    row = conn.execute(select(t.runner).where(t.runner.c.id == runner_id)).first()
    if row is None or not visible_to(conn, row, caller.principal_id):
        raise not_found()
    return row


def _own_runner(conn: Connection, caller: Caller, runner_id: str, *, lock: bool = False) -> Any:
    """The caller's runner; `lock` orders a change with a concurrent re-pair (`_consume`)."""
    query = select(t.runner).where(
        t.runner.c.id == runner_id, t.runner.c.owner_id == caller.principal_id
    )
    row = conn.execute(query.with_for_update() if lock else query).first()
    if row is None:
        raise not_found()
    return row


def _refuse_removed(row: Any) -> None:
    if row.removed_at is not None:
        raise ApiError(
            409, "invalid_transition", "the runner was removed", {"from": "removed", "to": None}
        )


@router.get("/runners")
def list_runners(request: Request, caller: HumanCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        administered = [
            r.project_id
            for r in conn.execute(
                select(t.membership.c.project_id, t.membership.c.trust, t.membership.c.role).where(
                    t.membership.c.human_id == caller.principal_id,
                    t.membership.c.active.is_(True),
                )
            )
            if has_scope(r.trust, r.role, "human", "members:admin")
        ]
        attached_there = select(t.runner_attachment.c.runner_id).where(
            t.runner_attachment.c.project_id.in_(administered),
            t.runner_attachment.c.active.is_(True),
        )
        rows = conn.execute(
            select(t.runner)
            .where(
                t.runner.c.active.is_(True),
                (t.runner.c.owner_id == caller.principal_id) | t.runner.c.id.in_(attached_there),
            )
            .order_by(t.runner.c.name, t.runner.c.id)
        ).all()
        views = [runner_view(conn, r, caller.principal_id) for r in rows]
        return JSONResponse({"items": views, "next_cursor": None})


@router.get("/runners/{runner_id}")
def get_runner(runner_id: str, request: Request, caller: HumanCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        row = _visible_runner(conn, caller, runner_id)
        return JSONResponse(runner_view(conn, row, caller.principal_id))


@router.patch("/runners/{runner_id}")
def update_runner(
    runner_id: str, body: RunnerUpdate, request: Request, caller: HumanCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        row = _own_runner(conn, caller, runner_id)
        _refuse_removed(row)
        if body.name != row.name:
            taken = invalid({"name": "taken"}, "you have a runner of that name")
            if _name_taken(conn, caller.principal_id, body.name, but=runner_id):
                raise taken
            try:
                with conn.begin_nested():
                    conn.execute(
                        update(t.runner)
                        .where(t.runner.c.id == runner_id)
                        .values(name=body.name, updated_at=clock.now())
                    )
            except IntegrityError:  # a concurrent rename took the name first
                raise taken from None
        return idempotency.Outcome(
            200, "runner", runner_id, load_runner(conn, runner_id, caller.principal_id)
        )

    return idempotency.run(engine_of(request), request, caller, action)


@router.post("/runners/{runner_id}/revoke")
def revoke_runner(
    runner_id: str, request: Request, caller: HumanCaller, body: RunnerRevoke | None = None
) -> JSONResponse:
    reason = body.reason if body and body.reason else "revoked"  # as for an agent's
    agents = body.agents if body else "policy"
    instance_rule = settings_of(request).on_runner_revoke

    def action(conn: Connection) -> idempotency.Outcome:
        _own_runner(conn, caller, runner_id, lock=True)
        live = live_credential_id(conn, runner_id)
        applied: list[dict[str, Any]] = []
        if live is not None:
            applied = runner_revoke.apply(
                conn,
                runner_id,
                agents=agents,
                instance_rule=instance_rule,
                removing=False,
                by=caller.principal_id,
            )
            revoke_runner_credential(conn, live, reason, by=caller.principal_id, applied=applied)
            placements.runner_credential_gone(conn, runner_id, caller.principal_id)
        elif agents == "stop":
            # A key revoked already (by a `keep`, or for a leak): the owner's stop still
            # stops its agents, added to what that revocation applied (§15.3).
            applied = runner_revoke.apply(
                conn,
                runner_id,
                agents="stop",
                instance_rule=instance_rule,
                removing=False,
                by=caller.principal_id,
            )
            _record_applied(conn, runner_id, applied)
        return idempotency.Outcome(
            200, "runner_revoked", runner_id, _load_revoked(conn, runner_id, request)
        )

    return idempotency.run(engine_of(request), request, caller, action)


@router.delete("/runners/{runner_id}")
def remove_runner(
    runner_id: str, request: Request, caller: HumanCaller, body: RunnerRemove | None = None
) -> JSONResponse:
    agents = body.agents if body else "policy"
    instance_rule = settings_of(request).on_runner_revoke

    def action(conn: Connection) -> idempotency.Outcome:
        row = _own_runner(conn, caller, runner_id, lock=True)
        if row.removed_at is None:
            remove(
                conn, runner_id, agents=agents, instance_rule=instance_rule, by=caller.principal_id
            )
        return idempotency.Outcome(
            200, "runner_removal", runner_id, _load_removal(conn, runner_id, request)
        )

    return idempotency.run(engine_of(request), request, caller, action)


def remove(conn: Connection, runner_id: str, *, agents: str, instance_rule: str, by: str) -> None:
    """Remove a runner as `DELETE /runners/{id}` does (§15.3), on the authority of `by`,
    its owner; the caller has locked the runner row and checked that it is not removed.
    Shared with the deletion of the owner's account (§2.9), which passes `agents: stop`."""
    now = clock.now()
    # Each project's rule first, while the runner is still attached: under stop its
    # agents' credentials go too (§15.3); every placement closes either way.
    applied = runner_revoke.apply(
        conn, runner_id, agents=agents, instance_rule=instance_rule, removing=True, by=by
    )
    placements.runner_removed(conn, runner_id, by)
    live = live_credential_id(conn, runner_id)
    if live is not None:
        revoke_runner_credential(conn, live, "runner_removed", by=by, applied=applied)
    for project_id in attached_project_ids(conn, runner_id):
        detach(conn, project_id, runner_id, by)
    # An open re-pair would bring the removed runner back.
    conn.execute(
        update(t.runner_enrollment)
        .where(
            t.runner_enrollment.c.runner_id == runner_id,
            t.runner_enrollment.c.used_at.is_(None),
            t.runner_enrollment.c.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    conn.execute(
        update(t.runner)
        .where(t.runner.c.id == runner_id)
        .values(removed_at=now, updated_at=now, active=None)
    )


# --- attachments (§15.4) ---------------------------------------------------------------


@router.get("/projects/{owner}/{slug}/runners")
def list_project_runners(slug: str, request: Request, caller: AnyCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        # Agents only to propose placements (§15.4); every other agent is refused.
        mine.require("project:read" if mine.kind == "human" else "agents:propose")
        rows = conn.execute(
            select(t.runner_attachment)
            .join(t.runner, t.runner.c.id == t.runner_attachment.c.runner_id)
            .where(
                t.runner_attachment.c.project_id == mine.project.id,
                t.runner_attachment.c.active.is_(True),
            )
            .order_by(t.runner.c.name, t.runner.c.id)
        ).all()
        admin = mine.may("members:admin") or mine.may("agents:propose")
        items = [attachment_view(conn, r, mine.principal_id, capabilities=admin) for r in rows]
        return JSONResponse({"items": items, "next_cursor": None})


@router.post("/projects/{owner}/{slug}/runners")
def attach_runner(slug: str, body: AttachIn, request: Request, caller: HumanCaller) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine.require("members:admin")
        # Locked like removal, so a runner removed meanwhile is not attached again.
        owned = conn.execute(
            select(t.runner.c.id)
            .where(
                t.runner.c.id == body.runner_id,
                t.runner.c.owner_id == caller.principal_id,
                t.runner.c.active.is_(True),
            )
            .with_for_update()
        ).first()
        if owned is None:
            raise invalid({"runner_id": "not_yours"}, "attach one of your own runners")
        row, created = attach(conn, mine.project.id, body.runner_id, caller.principal_id)
        view = attachment_view(conn, row, caller.principal_id)
        if not created:
            raise ApiError(
                409, "already_attached", "the runner is attached already", {"attachment": view}
            )
        return idempotency.Outcome(201, "runner_attachment", row.id, view)

    return idempotency.run(engine_of(request), request, caller, action)


@router.delete("/projects/{owner}/{slug}/runners/{runner_id}")
def detach_runner(slug: str, runner_id: str, request: Request, caller: HumanCaller) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        owner = conn.execute(select(t.runner.c.owner_id).where(t.runner.c.id == runner_id)).scalar()
        if owner != caller.principal_id:
            mine.require("members:admin")
        row = detach(conn, mine.project.id, runner_id, caller.principal_id)
        if row is not None:  # its placements here close the uniform way (§15.5)
            placements.detached(
                conn, mine.project.id, runner_id, caller.actor(mine.id), caller.principal_id
            )
        if row is None:  # detached already: answered as it is
            row = conn.execute(
                select(t.runner_attachment)
                .where(
                    t.runner_attachment.c.project_id == mine.project.id,
                    t.runner_attachment.c.runner_id == runner_id,
                )
                .order_by(t.runner_attachment.c.attached_at.desc())
                .limit(1)
            ).first()
            if row is None:
                raise not_found()
        view = attachment_view(
            conn, row, caller.principal_id, capabilities=mine.may("members:admin")
        )
        return idempotency.Outcome(200, "runner_attachment", row.id, view)

    return idempotency.run(engine_of(request), request, caller, action)
