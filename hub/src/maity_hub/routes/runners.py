"""Runners: enrollments, the pairing exchange, and the owner's runner calls
(docs/api.md §15.2, §15.3).

Pairing is the join mechanism for the instance instead of a project: a
human creates an enrollment and gets one line with the URL (128-bit token)
and the code (60 bits); the exchange on the runner host trades the code for
the runner's credential once. The hub stores only hashes of token and code;
the credential is the response body and nothing else.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import Field
from sqlalchemy import Connection, insert, select, update
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from maity_hub import clock, events, idempotency
from maity_hub import tables as t
from maity_hub.auth import credentials
from maity_hub.auth.caller import Caller, require_secure_transport
from maity_hub.auth.leaks import revoke_runner_credential
from maity_hub.codes import code_matches, digest, new_code, new_token, normalise_code
from maity_hub.db import retrying
from maity_hub.deps import HumanCaller, engine_of, origin_of, settings_of
from maity_hub.errors import ApiError, forbidden, invalid, not_found, rate_limited
from maity_hub.ids import new_id
from maity_hub.models import HANDLE_PATTERN, Strict, markdown
from maity_hub.ratelimit import Limiter
from maity_hub.runners import enrollment_view, live_credential_id, load_runner, runner_view

router = APIRouter()
page_router = APIRouter()  # /r/{token}, outside the API prefix

TTL_DEFAULT, TTL_MIN, TTL_MAX = 900, 60, 900
WRONG_CODES_BEFORE_BURN = 3
PAIR_BY_ADDRESS = Limiter(10, 60)


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


def _viewer(request: Request) -> str:
    caller: Caller = request.state.caller
    return caller.principal_id


def load_enrollment(conn: Connection, enrollment_id: str) -> dict[str, Any]:
    row = conn.execute(
        select(t.runner_enrollment).where(t.runner_enrollment.c.id == enrollment_id)
    ).one()
    return enrollment_view(row)


def _load_removal(conn: Connection, runner_id: str, request: Request) -> dict[str, Any]:
    # Placements come with §15.5; until then nothing of a runner can still be running.
    return {**load_runner(conn, runner_id, _viewer(request)), "still_running": []}


idempotency.LOADERS["runner_enrollment"] = idempotency.plain(load_enrollment)
idempotency.LOADERS["runner"] = lambda conn, runner_id, request: load_runner(
    conn, runner_id, _viewer(request)
)
idempotency.LOADERS["runner_removal"] = _load_removal


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
    if body.attach:
        # Attaching at the exchange arrives with attachments (§15.4); until then an
        # enrollment that asks for it is refused rather than paired without it.
        raise invalid({"attach": "not_supported_yet"}, "attachments are not available yet")
    public_url = settings_of(request).public_url

    def action(conn: Connection) -> idempotency.Outcome:
        owner_id = caller.principal_id
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
        token, code = new_token(), new_code()
        now = clock.now()
        expires_at = now + timedelta(seconds=body.ttl_seconds)
        enrollment_id = new_id("runner_enrollment")
        conn.execute(
            insert(t.runner_enrollment).values(
                id=enrollment_id,
                runner_id=body.runner_id,
                name=body.name,
                attach=[],
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
def list_enrollments(request: Request, caller: HumanCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        rows = conn.execute(
            select(t.runner_enrollment)
            .where(t.runner_enrollment.c.created_by == caller.principal_id)
            .order_by(t.runner_enrollment.c.created_at.desc(), t.runner_enrollment.c.id.desc())
        ).all()
        return JSONResponse({"items": [enrollment_view(r) for r in rows], "next_cursor": None})


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

    def run() -> tuple[str, str, str] | None:
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
    value, credential_id, runner_id = outcome
    return Response(
        value,
        status_code=201,
        media_type="text/plain; charset=utf-8",
        headers={
            "Maity-Credential-Id": credential_id,
            "Maity-Runner-Id": runner_id,
            "Maity-Attached": "",
            "Maity-Hub": settings.public_url,
            "Maity-Signing": "required",  # a runner signs every call (§15.1)
        },
    )


def _consume(conn: Connection, row: Any, client: str) -> tuple[str, str, str]:
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
    return value, credential_id, runner_id


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


def _own_runner(conn: Connection, caller: Caller, runner_id: str) -> Any:
    row = conn.execute(
        select(t.runner).where(
            t.runner.c.id == runner_id, t.runner.c.owner_id == caller.principal_id
        )
    ).first()
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
        rows = conn.execute(
            select(t.runner)
            .where(t.runner.c.owner_id == caller.principal_id, t.runner.c.active.is_(True))
            .order_by(t.runner.c.name)
        ).all()
        views = [runner_view(conn, r, caller.principal_id) for r in rows]
        return JSONResponse({"items": views, "next_cursor": None})


@router.get("/runners/{runner_id}")
def get_runner(runner_id: str, request: Request, caller: HumanCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        row = _own_runner(conn, caller, runner_id)
        return JSONResponse(runner_view(conn, row, caller.principal_id))


@router.patch("/runners/{runner_id}")
def update_runner(
    runner_id: str, body: RunnerUpdate, request: Request, caller: HumanCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        row = _own_runner(conn, caller, runner_id)
        _refuse_removed(row)
        if body.name != row.name:
            if _name_taken(conn, caller.principal_id, body.name, but=runner_id):
                raise invalid({"name": "taken"}, "you have a runner of that name")
            conn.execute(
                update(t.runner)
                .where(t.runner.c.id == runner_id)
                .values(name=body.name, updated_at=clock.now())
            )
        return idempotency.Outcome(
            200, "runner", runner_id, load_runner(conn, runner_id, caller.principal_id)
        )

    return idempotency.run(engine_of(request), request, caller, action)


@router.post("/runners/{runner_id}/revoke")
def revoke_runner(
    runner_id: str, request: Request, caller: HumanCaller, body: RunnerRevoke | None = None
) -> JSONResponse:
    reason = body.reason if body else None

    def action(conn: Connection) -> idempotency.Outcome:
        _own_runner(conn, caller, runner_id)
        live = live_credential_id(conn, runner_id)
        if live is not None:  # none live: answered as it is
            revoke_runner_credential(conn, live, reason, by=caller.principal_id)
        return idempotency.Outcome(
            200, "runner", runner_id, load_runner(conn, runner_id, caller.principal_id)
        )

    return idempotency.run(engine_of(request), request, caller, action)


@router.delete("/runners/{runner_id}")
def remove_runner(runner_id: str, request: Request, caller: HumanCaller) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        row = _own_runner(conn, caller, runner_id)
        if row.removed_at is None:
            now = clock.now()
            live = live_credential_id(conn, runner_id)
            if live is not None:
                revoke_runner_credential(conn, live, "runner_removed", by=caller.principal_id)
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
        return idempotency.Outcome(
            200, "runner_removal", runner_id, _load_removal(conn, runner_id, request)
        )

    return idempotency.run(engine_of(request), request, caller, action)
