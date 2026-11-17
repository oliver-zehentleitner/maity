"""A project's own roles (docs/api.md §2.3 "Project roles"): `GET, PUT …/roles`."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import Field
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
    # Required, refused as `"required"` after the body (§2.3 "Version.").
    base_version: int | None = Field(default=None, ge=0)


def _view(conn: Connection, project_id: str) -> dict[str, Any]:
    project = conn.execute(select(t.project).where(t.project.c.id == project_id)).one()
    return project_roles.view(project)


def _conflict(current: int, base_version: int) -> ApiError:
    """A `PUT` on a list that changed since its caller read it (§2.3 "Version."): nothing
    changes, and the caller reads the list again and decides again."""
    return ApiError(
        409,
        "conflict",
        "the roles changed since you read them; read them and decide again",
        {"current_version": current, "base_version": base_version},
    )


def _replay(conn: Connection, project_id: str, request: Request) -> dict[str, Any]:
    del request
    return _view(conn, project_id)


idempotency.register("roles", _replay, idempotency.in_project(idempotency.the_project))


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
        if body.base_version is None:
            raise invalid({"base_version": "required"}, "name the roles' version you read")
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
        # A guide is no longer put here (§2.3, `moved`): a role that stays keeps the guide it
        # has and who set it, until the briefings take the guides over (§6.28); a new role
        # has none.
        new = []
        for role in parsed:
            before = old.get(role["name"]) or {}
            new.append(
                {**role, "guide": before.get("guide", ""), "guide_by": before.get("guide_by")}
            )
        version = project.roles_version
        if new == list(old.values()):
            # Changes nothing: no write, no event, the version kept, whatever
            # `base_version` says (§2.3 "Version.").
            return idempotency.Outcome(
                200, "roles", project.id, {"custom": new, "version": version}
            )
        if body.base_version != version:
            raise _conflict(version, body.base_version)
        for name in old.keys() - {r["name"] for r in parsed}:
            found = project_roles.uses(conn, project, name)
            if found:
                raise ApiError(
                    409,
                    "conflict",
                    f"the role {name} is still in use",
                    {"reason": "role_in_use", "role": name, "uses": found},
                )
        project_roles.rebase(conn, project, new, caller.actor(mine.id))
        # The version in the same UPDATE as the list, under the project's lock; the guard on
        # the version read makes a lost race a `conflict`, never a silent overwrite.
        written = conn.execute(
            update(t.project)
            .where(t.project.c.id == project.id, t.project.c.roles_version == version)
            .values(roles=new or None, roles_version=version + 1)
        ).rowcount
        if written != 1:
            current = conn.execute(
                select(t.project.c.roles_version).where(t.project.c.id == project.id)
            ).scalar_one()
            raise _conflict(current, body.base_version)
        # A project role's name and base are part of its members' rules: a bump (§6.9).
        rules.bump(
            conn,
            project,
            "policy_changed",
            ["all"],
            {"fields": ["roles"], "old": list(old.values()), "new": new},
            actor=caller.actor(mine.id),
        )
        return idempotency.Outcome(
            200, "roles", project.id, {"custom": new, "version": version + 1}
        )

    return idempotency.run(engine_of(request), request, caller, action)
