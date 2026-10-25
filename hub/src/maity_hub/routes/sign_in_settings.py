"""`/admin/settings/sign-in` (docs/api.md §2.6.6): the instance's sign-in methods, for the
instance admin. Human only; an agent or runner credential is refused before anything is
read."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from maity_hub.admin import require_instance_admin
from maity_hub.auth import sign_in_settings
from maity_hub.deps import HumanCaller, engine_of, settings_of

router = APIRouter()


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
        sign_in_settings.patch(conn, hub, body, caller.principal_id)
        return JSONResponse(sign_in_settings.view(conn, hub))
