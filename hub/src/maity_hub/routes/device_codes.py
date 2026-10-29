"""Device codes and the login page's methods (docs/api.md §2.6.1, §2.6.2, §2.6.4).

`/auth/device-codes/*` belong to the session that made the code: every other caller,
another session of the same human included, gets `not_found`. `/auth/device-login/*`
belong to the browser holding the pending cookie. No agent or runner credential makes,
redeems, approves or completes a code.
"""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from maity_hub import API_VERSION, clock, longpoll, moderation, paths, registration
from maity_hub.auth import device_codes, second_factor, sessions, sign_in_settings
from maity_hub.auth.caller import SESSION_COOKIE, Caller, require_secure_transport
from maity_hub.deps import AnyCaller, engine_of, origin_of, settings_of, wait_of
from maity_hub.errors import ApiError, forbidden, humans_only, not_found, rate_limited
from maity_hub.ratelimit import Limiter
from maity_hub.routes.auth import end_presented, member_of, pending_answer, set_session_cookies

router = APIRouter(prefix="/auth")

PENDING_COOKIE = "maity_pending"
PENDING_PATH = f"/api/{API_VERSION}/auth"
POLL = 0.25  # seconds between looks while a long-poll holds

# §2.6.4
CODES_BY_HUMAN = Limiter(5, 600)
REDEEM_BY_ADDRESS = Limiter(10, 60)
# Wrong codes across the instance; past 60 a minute every redemption is refused for a
# minute. A known denial of service, accepted so that a distributed guess cannot run;
# not to be "fixed" into a per-source limit (§2.6.4).
WRONG_CODES = Limiter(60, 60)
BREAKER_SECONDS = 60
_breaker = {"until": 0.0}  # monotonic time until which every redemption is refused

# The one long-poll per session or pending cookie; a newer one supersedes it.
_holding: dict[str, object] = {}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Pick(Strict):
    number: int = Field(ge=10, le=99)


class Redeem(Strict):
    code: str = Field(min_length=1, max_length=32)
    next: str | None = None  # an unsafe value, of any length, becomes `/` (§2.6.5)


def _creator(caller: Caller) -> str:
    """The cookie session of a human: the only kind of caller that makes a code."""
    if caller.kind != "human":
        raise humans_only("device codes are for humans")
    if caller.human_session is None:
        raise forbidden(message="device codes need a dashboard session")
    return caller.human_session


def _anonymous(request: Request) -> None:
    """The new device's calls: no credential, TLS (§2.5), and no other site may start or
    finish a sign-in in a visitor's browser (§2.6.5)."""
    if request.headers.get("authorization"):
        raise humans_only("a device code signs in a browser, never a credential")
    require_secure_transport(origin_of(request), settings_of(request).allow_plain_http)
    if request.headers.get("sec-fetch-site") in ("cross-site", "same-site"):
        raise forbidden(message="a sign-in from another site")


def _require_enabled(request: Request) -> None:
    with engine_of(request).begin() as conn:
        if not sign_in_settings.device_code_enabled(conn, settings_of(request)):
            raise ApiError(
                403, "forbidden", "device codes are switched off", {"reason": "method_disabled"}
            )


async def _hold(read: Callable[[], dict[str, Any]], wait: int, key: str) -> dict[str, Any]:
    """Answer at once, or with `wait` hold until the status changes (§8.3)."""
    first = await run_in_threadpool(read)
    if wait == 0 or first["status"] in ("used", "denied", "expired"):
        return first
    token = object()
    _holding[key] = token
    deadline = time.monotonic() + wait
    current = first
    try:
        # A stopping hub answers with what it has; the client simply waits again (§8.3).
        while time.monotonic() < deadline and not longpoll.stopping.is_set():
            await asyncio.sleep(POLL)
            if _holding.get(key) is not token:
                return {**current, "superseded": True}
            current = await run_in_threadpool(read)
            if current["status"] != first["status"]:
                break
        return current
    finally:
        if _holding.get(key) is token:
            del _holding[key]


# --- the signed-in device (A) --------------------------------------------------------


@router.post("/device-codes")
def create_code(request: Request, caller: AnyCaller) -> JSONResponse:
    session_hash = _creator(caller)
    _require_enabled(request)
    wait = CODES_BY_HUMAN.hit(caller.principal_id)
    if wait:
        raise rate_limited(wait)
    with engine_of(request).begin() as conn:
        row, code = device_codes.create(conn, caller.principal_id, session_hash)
    public = settings_of(request).public_url
    return JSONResponse(
        {
            "id": row.id,
            "code": "-".join(code[i : i + 4] for i in range(0, len(code), 4)),
            # In the fragment, which no request carries: no log, proxy or Referer sees it.
            "url": f"{public}/sign-in/code#c={code}",
            "expires_at": clock.rfc3339(row.expires_at),
        },
        status_code=201,
    )


@router.get("/device-codes/{code_id}")
async def get_code(code_id: str, request: Request, caller: AnyCaller) -> JSONResponse:
    session_hash = _creator(caller)
    _require_enabled(request)
    wait = wait_of(request)
    engine = engine_of(request)

    def read() -> dict[str, Any]:
        with engine.begin() as conn:
            row = device_codes.of_creator(conn, code_id, session_hash)
            if row is None:
                raise not_found()
            return device_codes.creator_view(row, clock.now())

    return JSONResponse(await _hold(read, wait, f"code:{session_hash}"))


@router.post("/device-codes/{code_id}/approve")
def approve_code(code_id: str, body: Pick, request: Request, caller: AnyCaller) -> JSONResponse:
    session_hash = _creator(caller)
    _require_enabled(request)
    with engine_of(request).begin() as conn:
        row = device_codes.of_creator(conn, code_id, session_hash, lock=True)
        if row is None:
            raise not_found()
        if device_codes.status(row, clock.now()) != "redeemed":
            raise ApiError(409, "conflict", "the code is not waiting for an approval")
        second_factor.require_step_up(conn, settings_of(request), caller)  # §2.8.4
        right = device_codes.approve(conn, row, body.number)
    if not right:
        raise device_codes.code_invalid()  # the wrong pick denied it (number matching)
    return _creator_answer(request, code_id, session_hash)


@router.post("/device-codes/{code_id}/deny")
def deny_code(code_id: str, request: Request, caller: AnyCaller) -> JSONResponse:
    return _deny(request, caller, code_id)


@router.delete("/device-codes/{code_id}")
def cancel_code(code_id: str, request: Request, caller: AnyCaller) -> JSONResponse:
    return _deny(request, caller, code_id)


def _deny(request: Request, caller: Caller, code_id: str) -> JSONResponse:
    session_hash = _creator(caller)
    _require_enabled(request)
    with engine_of(request).begin() as conn:
        row = device_codes.of_creator(conn, code_id, session_hash, lock=True)
        if row is None:
            raise not_found()
        if device_codes.status(row, clock.now()) in ("waiting", "redeemed"):
            device_codes.deny(conn, row)
    return _creator_answer(request, code_id, session_hash)


def _creator_answer(request: Request, code_id: str, session_hash: str) -> JSONResponse:
    with engine_of(request).begin() as conn:
        row = device_codes.of_creator(conn, code_id, session_hash)
        return JSONResponse(device_codes.creator_view(row, clock.now()))


# --- the new device (B) --------------------------------------------------------------


@router.post("/device-login")
def redeem_code(body: Redeem, request: Request) -> JSONResponse:
    _anonymous(request)
    _require_enabled(request)
    origin = origin_of(request)
    tripped = _breaker["until"] - time.monotonic()
    if tripped > 0:
        raise rate_limited(max(1, int(tripped + 0.999)))
    wait = REDEEM_BY_ADDRESS.hit(origin.address)
    if wait:
        raise rate_limited(wait)
    with engine_of(request).begin() as conn:
        redeemed = device_codes.redeem(
            conn,
            body.code,
            address=origin.address,
            user_agent=request.headers.get("user-agent"),
            device_cookie=request.cookies.get(sessions.DEVICE_COOKIE),
            next_route=paths.safe_next(body.next),
        )
    if redeemed is None:
        WRONG_CODES.hit("instance")
        if WRONG_CODES.blocked("instance"):
            # 60 wrong codes within a minute: every redemption is refused for a minute.
            _breaker["until"] = time.monotonic() + BREAKER_SECONDS
        raise device_codes.code_invalid()
    row, pending = redeemed
    response = JSONResponse(
        {
            "status": "redeemed",
            "expires_at": clock.rfc3339(row.expires_at),
            "match_number": row.match_number,
        }
    )
    response.set_cookie(
        PENDING_COOKIE,
        pending,
        max_age=int(device_codes.LIFETIME.total_seconds()),
        path=PENDING_PATH,
        secure=origin.tls,
        httponly=True,
        samesite="strict",
    )
    return response


@router.get("/device-login")
async def watch_redemption(request: Request) -> JSONResponse:
    _anonymous(request)
    _require_enabled(request)
    wait = wait_of(request)
    pending = request.cookies.get(PENDING_COOKIE)
    engine = engine_of(request)

    def read() -> dict[str, Any]:
        with engine.begin() as conn:
            row = device_codes.of_pending(conn, pending)
            if row is None:
                raise not_found()
            return device_codes.pending_view(conn, row, clock.now())

    key = f"pending:{device_codes.digest(pending or secrets.token_hex(8))}"
    return JSONResponse(await _hold(read, wait, key))


@router.post("/device-login/complete")
def complete_redemption(request: Request) -> JSONResponse:
    _anonymous(request)
    _require_enabled(request)
    origin = origin_of(request)
    pending = request.cookies.get(PENDING_COOKIE)
    with engine_of(request).begin() as conn:
        # A suspended account first (§16.8), before the state, and before the code's row
        # lock: the suspension holds the account lock when it denies the open codes.
        seen = device_codes.of_pending(conn, pending)
        if seen is not None:
            moderation.refuse_suspended(conn, seen.human_id)
        row = device_codes.of_pending(conn, pending, lock=True)
        if row is None:
            raise not_found()
        if device_codes.status(row, clock.now()) != "approved":
            raise ApiError(409, "conflict", "the code is not approved")
        end_presented(conn, request.cookies.get(SESSION_COOKIE))
        user_agent = request.headers.get("user-agent")
        session_id, csrf, _, state = device_codes.complete(
            conn, row, address=origin.address, user_agent=user_agent, hub=settings_of(request)
        )
        device = None
        if state == "full":
            device = sessions.remember_device(
                conn, row.human_id, request.cookies.get(sessions.DEVICE_COOKIE)
            )
            answer: dict[str, Any] = {
                "member": member_of(conn, row.human_id),
                "next": row.next or "/",
            }
        else:
            answer = pending_answer(state)  # the second step is owed (§2.8.2)
    response = JSONResponse(answer)
    set_session_cookies(response, request, session_id, csrf, device)
    response.delete_cookie(
        PENDING_COOKIE, path=PENDING_PATH, secure=origin.tls, httponly=True, samesite="strict"
    )
    return response


# --- the login page --------------------------------------------------------------------


@router.get("/methods")
def methods(request: Request) -> JSONResponse:
    """What the login page may show (§2.6.1); nothing about any account. `registration`
    is the mode in effect (§2.7: `allowlist` with an entry or `open`, with complete, enabled
    mail, which `effective_mode` already folds in), never the entries of the lists; `terms` the
    instance's or `null`."""
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        device_code = sign_in_settings.device_code_enabled(conn, hub)
        email_link = sign_in_settings.view(conn, hub)["email_link_available"]
        env = hub.registration or registration.RegistrationEnvironment()
        resolved = registration.resolve(conn, env, registration.mail_ready(conn, hub))
    terms = resolved.value("terms")
    return JSONResponse(
        {
            "password": True,
            "device_code": device_code,
            "email_link": email_link,
            # An allowlist with both lists empty admits nobody: no way in is shown (§2.7).
            "registration": resolved.effective_mode in ("allowlist", "open")
            and "allowlist" not in resolved.missing,
            "terms": terms if isinstance(terms, dict) else None,
        }
    )
