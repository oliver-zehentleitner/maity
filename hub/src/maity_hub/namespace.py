"""Projects in their owner's namespace (docs/api.md §6.25).

A project is addressed as `<owner>/<slug>`: the namespace owner's handle and the slug. Every
project route is `/projects/{owner}/{slug}/…`; `ProjectRoute` hands the route the two as one
`slug` path parameter, the full name, so that a route and its dependencies resolve the
project from one value. `resolve` finds the project by the owner, then the pair of the
owner's id and the slug among every project's current name and aliases.

A slug is never a literal word after `{slug}` in a route (`ROUTE_WORDS`) nor a project view of
the dashboard (§16.11), so that `/<owner>/<word>` stays free.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Coroutine, Iterable
from datetime import timedelta
from typing import Any

from fastapi import Request, Response
from fastapi.routing import APIRoute
from sqlalchemy import Connection, delete, func, insert, inspect, select

from maity_hub import clock, paths
from maity_hub import tables as t
from maity_hub.errors import ApiError, rate_limited

PREFIX = "/api/v1/projects/"
# A project's aliases (§6.25), as a handle's (§6.24): at most 8, and renames and transfers
# together at most 3 per 24 hours per project.
ALIAS_LIMIT = 8
CHANGES_PER_DAY = 3
DAY_SECONDS = 24 * 3600
FULL_NAME = re.compile(r"^([a-z0-9][a-z0-9-]{1,30})/([a-z0-9][a-z0-9-]{1,62})$")


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
        "attachments", "banner", "conversations", "credentials", "events", "forge",
        "invitations", "joins", "jour-fixe", "keep-the-why", "logo", "me", "members", "memory",
        "messages", "placements", "probe", "repository", "requests", "roles", "rules", "runners",
        "swarm", "takeovers", "tasks", "ticker", "transfer",
    }
)  # fmt: skip


def app_words(app: Any) -> frozenset[str]:
    """`route_words` of the running app, read once from its schema's paths (FastAPI keeps
    included routers behind its own objects; the schema lists every path flat)."""
    words = getattr(app.state, "namespace_words", None)
    if words is None:
        words = ROUTE_WORDS | paths.PROJECT_VIEWS | route_words(app.openapi().get("paths", {}))
        app.state.namespace_words = words
    return words


def owner_values(owner_id: str) -> dict[str, Any]:
    """The owner columns of a `project` or `project_alias` row for the namespace owner
    `owner_id`, a human's or an organisation's: `owner_id` and the one foreign key of its kind
    (§6.26, `tables.OWNER_SHAPE`)."""
    human = owner_id.startswith("hum-")
    return {
        "owner_id": owner_id,
        "owner_human_id": owner_id if human else None,
        "owner_org_id": None if human else owner_id,
    }


def _owners(table: Any) -> Any:
    """`table` with its owner, a human or an organisation, joined for the handle."""
    return table.outerjoin(t.human, t.human.c.id == table.c.owner_human_id).outerjoin(
        t.org, t.org.c.id == table.c.owner_org_id
    )


def _handle(table: Any) -> Any:
    """The current handle of the row's namespace owner, whichever kind it is."""
    return func.coalesce(t.human.c.handle, t.org.c.handle)


def join_owner(query: Any) -> Any:
    """`query`, which has `project` among its tables, with the project's owner joined: use
    `owner_handle()` for its handle."""
    return query.outerjoin(t.human, t.human.c.id == t.project.c.owner_human_id).outerjoin(
        t.org, t.org.c.id == t.project.c.owner_org_id
    )


def owner_handle() -> Any:
    """The handle of the namespace owner joined by `join_owner`: a human's or an organisation's."""
    return func.coalesce(t.human.c.handle, t.org.c.handle)


def resolve_owner(conn: Connection, handle: str) -> str | None:
    """The id a namespace owner's handle names (§6.25): a human's or an organisation's
    (§6.26), by the current handle or an alias (§6.24), so that `<old
    handle>/<slug>` keeps reaching the project after a rename; a deleted one's still names
    its archived projects."""
    from maity_hub import handles

    human = handles.human_id_of(conn, handle)
    if human is not None:
        return human
    return handles.org_id_of(conn, handle)


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
        select(_handle(t.project))
        .select_from(_owners(t.project))
        .where(t.project.c.id == project.id)
    ).scalar_one()
    return {"id": project.owner_id, "handle": handle}


def full_name(conn: Connection, project: Any) -> str:
    """`<owner handle>/<slug>`: computed, never stored, so it follows a rename (§6.25)."""
    return f"{owner_of(conn, project)['handle']}/{project.slug}"


def name_of(conn: Connection, project_id: str) -> str:
    """The full name of the project with this id (§6.25)."""
    row = conn.execute(
        select(t.project.c.slug, _handle(t.project).label("handle"))
        .select_from(_owners(t.project))
        .where(t.project.c.id == project_id)
    ).one()
    return f"{row.handle}/{row.slug}"


def aliases_of(conn: Connection, project_id: str) -> list[str]:
    """The project's earlier full names, oldest first, each with its owner's current handle
    (an owner's own handle aliases resolve anyway, §6.24)."""
    rows = conn.execute(
        select(t.project_alias.c.slug, _handle(t.project_alias).label("handle"))
        .select_from(_owners(t.project_alias))
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
        select(t.project.c.id, t.project.c.slug, _handle(t.project).label("handle"))
        .select_from(_owners(t.project))
        .where(t.project.c.id.in_(ids))
    ).all()
    return {row.id: f"{row.handle}/{row.slug}" for row in rows}


def taken(conn: Connection, owner_id: str, slug: str, project_id: str | None = None) -> bool:
    """Whether `slug` is the current name or an alias of a project in `owner_id`'s namespace,
    other than `project_id` (which may take back its own alias, §6.25).

    Every caller is about to claim the slug, so the namespace owner's row is locked first:
    a project's slug and an alias live in two tables, and no constraint keeps a create of
    `s` from racing a rename away from `s`, which writes `s` as an alias."""
    if owner_id.startswith("org-"):  # an organisation's namespace: its row, as every change of it
        conn.execute(select(t.org.c.id).where(t.org.c.id == owner_id).with_for_update()).first()
    else:
        conn.execute(select(t.human.c.id).where(t.human.c.id == owner_id).with_for_update()).first()
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


def aliases_by(conn: Connection, project_ids: Iterable[str]) -> dict[str, list[str]]:
    """project id → `aliases_of`, in one query, for lists."""
    ids = list(set(project_ids))
    found: dict[str, list[str]] = {i: [] for i in ids}
    if not ids:
        return found
    rows = conn.execute(
        select(
            t.project_alias.c.project_id,
            t.project_alias.c.slug,
            _handle(t.project_alias).label("handle"),
        )
        .select_from(_owners(t.project_alias))
        .where(t.project_alias.c.project_id.in_(ids))
        .order_by(t.project_alias.c.id)
    ).all()
    for row in rows:
        found[row.project_id].append(f"{row.handle}/{row.slug}")
    return found


def check_change(conn: Connection, project: Any, owner_id: str, slug: str) -> None:
    """Before a rename or a transfer to `owner_id`/`slug` (§6.25): the slug free in that
    namespace (the project may take back its own alias), the alias the change adds within
    `ALIAS_LIMIT`, and the project's changes within `CHANGES_PER_DAY`."""
    if taken(conn, owner_id, slug, project.id):
        raise ApiError(
            400, "invalid", "the slug is taken in that namespace", {"fields": {"slug": "taken"}}
        )
    back = _own_alias(conn, project.id, owner_id, slug)
    given_up = _own_alias(conn, project.id, project.owner_id, project.slug)
    names = aliases_of(conn, project.id)
    after = len(names) - (back is not None) + (given_up is None)
    if after > ALIAS_LIMIT:  # taking a name back never adds one, so it stays possible
        raise ApiError(
            409,
            "alias_limit",
            f"a project keeps at most {ALIAS_LIMIT} former names",
            {"limit": ALIAS_LIMIT, "aliases": names},
        )
    _check_rate(conn, project.id)


def _own_alias(conn: Connection, project_id: str, owner_id: str, slug: str) -> int | None:
    found: int | None = conn.execute(
        select(t.project_alias.c.id).where(
            t.project_alias.c.project_id == project_id,
            t.project_alias.c.owner_id == owner_id,
            t.project_alias.c.slug == slug,
        )
    ).scalar()
    return found


def _check_rate(conn: Connection, project_id: str) -> None:
    """`rate_limited` past `CHANGES_PER_DAY` renames and transfers in 24 hours, counted from
    the `project_updated` events that changed the full name: the log is the record."""
    now = clock.now()
    since = now - timedelta(seconds=DAY_SECONDS)
    rows = conn.execute(
        select(t.event.c.at, t.event.c.payload)
        .where(
            t.event.c.project_id == project_id,
            t.event.c.kind == "project_updated",
            t.event.c.at > since,
        )
        .order_by(t.event.c.seq)
    ).all()
    changes = [r.at for r in rows if "full_name" in ((r.payload or {}).get("fields") or {})]
    if len(changes) >= CHANGES_PER_DAY:
        wait = changes[-CHANGES_PER_DAY] + timedelta(seconds=DAY_SECONDS) - now
        raise rate_limited(max(1, int(wait.total_seconds()) + 1))


def move(conn: Connection, project: Any, owner_id: str, slug: str) -> None:
    """Give the project the name `owner_id`/`slug`: the name given up becomes an alias,
    and a name taken back leaves the aliases (§6.25). `check_change` came first."""
    back = _own_alias(conn, project.id, owner_id, slug)
    if back is not None:
        conn.execute(delete(t.project_alias).where(t.project_alias.c.id == back))
    if _own_alias(conn, project.id, project.owner_id, project.slug) is None:
        conn.execute(
            insert(t.project_alias).values(
                project_id=project.id,
                **owner_values(project.owner_id),
                slug=project.slug,
                created_at=clock.now(),
            )
        )
    conn.execute(
        t.project.update()
        .where(t.project.c.id == project.id)
        .values(**owner_values(owner_id), slug=slug)
    )


def namespace_owner_of(conn: Connection, human_id: str, project_ids: Iterable[str]) -> None:
    """`namespace_owner` (409) when `human_id` is the namespace owner of any of
    `project_ids`: no demotion below owner, no removal, no account deletion (§6.25)."""
    ids = list(project_ids)
    if not ids:
        return
    # The namespace owner, or an owner of the organisation that owns the project (§6.26):
    # the organisation's owners stay owners of its projects collectively, one by one.
    owns_org = select(t.org_member.c.org_id).where(
        t.org_member.c.human_id == human_id, t.org_member.c.role == "owner"
    )
    rows = conn.execute(
        select(t.project.c.id).where(
            (t.project.c.owner_id == human_id) | t.project.c.owner_org_id.in_(owns_org),
            t.project.c.id.in_(ids),
        )
    ).scalars()
    names = sorted(full_names(conn, rows).values())
    if names:
        raise ApiError(
            409,
            "namespace_owner",
            "the project's namespace owner stays an owner: transfer the project first",
            {"projects": names},
        )


def reserved_holders(conn: Connection) -> list[str]:
    """Who already holds a word that §16.11 reserves: a handle that is a reserved first
    segment, a slug or a project alias that is a project view or a route word. A release
    that reserves such a word does not go on; the operator renames the holder first. Tables
    an older schema does not have yet are skipped."""
    present = set(inspect(conn).get_table_names())
    found: list[str] = []
    if "human" in present:
        found += [
            f"handle {handle!r}"
            for handle in conn.execute(select(t.human.c.handle)).scalars()
            if handle in paths.RESERVED_FIRST
        ]
    if "org" in present:  # an organisation's handle is held to the same words (§6.26)
        found += [
            f"organisation handle {handle!r}"
            for handle in conn.execute(select(t.org.c.handle)).scalars()
            if handle in paths.RESERVED_FIRST
        ]
    slugs = ROUTE_WORDS | paths.PROJECT_VIEWS
    for table, label in ((t.project, "slug"), (t.project_alias, "project alias")):
        if table.name in present:
            found += [
                f"{label} {slug!r}"
                for slug in conn.execute(select(table.c.slug)).scalars()
                if slug in slugs
            ]
    return sorted(found)
