"""`/admin/settings/site-values` (docs/api.md §16.7.3): the values a site file's placeholders
take on import, for the instance admin. Human only; an agent or runner credential is refused
before anything is read."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from maity_hub import site_values
from maity_hub.admin import require_instance_admin
from maity_hub.auth import second_factor
from maity_hub.deps import HumanCaller, engine_of, settings_of

router = APIRouter()


@router.get("/admin/settings/site-values")
def get_site_values(request: Request, caller: HumanCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        require_instance_admin(conn, caller.principal_id)
        return JSONResponse(site_values.view(conn))


@router.patch("/admin/settings/site-values")
def patch_site_values(
    request: Request, caller: HumanCaller, body: Annotated[dict[str, Any], Body()]
) -> JSONResponse:
    with engine_of(request).begin() as conn:
        require_instance_admin(conn, caller.principal_id)
        second_factor.require_step_up(conn, settings_of(request), caller)  # §2.8.4
        site_values.patch(conn, body, caller.principal_id)
        return JSONResponse(site_values.view(conn))
