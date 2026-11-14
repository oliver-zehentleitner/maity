"""A project's own roles (docs/api.md §2.3 "Project roles"): `GET, PUT …/roles`."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, select, update

from maity_hub import events, guide, idempotency, policy, project_roles, rules
from maity_hub import tables as t
from maity_hub.access import membership
from maity_hub.deps import AnyCaller, HumanCaller, engine_of
from maity_hub.errors import ApiError, invalid
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
        return JSONResponse(
            {"builtin": guide.builtin(mine.project), **project_roles.view(mine.project)}
        )


@router.put("/projects/{owner}/{slug}/roles")
def put_roles(slug: str, body: RolesIn, request: Request, caller: HumanCaller) -> JSONResponse:
    """The whole list (§2.3). A role still in use cannot be removed; a role moved to
    another base takes its members along; a role's stored guide and `guide_by` stay as
    they are."""

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine.require("project:admin")
        project = events.lock_project(conn, mine.project.id)
        parsed = project_roles.parse(body.custom)
        old = {r["name"]: r for r in project_roles.of(project)}
        listed = policy.outside_roles(project)
        for index, role in enumerate(parsed):
            if role["name"] in listed and role["base"] not in policy.OUTSIDE_BASES:
                # An outsider's agent may hold it (`outside_roles`, §6.1): never one that
                # reviews, tests or manages, and the base is what grants those.
                raise invalid(
                    {f"custom[{index}].base": "outside_roles"},
                    f"the role {role['name']} is in policy.outside_roles",
                )
        for name in old.keys() - {r["name"] for r in parsed}:
            found = project_roles.uses(conn, project, name)
            if found:
                raise ApiError(
                    409,
                    "conflict",
                    f"the role {name} is still in use",
                    {"reason": "role_in_use", "role": name, "uses": found},
                )
        # A guide is no longer put here (§2.3, `moved`): a role that stays keeps the guide it
        # has and who set it, until the briefings take the guides over (§6.28); a new role
        # has none.
        new = []
        for role in parsed:
            before = old.get(role["name"]) or {}
            new.append(
                {**role, "guide": before.get("guide", ""), "guide_by": before.get("guide_by")}
            )
        if new != list(old.values()):
            project_roles.rebase(conn, project, new, caller.actor(mine.id))
            conn.execute(
                update(t.project).where(t.project.c.id == project.id).values(roles=new or None)
            )
            # A project role's name and base are part of its members' rules: a bump (§6.9).
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
