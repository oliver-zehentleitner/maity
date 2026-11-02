"""`/admin/settings/sign-in` (docs/api.md §2.6.6): the instance's sign-in methods, for the
instance admin. Human only; an agent or runner credential is refused before anything is
read."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, select

from maity_hub import tables as t
from maity_hub.admin import require_instance_admin
from maity_hub.auth import second_factor, sign_in_settings
from maity_hub.auth.mail_factor import LIFETIME
from maity_hub.deps import HumanCaller, engine_of, settings_of
from maity_hub.errors import unauthenticated

router = APIRouter()


class Confirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(max_length=32)


def _session(conn: Connection, caller: HumanCaller) -> Any:
    if caller.human_session is None:
        raise unauthenticated("this endpoint needs a dashboard session")
    return conn.execute(
        select(t.human_session).where(t.human_session.c.id_hash == caller.human_session)
    ).one()


@router.get("/admin/settings/sign-in")
def get_sign_in(request: Request, caller: HumanCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        require_instance_admin(conn, caller.principal_id)
        return JSONResponse(sign_in_settings.view(conn, settings_of(request)))


@router.patch("/admin/settings/sign-in")
def patch_sign_in(
    request: Request, caller: HumanCaller, body: Annotated[dict[str, Any], Body()]
) -> JSONResponse:
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        require_instance_admin(conn, caller.principal_id)
        second_factor.require_step_up(conn, hub, caller)  # §2.8.4
        session = _session(conn, caller) if body.get("second_factor") == "email" else None
        if sign_in_settings.patch(conn, hub, body, caller.principal_id, session):
            return JSONResponse({"expires_in": int(LIFETIME.total_seconds())}, status_code=202)
        return JSONResponse(sign_in_settings.view(conn, hub))


@router.post("/admin/settings/sign-in/second-factor-email/confirm")
def confirm_email(body: Confirm, request: Request, caller: HumanCaller) -> JSONResponse:
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        require_instance_admin(conn, caller.principal_id)
        session = _session(conn, caller)
        done = sign_in_settings.confirm_email(conn, hub, session, body.code, caller.principal_id)
        answer = sign_in_settings.view(conn, hub)
    if not done:  # after the commit: the wrong code stays counted (§2.8.6)
        raise second_factor.code_invalid()
    return JSONResponse(answer)
