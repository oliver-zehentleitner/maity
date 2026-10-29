"""Registration (docs/api.md §2.7, §16.4): `POST /auth/register`, the instance admin's
`/admin/settings/registration` and `DELETE /admin/registrations/blocks/{address}`.

`POST /auth/register` answers `202` for every request that passes the synchronous checks,
after the password is hashed, so neither the answer nor its timing says whether an
address has an account or is listed. What depends on the address runs after the answer,
in a transaction of its own: the mode, the block, the per-address limits and the pending
registration.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Body, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import Connection, Engine, and_, delete, insert, or_, select, update
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from maity_hub import (
    clock,
    paging,
    registration,
    registration_accounts,
    registration_mail,
)
from maity_hub import tables as t
from maity_hub.admin import instance_admin_id
from maity_hub.auth import passwords, second_factor
from maity_hub.auth.caller import require_secure_transport
from maity_hub.deps import HumanCaller, engine_of, origin_of, settings_of
from maity_hub.errors import ApiError, forbidden, invalid, not_found, rate_limited
from maity_hub.ids import new_id
from maity_hub.mail import address
from maity_hub.ratelimit import Limiter

router = APIRouter()

PAGE_DEFAULT, PAGE_MAX = 50, 200

PASSWORD_MIN = 12  # §2.1
BY_SOURCE = Limiter(10, 3600)  # POST /auth/register per source address (§2.7.3), 429
# Silent limits: over them the answer is still 202 and nothing is sent (§2.7.3).
BY_PAIR_SHORT = Limiter(3, 900)
BY_PAIR_DAY = Limiter(10, 86400)
BY_ADDRESS_DAY = Limiter(20, 86400)


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    address: str = Field(max_length=254)
    password: str = Field(min_length=PASSWORD_MIN, max_length=1024)
    next: str | None = Field(default=None, max_length=2048)


def _environment(request: Request) -> registration.RegistrationEnvironment:
    found = settings_of(request).registration
    return found if found is not None else registration.RegistrationEnvironment()


def _resolved(conn: Connection, hub: Any) -> registration.Resolved:
    found = hub.registration if hub.registration is not None else None
    env = found or registration.RegistrationEnvironment()
    return registration.resolve(conn, env, registration.mail_ready(conn, hub))


def _closed() -> ApiError:
    return ApiError(403, "forbidden", "registration is closed", {"reason": "registration_closed"})


def _body(raw: bytes) -> RegisterIn:
    try:
        data = json.loads(raw or b"null")
    except ValueError:
        raise invalid({"body": "not_json"}) from None
    if not isinstance(data, dict):
        raise invalid({"body": "not_an_object"})
    try:
        body = RegisterIn.model_validate(data)
    except ValidationError as error:
        fields = {".".join(str(p) for p in e["loc"]) or "body": e["type"] for e in error.errors()}
        raise invalid(fields) from None
    errors: dict[str, str] = {}
    if not address.valid(body.address.strip()):
        errors["address"] = "invalid"
    if errors:
        raise invalid(errors)
    return body


@router.post("/auth/register", status_code=202)
async def register(request: Request, background: BackgroundTasks) -> JSONResponse:
    """§2.7.1 steps 1 and 2: the checks that look at no account, then always `202`."""
    if request.headers.get("authorization"):  # an agent's or a runner's credential
        raise ApiError(403, "forbidden", "only a person registers", {"reason": "humans_only"})
    origin = origin_of(request)
    require_secure_transport(origin, settings_of(request).allow_plain_http)
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise ApiError(403, "csrf_mismatch", "cross-site registration")
    engine = engine_of(request)
    hub = settings_of(request)
    hub_env = _environment(request)

    def mail_ready() -> bool:
        with engine.begin() as conn:
            return _resolved(conn, hub).mail_ready

    # Before the body is read: without mail nobody registers (§2.7.1 step 1). With mail
    # every mode reads it, `closed` included, and answers alike: whether an invitation
    # admits the address is decided after the answer, so the mode never shows in it.
    if not await run_in_threadpool(mail_ready):
        raise _closed()
    # Every request that reads a body counts for the breaker, whatever is refused after
    # it: an invalid body, the per-source limit (§2.7.3).
    tripped = registration.BREAKER.hit(hub_env.breaker)
    if tripped:
        raise rate_limited(tripped)
    body = _body(await request.body())
    wait = BY_SOURCE.hit(origin.address)
    if wait:
        raise rate_limited(wait)
    # Every accepted request costs one scrypt before it is answered (§2.7.1 step 2).
    hashed = await run_in_threadpool(passwords.hash_password, body.password)
    background.add_task(  # a sync task: Starlette runs it in the threadpool
        _store,
        engine,
        hub,
        body.address.strip(),
        hashed,
        origin.address,
        request.headers.get("user-agent"),
        request.headers.get("accept-language"),
        registration.safe_next(body.next),  # replaced by `/`, silently (§2.6.5)
    )
    return JSONResponse({"expires_in": int(registration.PENDING_FOR.total_seconds())}, 202)


def _store(
    engine: Engine,
    hub: Any,
    given: str,
    hashed: str,
    source: str,
    user_agent: str | None,
    language: str | None,
    next_path: str | None,
) -> None:
    """§2.7.1 step 3, after the answer: drop, mail the account's owner, or make a pending
    registration and mail its link."""
    normalized = registration.normalized(given)
    pair = f"{normalized}\x00{source}"
    over = BY_PAIR_SHORT.hit(pair) or BY_PAIR_DAY.hit(pair) or BY_ADDRESS_DAY.hit(normalized)
    address.prepare(engine, hub.secret_key)  # before the lock's transaction
    with engine.begin() as conn:
        now = clock.now()
        conn.execute(
            delete(t.pending_registration).where(t.pending_registration.c.expires_at <= now)
        )
        resolved = _resolved(conn, hub)
        # A filter that spares a mail; completion checks again (`registration_accounts`).
        if over or not registration_accounts.admitted(conn, resolved, given):
            registration.DROPPED.add()
            return
        blocked = conn.execute(
            select(t.registration_block.c.until).where(
                t.registration_block.c.address_normalized == normalized,
                t.registration_block.c.until > now,
            )
        ).first()
        if blocked is not None:  # a blocked address gets no mail at all
            registration.DROPPED.add()
            return
        if _has_account(conn, normalized):
            registration_mail.send(
                conn, kind="already_registered", to=given, language=language, hub=hub
            )
            return
        lock_address(conn, hub.secret_key, normalized)
        _void_earlier(conn, normalized, source, now)
        pending_id = new_id("pending_registration")
        terms = resolved.value("terms")
        conn.execute(
            insert(t.pending_registration).values(
                id=pending_id,
                address=given,
                address_normalized=normalized,
                password_hash=hashed,
                source_ip=source[:64],
                user_agent=(user_agent or "")[:512] or None,
                language=(language or "")[:35] or None,
                terms_version=terms["version"] if terms else None,
                next=next_path,
                created_at=now,
                expires_at=now + registration.PENDING_FOR,
            )
        )
        registration_mail.send(conn, kind="register_link", to=given, pending_id=pending_id, hub=hub)


def _has_account(conn: Connection, normalized: str) -> bool:
    """Whether the address is an account's verified address (§18.4)."""
    from maity_hub.notifications import preferences

    return preferences.has_verified_address(conn, normalized)


def lock_address(conn: Connection, secret_key: bytes | None, normalized: str) -> None:
    """Serialise what changes one address's pending registrations (§2.7.1): its row in
    `registration_lock`, made if absent, then locked until commit. Two requests for one
    address cannot both count four live ones and leave six, or both stay live from one
    source. The claim at completion takes the account address lock (§18.4) as well. The
    row holds the address's HMAC, never the address (`addresses.lock_key`)."""
    key = address.lock_key(conn, secret_key, normalized)
    try:
        with conn.begin_nested():
            conn.execute(insert(t.registration_lock).values(digest=key))
    except IntegrityError:
        pass  # it exists; lock it below
    conn.execute(
        select(t.registration_lock.c.digest)
        .where(t.registration_lock.c.digest == key)
        .with_for_update()
    )


def _void_earlier(conn: Connection, normalized: str, source: str, now: Any) -> None:
    """A new request from the same source voids its earlier unused one; at most five
    pending registrations per address, the oldest goes first (§2.7.1)."""
    live = (
        t.pending_registration.c.address_normalized == normalized,
        t.pending_registration.c.voided_at.is_(None),
        t.pending_registration.c.expires_at > now,
    )
    conn.execute(
        update(t.pending_registration)
        .where(*live, t.pending_registration.c.source_ip == source[:64])
        .values(voided_at=now)
    )
    rest = (
        conn.execute(
            select(t.pending_registration.c.id)
            .where(*live)
            .order_by(t.pending_registration.c.created_at, t.pending_registration.c.id)
        )
        .scalars()
        .all()
    )
    surplus = len(rest) - (registration.PENDING_PER_ADDRESS - 1)
    if surplus > 0:
        conn.execute(
            update(t.pending_registration)
            .where(t.pending_registration.c.id.in_(rest[:surplus]))
            .values(voided_at=now)
        )


# --- the instance admin's side (§16.4) ------------------------------------------------


def _require_admin(conn: Connection, caller: HumanCaller) -> None:
    if caller.principal_id != instance_admin_id(conn):
        raise forbidden("instance:admin")


@router.get("/admin/settings/registration")
def get_settings(request: Request, caller: HumanCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        _require_admin(conn, caller)
        return JSONResponse(registration.view(conn, _resolved(conn, settings_of(request))))


@router.patch("/admin/settings/registration")
def patch_settings(
    request: Request, caller: HumanCaller, body: Annotated[dict[str, Any], Body()]
) -> JSONResponse:
    with engine_of(request).begin() as conn:
        _require_admin(conn, caller)
        second_factor.require_step_up(conn, settings_of(request), caller)  # §2.8.4
        ready = registration.mail_ready(conn, settings_of(request))
        registration.patch(conn, _environment(request), ready, body, caller.principal_id)
        return JSONResponse(registration.view(conn, _resolved(conn, settings_of(request))))


@router.delete("/admin/registrations/blocks/{blocked}")
def lift_block(blocked: str, request: Request, caller: HumanCaller) -> Response:
    """Lift a block early; idempotent (§16.4)."""
    with engine_of(request).begin() as conn:
        _require_admin(conn, caller)
        conn.execute(
            delete(t.registration_block).where(
                t.registration_block.c.address_normalized == registration.normalized(blocked)
            )
        )
    return Response(status_code=204)


class RejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=registration_accounts.REASON_MAX)


@router.get("/admin/registrations")
def list_registrations(
    request: Request,
    caller: HumanCaller,
    limit: int = Query(default=PAGE_DEFAULT, ge=1, le=PAGE_MAX),
    cursor: str | None = None,
) -> JSONResponse:
    """The accounts that wait for approval, oldest first (§16.4)."""
    with engine_of(request).begin() as conn:
        _require_admin(conn, caller)
        registration_accounts.expire(conn)
        c = t.account_registration.c
        query = select(t.account_registration).where(c.status == "pending")
        if cursor is not None:
            after_at, after_id = paging.uncursor(cursor, "registrations")
            query = query.where(
                or_(c.created_at > after_at, and_(c.created_at == after_at, c.human_id > after_id))
            )
        rows = conn.execute(query.order_by(c.created_at, c.human_id).limit(limit + 1)).all()
        page = rows[:limit]
        next_cursor = (
            paging.cursor(page[-1].created_at, page[-1].human_id, "registrations")
            if len(rows) > limit
            else None
        )
        items = [registration_accounts.item(conn, row) for row in page]
        return JSONResponse({"items": items, "next_cursor": next_cursor})


def _decidable(conn: Connection, human_id: str) -> Any:
    """The pending account, locked; `not_found` for none, `invalid_transition` for one
    another instance admin decided meanwhile (§16.4)."""
    registration_accounts.expire(conn)
    row = registration_accounts.locked(conn, human_id)
    if row is None:
        raise not_found()
    if row.status != "pending":
        raise ApiError(
            409,
            "invalid_transition",
            f"the registration is {row.status} already",
            {"from": row.status, "to": "decided"},
        )
    return row


@router.post("/admin/registrations/{human_id}/approve")
def approve_registration(human_id: str, request: Request, caller: HumanCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        _require_admin(conn, caller)
        row = _decidable(conn, human_id)
        registration_accounts.approve(conn, row, caller.principal_id)
        return JSONResponse({**registration_accounts.item(conn, row), "account_status": "active"})


@router.post("/admin/registrations/{human_id}/reject")
def reject_registration(
    human_id: str, body: RejectIn, request: Request, caller: HumanCaller
) -> JSONResponse:
    if any(ord(c) < 32 and c not in "\n\t" or ord(c) == 127 for c in body.reason):
        raise invalid({"reason": "invalid"})
    with engine_of(request).begin() as conn:
        _require_admin(conn, caller)
        row = _decidable(conn, human_id)
        registration_accounts.remove(conn, row, "rejected", caller.principal_id, body.reason)
        return JSONResponse({"id": human_id, "status": "rejected"})
