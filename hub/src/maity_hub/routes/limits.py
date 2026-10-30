"""`/admin/settings/limits` (docs/api.md §16.5): the caps on what one account may hold, for
the instance admin. Human only; an agent or runner credential is refused before anything is
read."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from maity_hub import limits
from maity_hub.admin import require_instance_admin
from maity_hub.auth import second_factor
from maity_hub.deps import HumanCaller, engine_of, settings_of

router = APIRouter()


@router.get("/admin/settings/limits")
def get_limits(request: Request, caller: HumanCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        require_instance_admin(conn, caller.principal_id)
        return JSONResponse(limits.view(conn, settings_of(request)))


@router.patch("/admin/settings/limits")
def patch_limits(
    request: Request, caller: HumanCaller, body: Annotated[dict[str, Any], Body()]
) -> JSONResponse:
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        require_instance_admin(conn, caller.principal_id)
        second_factor.require_step_up(conn, hub, caller)  # §2.8.4
        limits.patch(conn, hub, body, caller.principal_id)
        return JSONResponse(limits.view(conn, hub))
