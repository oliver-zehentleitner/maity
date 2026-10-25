"""Human login, logout, password change, the session and the session list (docs/api.md §2.1,
§2.6.5)."""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, insert, select, update
from starlette.concurrency import run_in_threadpool

from maity_hub import avatars, clock, ids
from maity_hub import tables as t
from maity_hub.auth import passwords, sessions
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


def _member(conn: Connection, human_id: str) -> dict[str, Any]:
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
    browser, system = sessions.describe(request.headers.get("user-agent"))

    def run() -> tuple[dict[str, Any], str, str]:
        with engine.begin() as conn:
            row = conn.execute(select(t.human).where(t.human.c.handle == body.handle)).first()
            stored = row.password_hash if row is not None else passwords.DUMMY_HASH
            if not passwords.verify_password(body.password, stored) or row is None:
                raise unauthenticated("handle or password is wrong")
            sessions.forget_expired_addresses(conn)
            now = clock.now()
            if presented:
                # A browser that holds a session, of any human, has it ended first; the
                # new one never takes over a presented id (§2.6.5, session fixation).
                sessions.end_where(
                    conn, t.human_session.c.id_hash == session_id_hash(presented), "logout"
                )
            session_id, csrf = secrets.token_urlsafe(32), secrets.token_hex(32)
            conn.execute(
                insert(t.human_session).values(
                    id_hash=session_id_hash(session_id),
                    human_id=row.id,
                    csrf_token=csrf,
                    created_at=now,
                    last_seen_at=now,
                    expires_at=now + SESSION_ABSOLUTE,
                    source=origin.address[:64],
                    public_id=ids.new_id("human_session"),
                    method="password",
                    browser=browser,
                    os=system,
                    ip=origin.address[:64],
                )
            )
            conn.execute(
                update(t.human)
                .where(t.human.c.id == row.id)
                .values(last_seen_at=now, last_login_at=now)
            )
            return (
                human_member(row, avatar_url=avatars.urls(conn, [row.id])[row.id]),
                session_id,
                csrf,
            )

    member, session_id, csrf = await run_in_threadpool(run)
    response = JSONResponse({"member": member, "next": sessions.safe_next(body.next)})
    _set_cookies(response, request, session_id, csrf)
    return response


@router.post("/logout")
def logout(request: Request, caller: HumanCaller) -> JSONResponse:
    _require_cookie(caller)
    with engine_of(request).begin() as conn:
        sessions.end_where(conn, t.human_session.c.id_hash == caller.human_session, "logout")
        member = _member(conn, caller.principal_id)
    response = JSONResponse({"member": member})
    _clear_cookies(response, request)
    return response


@router.post("/password")
def change_password(body: PasswordChange, request: Request, caller: HumanCaller) -> JSONResponse:
    _require_cookie(caller)
    if len(body.new) < passwords.MIN_LENGTH:
        raise invalid({"new": "too_short"}, "a password has at least 12 characters")
    address = origin_of(request).address
    with engine_of(request).begin() as conn:
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
        return JSONResponse(
            {
                "member": _member(conn, caller.principal_id),
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
            reason = sessions.refusal(mine, target, now)
            if reason is not None:
                raise sessions.forbidden_to_end(reason)
            by = "logout" if target.id_hash == current else "revoked"
            chain = sessions.approved_by_chain(conn, caller.principal_id, target.public_id)
            live = [s for s in chain if sessions.ended(s, now) is None]
            # The same refusal per session of the chain: what the caller may not end is
            # skipped and named, never ended (§2.6.5).
            allowed = [s for s in live if sessions.refusal(mine, s, now) is None]
            skipped = [s.public_id for s in live if s not in allowed]
            sessions.end(conn, [target], by)
            sessions.end(conn, allowed, "revoked")
        row = _session(conn, target.id_hash)
        answer = {**sessions.view(row, current, clock.now()), "skipped": skipped}
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
        allowed = [row for row in others if sessions.refusal(mine, row, now) is None]
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
    return {"items": [sessions.view(row, current, now) for row in rows]}


def _require_cookie(caller: Caller) -> str:
    if caller.human_session is None:
        raise unauthenticated("this endpoint needs a dashboard session")
    return caller.human_session
