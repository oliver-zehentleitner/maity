"""Human login, logout, password change and session (docs/api.md §2.1)."""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, insert, select, update
from starlette.concurrency import run_in_threadpool

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.auth import passwords
from maity_hub.auth.caller import (
    CSRF_COOKIE,
    SESSION_ABSOLUTE,
    SESSION_COOKIE,
    Caller,
    session_expires_at,
    session_id_hash,
)
from maity_hub.deps import HumanCaller, engine_of, origin_of, settings_of
from maity_hub.errors import ApiError, invalid, rate_limited, unauthenticated
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


class PasswordChange(Strict):
    current: str = Field(min_length=1, max_length=1024)
    new: str = Field(min_length=1, max_length=1024)


def _set_cookies(response: JSONResponse, request: Request, session_id: str, csrf: str) -> None:
    secure = not settings_of(request).allow_plain_http
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
    secure = not settings_of(request).allow_plain_http
    for name, httponly in ((SESSION_COOKIE, True), (CSRF_COOKIE, False)):
        response.delete_cookie(name, path="/", secure=secure, httponly=httponly, samesite="lax")


def _member(conn: Connection, human_id: str) -> dict[str, Any]:
    row = conn.execute(select(t.human).where(t.human.c.id == human_id)).one()
    return human_member(row)


@router.post("/login")
async def login(body: Login, request: Request) -> JSONResponse:
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise ApiError(403, "csrf_mismatch", "cross-site login")
    origin = origin_of(request)
    for limiter, key in ((LOGIN_BY_ADDRESS, origin.address), (LOGIN_BY_HANDLE, body.handle)):
        wait = limiter.hit(key)
        if wait:
            raise rate_limited(wait)
    engine = engine_of(request)

    def run() -> tuple[dict[str, Any], str, str]:
        with engine.begin() as conn:
            row = conn.execute(select(t.human).where(t.human.c.handle == body.handle)).first()
            stored = row.password_hash if row is not None else passwords.DUMMY_HASH
            if not passwords.verify_password(body.password, stored) or row is None:
                raise unauthenticated("handle or password is wrong")
            now = clock.now()
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
                )
            )
            conn.execute(update(t.human).where(t.human.c.id == row.id).values(last_seen_at=now))
            return human_member(row), session_id, csrf

    member, session_id, csrf = await run_in_threadpool(run)
    response = JSONResponse({"member": member})
    _set_cookies(response, request, session_id, csrf)
    return response


@router.post("/logout")
def logout(request: Request, caller: HumanCaller) -> JSONResponse:
    _require_cookie(caller)
    with engine_of(request).begin() as conn:
        conn.execute(
            update(t.human_session)
            .where(t.human_session.c.id_hash == caller.human_session)
            .values(ended_at=clock.now())
        )
        member = _member(conn, caller.principal_id)
    response = JSONResponse({"member": member})
    _clear_cookies(response, request)
    return response


@router.post("/password")
def change_password(body: PasswordChange, request: Request, caller: HumanCaller) -> JSONResponse:
    _require_cookie(caller)
    with engine_of(request).begin() as conn:
        row = conn.execute(select(t.human).where(t.human.c.id == caller.principal_id)).one()
        if not passwords.verify_password(body.current, row.password_hash):
            raise invalid({"current": "mismatch"}, "the current password is wrong")
        conn.execute(
            update(t.human)
            .where(t.human.c.id == row.id)
            .values(password_hash=passwords.hash_password(body.new))
        )
        conn.execute(
            update(t.human_session)
            .where(
                t.human_session.c.human_id == row.id,
                t.human_session.c.id_hash != caller.human_session,
                t.human_session.c.ended_at.is_(None),
            )
            .values(ended_at=clock.now())
        )
        return JSONResponse({"member": human_member(row)})


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
            }
        )


def _require_cookie(caller: Caller) -> None:
    if caller.human_session is None:
        raise unauthenticated("this endpoint needs a dashboard session")
