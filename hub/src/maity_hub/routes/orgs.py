"""`/orgs` (docs/api.md §6.26): organisations, their members and roles. An organisation is
the humans' business alone: an agent credential is `forbidden` (`humans_only`), and a
caller who is not a member of an organisation gets `not_found` on every route of it."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, StrictBool

from maity_hub import clock, events, org_invitations, orgs, paging
from maity_hub.admin import require_instance_admin
from maity_hub.auth import second_factor
from maity_hub.deps import AnyCaller, HumanCaller, engine_of, settings_of
from maity_hub.errors import forbidden, humans_only, invalid, not_found

router = APIRouter()


class CreateOrg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    handle: str
    display_name: str


class ChangeOrg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = None
    members_create_projects: StrictBool | None = None
    public_page: str | None = None


class ChangeRole(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str


class DeleteOrg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: str


def _human(caller: AnyCaller) -> str:
    if caller.kind == "agent":
        raise humans_only("an organisation is for humans")
    if caller.kind != "human" or caller.human_id is None:
        raise forbidden()
    return caller.human_id


def _locked_actor(conn: Any, org_id: str, human_id: str) -> tuple[Any, str]:
    """The organisation under its lock and the caller's role in it, read under the lock:
    a role read before it could be stale when the change commits (§6.26)."""
    locked = orgs.lock(conn, org_id)
    if locked is None:
        raise not_found()
    role = orgs.role_of(conn, locked.id, human_id)
    if role is None:
        raise not_found()
    return locked, role


@router.post("/orgs", status_code=201)
def create_org(request: Request, caller: AnyCaller, body: CreateOrg) -> JSONResponse:
    human_id = _human(caller)
    with events.transaction(engine_of(request)) as conn:
        org, role = orgs.create(
            conn, human_id, body.handle, body.display_name, settings_of(request).max_orgs_per_human
        )
        return JSONResponse(orgs.view(conn, org, role), status_code=201)


@router.get("/admin/orgs")
def admin_orgs(
    request: Request,
    caller: HumanCaller,
    q: str | None = None,
    suspended: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
) -> JSONResponse:
    """The organisations of the instance, by handle, for the instance admin (§16.10)."""
    if q is not None and not 1 <= len(q) <= 64:
        raise invalid({"q": "invalid"})
    bound = paging.scope(list="admin/orgs", q=q, suspended=suspended)
    after = None if cursor is None else paging.uncursor(cursor, bound)[1]
    with engine_of(request).begin() as conn:
        require_instance_admin(conn, caller.principal_id)
        items, more = orgs.admin_list(conn, q, suspended, after, limit)
        # The cursor is ordered by handle: the timestamp slot only has to be a time.
        next_cursor = (
            paging.cursor(clock.now(), items[-1]["handle"], bound) if more and items else None
        )
        return JSONResponse({"items": items, "next_cursor": next_cursor})


@router.get("/orgs")
def list_orgs(request: Request, caller: AnyCaller) -> JSONResponse:
    human_id = _human(caller)
    with events.transaction(engine_of(request)) as conn:
        return JSONResponse({"items": orgs.mine(conn, human_id)})


@router.get("/orgs/{org}")
def get_org(request: Request, caller: AnyCaller, org: str) -> JSONResponse:
    human_id = _human(caller)
    with events.transaction(engine_of(request)) as conn:
        row, role = orgs.find(conn, human_id, org)
        return JSONResponse(orgs.view(conn, row, role))


@router.patch("/orgs/{org}")
def patch_org(request: Request, caller: AnyCaller, org: str, body: ChangeOrg) -> JSONResponse:
    human_id = _human(caller)
    with events.transaction(engine_of(request)) as conn:
        row, _ = orgs.find(conn, human_id, org)
        locked, role = _locked_actor(conn, row.id, human_id)
        if role != "owner":
            raise orgs.org_role()
        changed = orgs.change_settings(conn, locked, body.model_dump(exclude_unset=True))
        return JSONResponse(orgs.view(conn, changed, role))


@router.delete("/orgs/{org}")
def delete_org(
    request: Request, caller: AnyCaller, org: str, body: Annotated[DeleteOrg, Body()]
) -> Response:
    human_id = _human(caller)
    with events.transaction(engine_of(request)) as conn:
        row, found_role = orgs.find(conn, human_id, org)
        if found_role != "owner":
            raise orgs.org_role()
        second_factor.require_step_up(conn, settings_of(request), caller)  # §2.8.4
        locked, role = _locked_actor(conn, row.id, human_id)
        if role != "owner":  # demoted while waiting for the lock
            raise orgs.org_role()
        orgs.delete_org(conn, locked, body.confirm)
        return Response(status_code=204)


@router.get("/orgs/{org}/members")
def list_members(request: Request, caller: AnyCaller, org: str) -> JSONResponse:
    human_id = _human(caller)
    with events.transaction(engine_of(request)) as conn:
        row, _ = orgs.find(conn, human_id, org)
        return JSONResponse({"items": orgs.members(conn, row.id)})


@router.patch("/orgs/{org}/members/{member}")
def patch_member(
    request: Request, caller: AnyCaller, org: str, member: str, body: ChangeRole
) -> JSONResponse:
    human_id = _human(caller)
    with events.transaction(engine_of(request)) as conn:
        row, _ = orgs.find(conn, human_id, org)
        locked, actor_role = _locked_actor(conn, row.id, human_id)
        item: dict[str, Any] = orgs.set_role(conn, locked, actor_role, member, body.role)
        return JSONResponse(item)


@router.delete("/orgs/{org}/members/{member}")
def delete_member(request: Request, caller: AnyCaller, org: str, member: str) -> Response:
    human_id = _human(caller)
    with events.transaction(engine_of(request)) as conn:
        row, _ = orgs.find(conn, human_id, org)
        locked, actor_role = _locked_actor(conn, row.id, human_id)
        orgs.remove_member(conn, locked, human_id, actor_role, member)
        return Response(status_code=204)


class Invite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    handle: str
    role: str


@router.get("/orgs/{org}/members/invitations")
def list_invitations(request: Request, caller: AnyCaller, org: str) -> JSONResponse:
    human_id = _human(caller)
    with events.transaction(engine_of(request)) as conn:
        row, role = orgs.find(conn, human_id, org)
        if role == "member":
            raise orgs.org_role()
        locked, _ = _locked_actor(conn, row.id, human_id)
        return JSONResponse({"items": org_invitations.open_items(conn, locked)})


@router.post("/orgs/{org}/members/invitations", status_code=202)
def invite(request: Request, caller: AnyCaller, org: str, body: Invite) -> JSONResponse:
    human_id = _human(caller)
    with events.transaction(engine_of(request)) as conn:
        row, _ = orgs.find(conn, human_id, org)
        locked, role = _locked_actor(conn, row.id, human_id)
        item = org_invitations.create(conn, locked, human_id, role, body.handle, body.role)
        return JSONResponse(item, status_code=202)


@router.delete("/orgs/{org}/members/invitations/{invitation}")
def revoke_invitation(request: Request, caller: AnyCaller, org: str, invitation: str) -> Response:
    human_id = _human(caller)
    with events.transaction(engine_of(request)) as conn:
        row, _ = orgs.find(conn, human_id, org)
        locked, role = _locked_actor(conn, row.id, human_id)
        org_invitations.revoke(conn, locked, role, invitation)
        return Response(status_code=204)
