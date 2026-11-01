"""`/me/notification-settings` (docs/api.md §18.4).

The settings are a human's own: an agent credential is `forbidden` with `humans_only`.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, select

from maity_hub import tables as t
from maity_hub.auth import second_factor
from maity_hub.auth.caller import Caller
from maity_hub.db import retrying
from maity_hub.deps import AnyCaller, engine_of, origin_of, settings_of
from maity_hub.errors import forbidden, humans_only, invalid, not_found
from maity_hub.mail import address as addresses
from maity_hub.mail import settings as mail_settings
from maity_hub.notifications import preferences
from maity_hub.routes.auth import LOGIN_BY_ADDRESS, LOGIN_BY_HANDLE

router = APIRouter()


def _human(caller: Caller) -> str:
    """The session hash of the dashboard session that calls."""
    if caller.kind == "agent":
        raise humans_only("notification settings are a human's own")
    if caller.kind != "human" or caller.human_session is None:
        raise forbidden(message="notification settings need a dashboard session")
    return caller.human_session


def _context(conn: Connection, caller: Caller, session_hash: str) -> tuple[Any, Any]:
    human = conn.execute(select(t.human).where(t.human.c.id == caller.principal_id)).one()
    session = conn.execute(
        select(t.human_session).where(t.human_session.c.id_hash == session_hash)
    ).one()
    return human, session


def _mail_ready(conn: Connection, request: Request) -> bool:
    hub = settings_of(request)
    return mail_settings.resolve(conn, hub.mail, hub.secret_key).complete


@router.get("/me/notification-settings")
def get_settings(request: Request, caller: AnyCaller) -> JSONResponse:
    _human(caller)
    with engine_of(request).begin() as conn:
        return JSONResponse(preferences.view(conn, caller.principal_id, _mail_ready(conn, request)))


@router.patch("/me/notification-settings")
def patch_settings(
    request: Request, caller: AnyCaller, body: Annotated[dict[str, Any], Body()]
) -> JSONResponse:
    session_hash = _human(caller)
    hub = settings_of(request)
    address = origin_of(request).address

    def run() -> tuple[dict[str, Any], int]:
        with engine_of(request).begin() as conn:
            human, session = _context(conn, caller, session_hash)

            def wrong_password() -> None:
                # A wrong current password counts against the login limit (§2.1, §18.4).
                LOGIN_BY_ADDRESS.hit(address)
                LOGIN_BY_HANDLE.hit(human.handle)

            def password_blocked() -> int:
                return max(LOGIN_BY_ADDRESS.blocked(address), LOGIN_BY_HANDLE.blocked(human.handle))

            status = preferences.patch(
                conn,
                human=human,
                session=session,
                body=body,
                signing_key=hub.mail.signing_key,
                public_url=hub.public_url,
                mail_ready=_mail_ready(conn, request),
                wrong_password=wrong_password,
                password_blocked=password_blocked,
                step_up=lambda: second_factor.require_step_up(conn, hub, caller),  # §2.8.4
                keeps_factor=lambda: second_factor.refuse_losing_the_address(conn, hub, human.id),
            )
            return preferences.view(conn, human.id, _mail_ready(conn, request)), status

    # Three first writes at once can end in a duplicate-key deadlock on MariaDB; the whole
    # transaction runs again (`db.retrying`), and a refusal (an error raised) is not retried.
    answer, status = retrying(run)
    return JSONResponse(answer, status_code=status)


@router.post("/me/notification-settings/email/verify")
def verify_from_dashboard(
    request: Request, caller: AnyCaller, body: Annotated[dict[str, Any], Body()]
) -> JSONResponse:
    _human(caller)
    token = body.get("token")
    if set(body) != {"token"} or not isinstance(token, str):
        raise invalid({"token": "required"})
    hub = settings_of(request)
    addresses.prepare(engine_of(request), hub.secret_key)  # before the lock's transaction
    with engine_of(request).begin() as conn:
        # Another human's token is `not_found`, the same as an invalid one (§18.4).
        done = preferences.verify(
            conn,
            token,
            hub.mail.signing_key,
            hub.public_url,
            secret_key=hub.secret_key,
            human_id=caller.principal_id,
        )
        if not done:
            raise not_found()
        return JSONResponse(preferences.view(conn, caller.principal_id, True))


@router.post("/me/notification-settings/email/address-change/approve")
def approve_change(
    request: Request, caller: AnyCaller, body: Annotated[dict[str, Any], Body()]
) -> JSONResponse:
    return _decide(request, caller, body, approve=True)


@router.post("/me/notification-settings/email/address-change/reject")
def reject_change(
    request: Request, caller: AnyCaller, body: Annotated[dict[str, Any], Body()]
) -> JSONResponse:
    return _decide(request, caller, body, approve=False)


def _decide(
    request: Request, caller: Caller, body: dict[str, Any], *, approve: bool
) -> JSONResponse:
    session_hash = _human(caller)
    if set(body) != {"id", "address"}:
        raise invalid({"body": "id_and_address"})
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        human, session = _context(conn, caller, session_hash)
        preferences.decide_held(
            conn,
            human=human,
            session=session,
            change_id=body["id"],
            address=body["address"],
            approve=approve,
            signing_key=hub.mail.signing_key,
            public_url=hub.public_url,
            step_up=lambda: second_factor.require_step_up(conn, hub, caller),  # §2.8.4
        )
        return JSONResponse(preferences.view(conn, human.id, _mail_ready(conn, request)))
