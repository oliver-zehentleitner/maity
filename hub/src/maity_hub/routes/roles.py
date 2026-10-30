"""A project's own roles (docs/api.md §2.3 "Project roles"): `GET, PUT …/roles`."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, select, update

from maity_hub import events, idempotency, project_roles, rules
from maity_hub import tables as t
from maity_hub.access import membership
from maity_hub.deps import AnyCaller, HumanCaller, engine_of
from maity_hub.errors import ApiError
from maity_hub.models import Strict
from maity_hub.namespace import ProjectRoute

router = APIRouter(route_class=ProjectRoute)


class RolesIn(Strict):
    custom: Any  # checked by `project_roles.parse`, every bad field named


def _view(conn: Connection, project_id: str) -> dict[str, Any]:
    project = conn.execute(select(t.project).where(t.project.c.id == project_id)).one()
    return project_roles.view(project)


def _replay(conn: Connection, project_id: str, request: Request) -> dict[str, Any]:
    del request
    return _view(conn, project_id)


idempotency.LOADERS["roles"] = _replay


@router.get("/projects/{owner}/{slug}/roles")
def read_roles(slug: str, request: Request, caller: AnyCaller) -> JSONResponse:
    with engine_of(request).connect() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        return JSONResponse(project_roles.view(mine.project))


@router.put("/projects/{owner}/{slug}/roles")
def put_roles(slug: str, body: RolesIn, request: Request, caller: HumanCaller) -> JSONResponse:
    """The whole list (§2.3). A role still in use cannot be removed; a role moved to
    another base takes its members along; `guide_by` names who last set a role's guide."""

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine.require("project:admin")
        project = events.lock_project(conn, mine.project.id)
        parsed = project_roles.parse(body.custom)
        old = {r["name"]: r for r in project_roles.of(project)}
        for name in old.keys() - {r["name"] for r in parsed}:
            found = project_roles.uses(conn, project, name)
            if found:
                raise ApiError(
                    409,
                    "conflict",
                    f"the role {name} is still in use",
                    {"reason": "role_in_use", "role": name, "uses": found},
                )
        handle = conn.execute(
            select(t.human.c.handle).where(t.human.c.id == caller.human_id)
        ).scalar_one()
        new = []
        for role in parsed:
            before = old.get(role["name"])
            if before is not None and before["guide"] == role["guide"]:
                guide_by = before["guide_by"]
            else:
                guide_by = handle if role["guide"] else None
            new.append({**role, "guide_by": guide_by})
        if new != list(old.values()):
            project_roles.rebase(conn, project, new)
            conn.execute(
                update(t.project).where(t.project.c.id == project.id).values(roles=new or None)
            )
            # A project role's guide is part of its members' rules: a bump (§6.9).
            rules.bump(
                conn,
                project,
                "policy_changed",
                ["all"],
                {"fields": ["roles"], "old": list(old.values()), "new": new},
                actor=caller.actor(mine.id),
            )
        return idempotency.Outcome(200, "roles", project.id, {"custom": new})

    return idempotency.run(engine_of(request), request, caller, action)
