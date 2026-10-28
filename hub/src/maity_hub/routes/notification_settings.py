"""`/me/notification-settings` (docs/api.md §18.4).

The settings are a human's own: an agent credential is `forbidden` with `humans_only`.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Connection

from maity_hub.auth.caller import Caller
from maity_hub.deps import AnyCaller, engine_of, settings_of
from maity_hub.errors import forbidden, humans_only
from maity_hub.mail import settings as mail_settings
from maity_hub.notifications import preferences

router = APIRouter()


def _human(caller: Caller) -> str:
    if caller.kind == "agent":
        raise humans_only("notification settings are a human's own")
    if caller.kind != "human" or caller.human_session is None:
        raise forbidden(message="notification settings need a dashboard session")
    return caller.principal_id


def _mail_ready(conn: Connection, request: Request) -> bool:
    hub = settings_of(request)
    return mail_settings.resolve(conn, hub.mail, hub.secret_key).complete


@router.get("/me/notification-settings")
def get_settings(request: Request, caller: AnyCaller) -> JSONResponse:
    human_id = _human(caller)
    with engine_of(request).begin() as conn:
        return JSONResponse(preferences.view(conn, human_id, _mail_ready(conn, request)))


@router.patch("/me/notification-settings")
def patch_settings(
    request: Request, caller: AnyCaller, body: Annotated[dict[str, Any], Body()]
) -> JSONResponse:
    human_id = _human(caller)
    with engine_of(request).begin() as conn:
        preferences.patch(conn, human_id=human_id, body=body)
        return JSONResponse(preferences.view(conn, human_id, _mail_ready(conn, request)))
