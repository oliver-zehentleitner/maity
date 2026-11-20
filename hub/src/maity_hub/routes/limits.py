"""`/admin/settings/limits` (docs/api.md §16.5): the caps on what one account may hold, for
the instance admin, and `/admin/projects/{owner}/{slug}/limits` and `/admin/users/{id}/limits`
(§16.5.1): the instance admin's limits for one project or one account. Human only; an agent
or runner credential is refused before anything is read."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, select

from maity_hub import limit_overrides, limits, namespace, read_limits
from maity_hub import tables as t
from maity_hub.admin import require_instance_admin
from maity_hub.auth import second_factor
from maity_hub.deps import HumanCaller, engine_of, settings_of
from maity_hub.errors import not_found

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
        answer = limits.view(conn, hub)
    # Once committed: a read in between would otherwise cache the old value again.
    read_limits.forget_instance_value()
    return JSONResponse(answer)


# --- per project and per account (§16.5.1) -------------------------------------------------


def _project(conn: Connection, owner: str, slug: str) -> Any:
    """The project of the full name `<owner>/<slug>`, current or an alias, else `not_found`."""
    project = namespace.resolve(conn, f"{owner}/{slug}")
    if project is None:
        raise not_found()
    return project


def _human(conn: Connection, human_id: str) -> str:
    """A human account that is not deleted, else `not_found`."""
    found = conn.execute(
        select(t.human.c.id).where(t.human.c.id == human_id, t.human.c.deleted_at.is_(None))
    ).scalar()
    if found is None:
        raise not_found()
    return str(found)


@router.get("/admin/projects/{owner}/{slug}/limits")
def get_project_limits(
    owner: str, slug: str, request: Request, caller: HumanCaller
) -> JSONResponse:
    with engine_of(request).begin() as conn:
        require_instance_admin(conn, caller.principal_id)
        project = _project(conn, owner, slug)
        return JSONResponse(limit_overrides.project_view(conn, settings_of(request), project))


@router.patch("/admin/projects/{owner}/{slug}/limits")
def patch_project_limits(
    owner: str,
    slug: str,
    request: Request,
    caller: HumanCaller,
    body: Annotated[dict[str, Any], Body()],
) -> JSONResponse:
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        require_instance_admin(conn, caller.principal_id)
        project = _project(conn, owner, slug)
        second_factor.require_step_up(conn, hub, caller)  # §2.8.4
        limit_overrides.patch(conn, body, caller.principal_id, project_id=project.id)
        return JSONResponse(limit_overrides.project_view(conn, hub, project))


@router.get("/admin/users/{human_id}/limits")
def get_account_limits(human_id: str, request: Request, caller: HumanCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        require_instance_admin(conn, caller.principal_id)
        found = _human(conn, human_id)
        return JSONResponse(limit_overrides.account_view(conn, settings_of(request), found))


@router.patch("/admin/users/{human_id}/limits")
def patch_account_limits(
    human_id: str,
    request: Request,
    caller: HumanCaller,
    body: Annotated[dict[str, Any], Body()],
) -> JSONResponse:
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        require_instance_admin(conn, caller.principal_id)
        found = _human(conn, human_id)
        second_factor.require_step_up(conn, hub, caller)  # §2.8.4
        limit_overrides.patch(conn, body, caller.principal_id, human_id=found)
        return JSONResponse(limit_overrides.account_view(conn, hub, found))
