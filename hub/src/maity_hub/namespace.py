"""Projects in their owner's namespace (docs/api.md §6.25).

A project is addressed as `<owner>/<slug>`: the namespace owner's handle and the slug. Every
project route is `/projects/{owner}/{slug}/…`; `ProjectRoute` hands the route the two as one
`slug` path parameter, the full name, so that a route and its dependencies resolve the
project from one value. `resolve` finds the project by the owner, then the pair of the
owner's id and the slug among every project's current name and aliases.

Old one-segment paths (`/projects/maity/tasks`) always have a reserved word where the new form
has a slug (`tasks` cannot be a slug), so `outdated` recognises them without a lookup and
answers them the same whether the first segment was ever a slug or not.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Coroutine, Iterable
from typing import Any

from fastapi import Request, Response
from fastapi.routing import APIRoute
from sqlalchemy import Connection, select

from maity_hub import tables as t
from maity_hub.errors import ApiError

PREFIX = "/api/v1/projects/"
FULL_NAME = re.compile(r"^([a-z0-9][a-z0-9-]{1,30})/([a-z0-9][a-z0-9-]{1,62})$")
# The lowest CLI that addresses projects as <owner>/<slug> (§6.25): what `client_outdated`
# names. Any CLI that calls an old path is older than that by construction.
CLI_MINIMUM = "0.1.0a2"
# The dashboard's top-level routes (§6.25): never a human handle, so that `#/invite/…` cannot
# be read as the namespace `invite`. Every route the dashboard adds later goes here too.
DASHBOARD_WORDS = frozenset(
    {
        "account", "admin", "agents", "all", "chats", "components", "invite", "join", "login",
        "new", "notifications", "observe", "p", "register", "requests", "runners", "s",
        "settings", "sign-in",
    }
)  # fmt: skip


class ProjectRoute(APIRoute):
    """A route under `/projects/{owner}/{slug}`: its `slug` path parameter becomes the full
    name `<owner>/<slug>` before the dependencies and the endpoint read it."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        inner = super().get_route_handler()

        async def handler(request: Request) -> Response:
            params = request.scope.get("path_params") or {}
            if "owner" in params and "slug" in params:
                params = dict(params)
                params["slug"] = f"{params.pop('owner')}/{params['slug']}"
                request.scope["path_params"] = params
            return await inner(request)

        return handler


def route_words(paths: Iterable[str]) -> frozenset[str]:
    """Every literal segment that follows `{owner}/{slug}` in a project route: a slug is never
    one of them (§6.25), so an old path never reads as a new one."""
    marker = "/projects/{owner}/{slug}/"
    words = set()
    for path in paths:
        _, found, rest = path.partition(marker)
        if found:
            first = rest.split("/", 1)[0]
            if first and not first.startswith("{"):
                words.add(first)
    return frozenset(words)


# The route words when the namespace came (§6.25), a floor under what the routes say: a
# word stays reserved even if its route were ever left out of the schema.
ROUTE_WORDS = frozenset(
    {
        "banner", "conversations", "credentials", "events", "forge", "invitations", "joins",
        "jour-fixe", "keep-the-why", "logo", "members", "memory", "placements", "probe",
        "requests", "rules", "runners", "swarm", "takeovers", "tasks", "ticker",
    }
)  # fmt: skip


def app_words(app: Any) -> frozenset[str]:
    """`route_words` of the running app, read once from its schema's paths (FastAPI keeps
    included routers behind its own objects; the schema lists every path flat)."""
    words = getattr(app.state, "namespace_words", None)
    if words is None:
        words = ROUTE_WORDS | route_words(app.openapi().get("paths", {}))
        app.state.namespace_words = words
    return words


def outdated(path: str, words: frozenset[str]) -> bool:
    """A project path in the form before the namespace: `/projects/<slug>` alone, or
    `/projects/<slug>/<word>/…` with a word that follows a project in a route."""
    if not path.startswith(PREFIX):
        return False
    parts = path[len(PREFIX) :].split("/")
    if len(parts) == 1:
        return parts[0] != ""
    return parts[1] in words


def outdated_error(user_agent: str, install: str) -> ApiError:
    """`client_outdated` (426) for the CLI, `project_path_outdated` (410) for everyone else
    (§6.25); neither says anything about the project."""
    if user_agent.startswith("maity-cli/"):
        return ApiError(
            426,
            "client_outdated",
            "this maity is older than the hub needs: projects are addressed as <owner>/<slug>",
            {"minimum": CLI_MINIMUM, "install": install},
        )
    return ApiError(
        410,
        "project_path_outdated",
        "projects are addressed as /projects/{owner}/{slug} (docs/api.md §6.25)",
    )


def resolve_owner(conn: Connection, handle: str) -> str | None:
    """The human id a namespace owner's handle names (§6.25): the current handle. The hook
    for handle aliases (§6.24): when the hub keeps aliases, an alias resolves here too."""
    return conn.execute(select(t.human.c.id).where(t.human.c.handle == handle)).scalar()


def resolve(conn: Connection, full_name: str) -> Any | None:
    """The project row `<owner>/<slug>` names: by its current name or one of its aliases. At
    most one matches, since a full name once used belongs to one project (§6.25)."""
    found = FULL_NAME.match(full_name)
    if found is None:
        return None
    owner_id = resolve_owner(conn, found[1])
    if owner_id is None:
        return None
    slug = found[2]
    row = conn.execute(
        select(t.project).where(t.project.c.owner_id == owner_id, t.project.c.slug == slug)
    ).first()
    if row is not None:
        return row
    project_id = conn.execute(
        select(t.project_alias.c.project_id).where(
            t.project_alias.c.owner_id == owner_id, t.project_alias.c.slug == slug
        )
    ).scalar()
    if project_id is None:
        return None
    return conn.execute(select(t.project).where(t.project.c.id == project_id)).first()


def owner_of(conn: Connection, project: Any) -> dict[str, str]:
    """`{id, handle}` of the project's namespace owner, by its current handle."""
    handle = conn.execute(
        select(t.human.c.handle).where(t.human.c.id == project.owner_id)
    ).scalar_one()
    return {"id": project.owner_id, "handle": handle}


def full_name(conn: Connection, project: Any) -> str:
    """`<owner handle>/<slug>`: computed, never stored, so it follows a rename (§6.25)."""
    return f"{owner_of(conn, project)['handle']}/{project.slug}"


def name_of(conn: Connection, project_id: str) -> str:
    """The full name of the project with this id (§6.25)."""
    row = conn.execute(
        select(t.project.c.slug, t.human.c.handle)
        .join(t.human, t.human.c.id == t.project.c.owner_id)
        .where(t.project.c.id == project_id)
    ).one()
    return f"{row.handle}/{row.slug}"


def aliases_of(conn: Connection, project_id: str) -> list[str]:
    """The project's earlier full names, oldest first, each with its owner's current handle
    (an owner's own handle aliases resolve anyway, §6.24)."""
    rows = conn.execute(
        select(t.project_alias.c.slug, t.human.c.handle)
        .join(t.human, t.human.c.id == t.project_alias.c.owner_id)
        .where(t.project_alias.c.project_id == project_id)
        .order_by(t.project_alias.c.id)
    ).all()
    return [f"{row.handle}/{row.slug}" for row in rows]


def full_names(conn: Connection, project_ids: Iterable[str]) -> dict[str, str]:
    """project id → full name, in one query, for lists."""
    ids = list(set(project_ids))
    if not ids:
        return {}
    rows = conn.execute(
        select(t.project.c.id, t.project.c.slug, t.human.c.handle)
        .join(t.human, t.human.c.id == t.project.c.owner_id)
        .where(t.project.c.id.in_(ids))
    ).all()
    return {row.id: f"{row.handle}/{row.slug}" for row in rows}


def taken(conn: Connection, owner_id: str, slug: str, project_id: str | None = None) -> bool:
    """Whether `slug` is the current name or an alias of a project in `owner_id`'s namespace,
    other than `project_id` (which may take back its own alias, §6.25)."""
    current = conn.execute(
        select(t.project.c.id).where(t.project.c.owner_id == owner_id, t.project.c.slug == slug)
    ).scalar()
    if current is not None and current != project_id:
        return True
    alias = conn.execute(
        select(t.project_alias.c.project_id).where(
            t.project_alias.c.owner_id == owner_id, t.project_alias.c.slug == slug
        )
    ).scalar()
    return alias is not None and alias != project_id
