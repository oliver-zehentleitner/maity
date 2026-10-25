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

from fastapi import APIRouter, BackgroundTasks, Body, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import Connection, Engine, delete, insert, select, update
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from maity_hub import clock, registration, registration_mail
from maity_hub import tables as t
from maity_hub.admin import instance_admin_id
from maity_hub.auth import passwords
from maity_hub.auth.caller import require_secure_transport
from maity_hub.deps import HumanCaller, engine_of, origin_of, settings_of
from maity_hub.errors import ApiError, forbidden, invalid, rate_limited
from maity_hub.ids import new_id
from maity_hub.mail import address
from maity_hub.ratelimit import Limiter

router = APIRouter()

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


def _safe_next(value: str | None) -> bool:
    """A path on this hub (§2.6.5): one slash, no scheme, no host, no backslash."""
    if value is None:
        return True
    return value.startswith("/") and not value.startswith("//") and "\\" not in value


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
    if not _safe_next(body.next):
        errors["next"] = "invalid"
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

    def mode_open() -> bool:
        with engine.begin() as conn:
            return _resolved(conn, hub).open

    # Before the body is read: a closed instance says nothing more (§2.7.1 step 1).
    if not await run_in_threadpool(mode_open):
        raise _closed()
    # Every request to an open instance counts for the breaker, whatever is refused
    # after it: an invalid body, the per-source limit (§2.7.3).
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
        body.next,
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
    with engine.begin() as conn:
        now = clock.now()
        conn.execute(
            delete(t.pending_registration).where(t.pending_registration.c.expires_at <= now)
        )
        resolved = _resolved(conn, hub)
        if over or not resolved.allows(given):
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
            registration_mail.send(conn, kind="already_registered", to=given)
            return
        lock_address(conn, normalized)
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
        registration_mail.send(conn, kind="register_link", to=given, pending_id=pending_id)


def _has_account(conn: Connection, normalized: str) -> bool:
    """Whether the address is an account's verified address (§18.4). Accounts carry no
    address until the notification settings store them (#280); then this looks there."""
    del conn, normalized
    return False


def lock_address(conn: Connection, normalized: str) -> None:
    """Serialise what changes one address's pending registrations (§2.7.1): its row in
    `registration_lock`, made if absent, then locked until commit. Two requests for one
    address cannot both count four live ones and leave six, or both stay live from one
    source. The claim at completion takes the account address lock (§18.4) as well."""
    try:
        with conn.begin_nested():
            conn.execute(insert(t.registration_lock).values(address_normalized=normalized))
    except IntegrityError:
        pass  # it exists; lock it below
    conn.execute(
        select(t.registration_lock.c.address_normalized)
        .where(t.registration_lock.c.address_normalized == normalized)
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
