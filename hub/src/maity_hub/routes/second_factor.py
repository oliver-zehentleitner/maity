"""A human's second factor (docs/api.md §2.8): the state, the enrolment, recovery codes,
turning it off, and the verify that completes a sign-in or gives a step-up."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.auth import mail_factor, second_factor, sessions
from maity_hub.deps import HumanCaller, engine_of, settings_of
from maity_hub.errors import ApiError, rate_limited, unauthenticated
from maity_hub.routes.auth import member_of, set_session_cookies

router = APIRouter(prefix="/auth")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Confirm(Strict):
    code: str = Field(min_length=1, max_length=32)


class Verify(Strict):
    code: str | None = Field(default=None, min_length=1, max_length=32)
    recovery_code: str | None = Field(default=None, min_length=1, max_length=32)
    email_code: str | None = Field(default=None, min_length=1, max_length=16)
    email_token: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def one_of(self) -> Verify:
        given = [v for v in (self.code, self.recovery_code, self.email_code, self.email_token) if v]
        if len(given) != 1:
            raise ValueError("give one of code, recovery_code, email_code or email_token")
        return self


def _session(caller: Any) -> str:
    if caller.human_session is None:
        raise unauthenticated("this endpoint needs a dashboard session")
    return str(caller.human_session)


def _issuer(request: Request) -> str:
    """The instance's public host names the account in the app, else `Maity` (§2.8.1)."""
    host = urlsplit(settings_of(request).public_url or "").hostname
    return host or "Maity"


@router.get("/second-factor")
def state(request: Request, caller: HumanCaller) -> JSONResponse:
    _session(caller)
    with engine_of(request).begin() as conn:
        return JSONResponse(second_factor.view(conn, settings_of(request), caller.principal_id))


@router.post("/second-factor/totp")
def start(request: Request, caller: HumanCaller) -> JSONResponse:
    _session(caller)
    with engine_of(request).begin() as conn:
        answer = second_factor.start(conn, settings_of(request), caller, _issuer(request))
    return JSONResponse(answer)


@router.post("/second-factor/totp/confirm")
def confirm(body: Confirm, request: Request, caller: HumanCaller) -> JSONResponse:
    _session(caller)
    with engine_of(request).begin() as conn:
        result = second_factor.confirm(conn, settings_of(request), caller, body.code)
        completion = result["completion"]
        device = None
        if completion is not None:
            # An enrolment session's sign-in completes here (§2.8.5).
            device = sessions.remember_device(
                conn, caller.principal_id, request.cookies.get(sessions.DEVICE_COOKIE)
            )
    response = JSONResponse({"recovery_codes": result["recovery_codes"]})
    if completion is not None:
        set_session_cookies(response, request, completion[0], completion[1], device)
    return response


@router.post("/second-factor/recovery-codes")
def new_recovery_codes(request: Request, caller: HumanCaller) -> JSONResponse:
    _session(caller)
    with engine_of(request).begin() as conn:
        codes = second_factor.regenerate(conn, settings_of(request), caller)
    return JSONResponse({"recovery_codes": codes})


@router.delete("/second-factor")
def turn_off(request: Request, caller: HumanCaller) -> JSONResponse:
    _session(caller)
    with engine_of(request).begin() as conn:
        second_factor.disable(conn, settings_of(request), caller)
        return JSONResponse(second_factor.view(conn, settings_of(request), caller.principal_id))


@router.post("/second-factor/verify")
def verify(body: Verify, request: Request, caller: HumanCaller) -> JSONResponse:
    current = _session(caller)
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        row = conn.execute(
            select(t.human_session).where(t.human_session.c.id_hash == current)
        ).one()
        result = second_factor.verify(
            conn,
            hub,
            caller,
            code=body.code,
            recovery_code=body.recovery_code,
            email_code=body.email_code,
            email_token=body.email_token,
        )
        if isinstance(result, tuple):
            member = member_of(conn, row.human_id)
            next_route = row.next or "/"
            device = sessions.remember_device(
                conn, row.human_id, request.cookies.get(sessions.DEVICE_COOKIE)
            )
    if result is None:
        raise second_factor.code_invalid()
    if not isinstance(result, tuple):
        return JSONResponse({"valid_until": clock.rfc3339(result)})
    response = JSONResponse({"member": member, "next": next_route})
    set_session_cookies(response, request, result[0], result[1], device)
    return response


@router.post("/second-factor/email")
def send_mail_factor(request: Request, caller: HumanCaller) -> JSONResponse:
    """A new mail of the mail factor (§2.8.8): from a second-factor session `via: email` a link
    and a code, from a full session of a human without TOTP, under `email`, a code only for the
    step-up. A new mail voids the earlier link and code."""
    current = _session(caller)
    hub = settings_of(request)
    unavailable: ApiError | None = None
    with engine_of(request).begin() as conn:
        row = conn.execute(
            select(t.human_session).where(t.human_session.c.id_hash == current)
        ).one()
        if second_factor.policy(conn, hub) != "email" or (
            second_factor.via(conn, hub, row.human_id) != mail_factor.VIA
        ):
            raise second_factor.refused("method_disabled", "the mail is not the second factor")
        step = row.state == "second_factor"
        try:
            outcome = mail_factor.send(conn, hub, row, with_link=step)
        except ApiError as refused:
            if refused.code != "address_unverified":
                raise
            unavailable = refused
            if mail_factor.ever_had_address(conn, row.human_id):
                second_factor.failed(
                    conn, row.human_id, mail_factor.UNAVAILABLE, row.ip, row.browser, row.os
                )
    if unavailable is not None:
        raise unavailable  # after the commit: the account record stays
    if outcome == "rate_limited":
        raise rate_limited(max(int(mail_factor.BY_HUMAN.blocked(row.human_id)), 60))
    return JSONResponse({"mail": "sent"})
