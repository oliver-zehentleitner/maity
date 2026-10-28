"""Human login, logout, password change, the session and the session list (docs/api.md §2.1,
§2.6.5)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, select, update
from starlette.concurrency import run_in_threadpool

from maity_hub import avatars, clock
from maity_hub import tables as t
from maity_hub.auth import passwords, second_factor, sessions
from maity_hub.auth.caller import (
    CSRF_COOKIE,
    SESSION_ABSOLUTE,
    SESSION_COOKIE,
    Caller,
    require_secure_transport,
    session_expires_at,
    session_id_hash,
)
from maity_hub.deps import AnyCaller, HumanCaller, engine_of, origin_of, settings_of
from maity_hub.errors import (
    ApiError,
    forbidden,
    humans_only,
    invalid,
    not_found,
    rate_limited,
    unauthenticated,
)
from maity_hub.notifications import records
from maity_hub.ratelimit import Limiter
from maity_hub.views import human_member

router = APIRouter(prefix="/auth")

LOGIN_BY_ADDRESS = Limiter(10, 60)
LOGIN_BY_HANDLE = Limiter(10, 60)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Strict):
    handle: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)
    # Where the dashboard goes afterwards; an unsafe value, of any length, becomes `/`
    # silently (§2.6.5).
    next: str | None = None


class PasswordChange(Strict):
    current: str = Field(min_length=1, max_length=1024)
    new: str = Field(min_length=1, max_length=1024)


def _set_cookies(response: JSONResponse, request: Request, session_id: str, csrf: str) -> None:
    # Secure follows the scheme the request actually arrived with (§2.5).
    secure = origin_of(request).tls
    max_age = int(SESSION_ABSOLUTE.total_seconds())
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        max_age=max_age,
        path="/",
        secure=secure,
        httponly=True,
        samesite="lax",
    )
    response.set_cookie(
        CSRF_COOKIE, csrf, max_age=max_age, path="/", secure=secure, httponly=False, samesite="lax"
    )


def _clear_cookies(response: JSONResponse, request: Request) -> None:
    secure = origin_of(request).tls
    for name, httponly in ((SESSION_COOKIE, True), (CSRF_COOKIE, False)):
        response.delete_cookie(name, path="/", secure=secure, httponly=httponly, samesite="lax")


def member_of(conn: Connection, human_id: str) -> dict[str, Any]:
    row = conn.execute(select(t.human).where(t.human.c.id == human_id)).one()
    return human_member(row, avatar_url=avatars.urls(conn, [row.id])[row.id])


@router.post("/login")
async def login(body: Login, request: Request) -> JSONResponse:
    if request.headers.get("authorization"):
        raise forbidden(message="this endpoint is for humans")
    origin = origin_of(request)
    require_secure_transport(origin, settings_of(request).allow_plain_http)
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise ApiError(403, "csrf_mismatch", "cross-site login")
    for limiter, key in ((LOGIN_BY_ADDRESS, origin.address), (LOGIN_BY_HANDLE, body.handle)):
        wait = limiter.hit(key)
        if wait:
            raise rate_limited(wait)
    engine = engine_of(request)
    presented = request.cookies.get(SESSION_COOKIE)
    device = request.cookies.get(sessions.DEVICE_COOKIE)
    user_agent = request.headers.get("user-agent")

    hub = settings_of(request)
    next_route = sessions.safe_next(body.next)

    def run() -> tuple[dict[str, Any], str, str, str | None]:
        with engine.begin() as conn:
            row = conn.execute(select(t.human).where(t.human.c.handle == body.handle)).first()
            stored = row.password_hash if row is not None else passwords.DUMMY_HASH
            if not passwords.verify_password(body.password, stored) or row is None:
                raise unauthenticated("handle or password is wrong")
            sessions.forget_expired_addresses(conn)
            end_presented(conn, presented)
            session_id, csrf, _, state = second_factor.begin(
                conn,
                hub,
                row.id,
                method="password",
                address=origin.address,
                user_agent=user_agent,
                next_route=next_route,
            )
            if state != "full":
                # The sign-in is not complete: no member, no device cookie yet (§2.8.2).
                return pending_answer(state), session_id, csrf, None
            return (
                {
                    "member": human_member(row, avatar_url=avatars.urls(conn, [row.id])[row.id]),
                    "next": next_route,
                },
                session_id,
                csrf,
                sessions.remember_device(conn, row.id, device),
            )

    answer, session_id, csrf, device_value = await run_in_threadpool(run)
    response = JSONResponse(answer)
    set_session_cookies(response, request, session_id, csrf, device_value)
    return response


def pending_answer(state: str) -> dict[str, Any]:
    """What a first factor answers when a step is still owed (§2.8.2, §2.8.5)."""
    if state == "second_factor":
        return {
            "second_factor": "required",
            "expires_in": int(second_factor.SECOND_STEP.total_seconds()),
        }
    return {"second_factor": "enrolment_required"}


def end_presented(conn: Connection, presented: str | None) -> None:
    """A browser that holds a session, of any human, has it ended before a new one is
    made; the new one never takes over a presented id (§2.6.5, session fixation)."""
    if presented:
        sessions.end_where(conn, t.human_session.c.id_hash == session_id_hash(presented), "logout")


def set_session_cookies(
    response: JSONResponse, request: Request, session_id: str, csrf: str, device: str | None
) -> None:
    """The cookies of a completed sign-in: the session's, and the device cookie when this
    browser held no value of the human yet (§2.6.5)."""
    _set_cookies(response, request, session_id, csrf)
    if device is not None:
        response.set_cookie(
            sessions.DEVICE_COOKIE,
            device,
            max_age=int(sessions.DEVICE_LIFETIME.total_seconds()),
            path="/",
            secure=origin_of(request).tls,
            httponly=True,
            samesite="lax",
        )


@router.post("/logout")
def logout(request: Request, caller: HumanCaller) -> JSONResponse:
    _require_cookie(caller)
    with engine_of(request).begin() as conn:
        complete = conn.execute(
            select(t.human_session.c.sign_in_complete).where(
                t.human_session.c.id_hash == caller.human_session
            )
        ).scalar_one()
        sessions.end_where(conn, t.human_session.c.id_hash == caller.human_session, "logout")
        # No member before the sign-in counts (§2.8.2).
        answer = {"member": member_of(conn, caller.principal_id)} if complete else {}
    response = JSONResponse(answer)
    _clear_cookies(response, request)
    return response


@router.post("/password")
def change_password(body: PasswordChange, request: Request, caller: HumanCaller) -> JSONResponse:
    _require_cookie(caller)
    if len(body.new) < passwords.MIN_LENGTH:
        raise invalid({"new": "too_short"}, "a password has at least 12 characters")
    address = origin_of(request).address
    with engine_of(request).begin() as conn:
        second_factor.require_step_up(conn, settings_of(request), caller)  # §2.8.4
        row = conn.execute(select(t.human).where(t.human.c.id == caller.principal_id)).one()
        # A wrong current password counts against the login limit (§2.1).
        limits = ((LOGIN_BY_ADDRESS, address), (LOGIN_BY_HANDLE, row.handle))
        for limiter, key in limits:
            wait = limiter.blocked(key)
            if wait:
                raise rate_limited(wait)
        if not passwords.verify_password(body.current, row.password_hash):
            for limiter, key in limits:
                limiter.hit(key)
            raise invalid({"current": "mismatch"}, "the current password is wrong")
        conn.execute(
            update(t.human)
            .where(t.human.c.id == row.id)
            .values(password_hash=passwords.hash_password(body.new))
        )
        sessions.end_where(
            conn,
            (t.human_session.c.human_id == row.id)
            & (t.human_session.c.id_hash != caller.human_session),
            "password_change",
        )
        url = avatars.urls(conn, [row.id])[row.id]
        return JSONResponse({"member": human_member(row, avatar_url=url)})


@router.get("/session")
def session(request: Request, caller: HumanCaller) -> JSONResponse:
    _require_cookie(caller)
    with engine_of(request).begin() as conn:
        row = conn.execute(
            select(t.human_session).where(t.human_session.c.id_hash == caller.human_session)
        ).one()
        owed = second_factor.session_view(conn, settings_of(request), row)
        if owed is not None:
            return JSONResponse(owed)  # no member before the step is done (§2.8.2)
        return JSONResponse(
            {
                "member": member_of(conn, caller.principal_id),
                "csrf_token": row.csrf_token,
                "expires_at": clock.rfc3339(session_expires_at(row)),
                "session_id": row.public_id,
                # The dashboard offers "join link via <join host>" only when one is set.
                "join_url": settings_of(request).join_url,
            }
        )


@router.get("/sessions")
def list_sessions(
    request: Request, caller: AnyCaller, ended: bool = Query(default=False)
) -> JSONResponse:
    current = _session_caller(caller)
    with engine_of(request).begin() as conn:
        return JSONResponse(_listing(conn, caller.principal_id, current, with_ended=ended))


@router.delete("/sessions/{public_id}")
def end_session(public_id: str, request: Request, caller: AnyCaller) -> JSONResponse:
    """Ends one of the caller's sessions, with every session it approved by device code;
    the current one is a logout. Idempotent: an ended session answers as it is."""
    current = _session_caller(caller)
    now = clock.now()
    with engine_of(request).begin() as conn:
        mine = _session(conn, current)
        confirmed = sessions.confirmed_sessions(conn, caller.principal_id)
        target = conn.execute(
            select(t.human_session).where(
                t.human_session.c.public_id == public_id,
                t.human_session.c.human_id == caller.principal_id,
            )
        ).first()
        if target is None:
            raise not_found()  # another human's session is not found either
        skipped: list[str] = []
        if sessions.ended(target, now) is None:
            reason = sessions.refusal(mine, target, now, confirmed)
            if reason is not None:
                raise sessions.forbidden_to_end(reason)
            by = "logout" if target.id_hash == current else "revoked"
            chain = sessions.approved_by_chain(conn, caller.principal_id, target.public_id)
            live = [s for s in chain if sessions.ended(s, now) is None]
            # The same refusal per session of the chain: what the caller may not end is
            # skipped and named, never ended (§2.6.5).
            allowed = [s for s in live if sessions.refusal(mine, s, now, confirmed) is None]
            skipped = [s.public_id for s in live if s not in allowed]
            sessions.end(conn, [target], by)
            sessions.end(conn, allowed, "revoked")
        row = _session(conn, target.id_hash)
        sign_ins = records.sign_in_records(conn, caller.principal_id)
        answer = {
            **sessions.view(row, current, clock.now(), sign_ins, confirmed),
            "skipped": skipped,
        }
    response = JSONResponse(answer)
    if target.id_hash == current:
        _clear_cookies(response, request)
    return response


@router.post("/sessions/end-others")
def end_others(request: Request, caller: AnyCaller) -> JSONResponse:
    """Every live session of the caller but the current one; from a session not in good
    standing only the others that are not in good standing either (§2.6.5)."""
    current = _session_caller(caller)
    now = clock.now()
    with engine_of(request).begin() as conn:
        mine = _session(conn, current)
        live = sessions.listing(conn, caller.principal_id, current, with_ended=False)
        others = [row for row in live if row.id_hash != current]
        confirmed = sessions.confirmed_sessions(conn, caller.principal_id)
        allowed = [row for row in others if sessions.refusal(mine, row, now, confirmed) is None]
        sessions.end(conn, allowed, "end_others")
        return JSONResponse(_listing(conn, caller.principal_id, current, with_ended=False))


def _session_caller(caller: Caller) -> str:
    """The session list is a human's alone: no agent or runner credential lists or ends
    a session, whatever it holds (§2.6.5)."""
    if caller.kind != "human":
        raise humans_only("the session list is for humans")
    return _require_cookie(caller)


def _session(conn: Connection, id_hash: str) -> Any:
    return conn.execute(select(t.human_session).where(t.human_session.c.id_hash == id_hash)).one()


def _listing(conn: Connection, human_id: str, current: str, *, with_ended: bool) -> dict[str, Any]:
    now = clock.now()
    rows = sessions.listing(conn, human_id, current, with_ended=with_ended)
    sign_ins = records.sign_in_records(conn, human_id)
    confirmed = sessions.confirmed_sessions(conn, human_id)
    return {"items": [sessions.view(row, current, now, sign_ins, confirmed) for row in rows]}


def _require_cookie(caller: Caller) -> str:
    if caller.human_session is None:
        raise unauthenticated("this endpoint needs a dashboard session")
    return caller.human_session


class Reauthenticate(Strict):
    password: str = Field(min_length=1, max_length=1024)


@router.post("/reauthenticate")
def reauthenticate(body: Reauthenticate, request: Request, caller: HumanCaller) -> JSONResponse:
    """The password given again on this session: the proof of §2.8.1 for ten minutes.
    A wrong one counts against the login limit (§2.1)."""
    _require_cookie(caller)
    address = origin_of(request).address
    with engine_of(request).begin() as conn:
        handle = conn.execute(
            select(t.human.c.handle).where(t.human.c.id == caller.principal_id)
        ).scalar_one()
        limits = ((LOGIN_BY_ADDRESS, address), (LOGIN_BY_HANDLE, handle))
        for limiter, key in limits:
            wait = limiter.blocked(key)
            if wait:
                raise rate_limited(wait)
        try:
            until = second_factor.reauthenticate(conn, caller, body.password)
        except ApiError:
            for limiter, key in limits:
                limiter.hit(key)
            raise
    return JSONResponse({"valid_until": clock.rfc3339(until)})
