"""The public views of a project (docs/api.md §16.9): Board, Team, Organisation and Why, each a
page of its own at `/{owner}/{slug}/<view>` while the project's page is served.

Who is named follows the project page: every active member and every agent that is not
isolated, by handle, whatever their profile says; only a moderation hold on a profile makes
them a count or a box with a role, never a name, and a card under a hold is on no board.
Whatever changes one of these inputs calls `public_pages.touch` for the kind `project_views`.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, Engine, func, or_, select

from maity_hub import (
    cards,
    clock,
    forge,
    forge_access,
    ktw,
    moderation,
    namespace,
    public_design,
    public_pages,
)
from maity_hub import tables as t
from maity_hub.config import Settings
from maity_hub.public_members import (
    Person,
    holder_data,
    members,
    pictured,
    shown_pictures,
)
from maity_hub.public_projects import served, targets

KIND = "project_views"
# Apart from the members' cache, which may have read with an owner's grant: what the public
# Why shows comes from the instance's own token only (§11.4, §16.9).
WHY_CACHE = ktw.Cache()
BOARD_LIMIT = 200  # cards per open column (§16.9)
CLOSED_DAYS = 30  # the window of `done` and `cancelled`


def _gone_agents(conn: Connection, project_id: str, who: dict[int, Person]) -> set[int]:
    """The memberships of agents that hold a card of the project and are not among `who`."""
    m = t.membership.c
    holders = {
        h
        for h in conn.execute(
            select(t.card.c.claim_holder).where(
                t.card.c.project_id == project_id, t.card.c.claim_holder.is_not(None)
            )
        ).scalars()
        if h not in who
    }
    if not holders:
        return set()
    return set(
        conn.execute(select(m.id).where(m.id.in_(holders), m.agent_id.is_not(None))).scalars()
    )


def board_rows(
    conn: Connection, project_id: str, who: dict[int, Person]
) -> tuple[list[tuple[str, list[Any]]], set[int]]:
    """The cards the board shows, per status, and the memberships of agents gone from it."""
    c = t.card.c
    cutoff = clock.now() - timedelta(days=CLOSED_DAYS)
    held = set(
        moderation.holds_of(
            conn,
            "card",
            list(conn.execute(select(c.id).where(c.project_id == project_id)).scalars()),
        )
    )
    gone = _gone_agents(conn, project_id, who)
    columns = []
    for status in cards.STATUSES:
        query = select(c.id, c.title, c.label, c.claim_holder).where(
            c.project_id == project_id, c.status == status
        )
        if status in cards.CLOSED:
            query = query.where(c.closed_at >= cutoff)
        if status != "done":  # a `security` card stays internal until it is done (§16.9)
            query = query.where(or_(c.label.is_(None), func.lower(c.label) != "security"))
        if held:  # the cards under a hold are left out in the query, so the limit counts the rest
            query = query.where(c.id.notin_(held))
        rows = list(
            conn.execute(query.order_by(c.created_at.desc(), c.id.desc()).limit(BOARD_LIMIT))
        )
        columns.append((status, rows))
    return columns, gone


def board_data(
    columns: list[tuple[str, list[Any]]], who: dict[int, Person], gone: set[int]
) -> dict[str, Any]:
    return {
        "columns": [
            {
                "status": status,
                "cards": [
                    {
                        "id": r.id,
                        "title": r.title,
                        "label": r.label,
                        "holder": (
                            holder_data(who.get(r.claim_holder), r.claim_holder in gone)
                            if r.claim_holder
                            else None
                        ),
                    }
                    for r in rows
                ],
            }
            for status, rows in columns
        ]
    }


def _other_roles(who: dict[int, Person]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for p in who.values():
        if not p.shown:
            counts[p.role] = counts.get(p.role, 0) + 1
    return counts


def members_data(who: dict[int, Person], pictures: dict[str, str | None]) -> dict[str, Any]:
    """The Team tab's `data` (§16.9, `team`): each one shown with the picture their own page
    shows (`pictures`)."""
    shown = sorted((p for p in who.values() if p.shown), key=lambda p: (p.handle or "", p.id))
    return {
        "shown": [
            {**(pictured(p, pictures) or {}), "trust": p.trust, "role": p.role} for p in shown
        ],
        "others": [{"role": r, "count": n} for r, n in sorted(_other_roles(who).items())],
    }


def _boss(p: Person, who: dict[int, Person]) -> int | None:
    """A boss who is no active member is no line."""
    return p.reports_to if p.reports_to in who and p.reports_to != p.id else None


def _tree_order(p: Person) -> tuple[int, str, str, int]:
    return (0, p.handle or "", p.role, p.id) if p.shown else (1, "", p.role, p.id)


def organisation_data(who: dict[int, Person], pictures: dict[str, str | None]) -> dict[str, Any]:
    """The nodes carry a number of this answer, so no member id leaves the hub. A named node's
    `person` carries the picture as the Team tab's does (`pictures`, §16.9)."""
    ordered = sorted(who.values(), key=_tree_order)
    index = {p.id: i for i, p in enumerate(ordered)}
    nodes = []
    for p in ordered:
        boss = _boss(p, who)
        nodes.append(
            {
                "index": index[p.id],
                "person": pictured(p, pictures),
                "role": p.role,
                "reports_to": None if boss is None else index[boss],
            }
        )
    return {"nodes": nodes}


def why_data(conn: Connection, project: Any, path: str, served: bool = True) -> dict[str, Any]:
    """What the page shows of the Keep the Why export (§16.9 **Why**): the counts, each family
    member's name, path and dashboard link, and the attention entries, read beforehand. Nothing
    while the repository is not public, nor for a project outside the operator's own namespaces
    (`served` False, §11.4), a stored view included. Each process holds its own read: a render
    with none, with a failed one or with one older than the stored view keeps that view
    (hub/context/public-pages.md). The view names the repository it was read from, and a
    stored view is kept only for the project's current repository, never while it names
    none: after a switch to another one, a process with no read of it shows nothing until it
    reads it."""
    if project.repository_public is not True or not served:
        return {"readable": False}
    row = public_pages.get(conn, path)
    stored = (
        row.data
        if row is not None
        and row.view == "why"
        and row.data["readable"]
        and project.repository_url is not None
        and row.data.get("repository_url") == project.repository_url
        else None
    )
    entry = WHY_CACHE.cached(project.id)
    if entry is None or entry.repository_url != project.repository_url:
        return stored or {"readable": False}  # no read of this repository in this process
    snapshot = entry.snapshot
    if snapshot is None:  # read, and the repository names no export any more
        return {"readable": False}
    if snapshot.error is not None:  # a failed read says nothing about the export
        return stored or {"readable": False}
    if stored and stored["observed_at"] > snapshot.observed_at:
        return dict(stored)
    answer = snapshot.answer()
    return {
        "readable": True,
        "observed_at": snapshot.observed_at,
        "repository_url": entry.repository_url,
        "summary": answer["summary"],
        "family": [
            {"name": m["name"], "path": m["path"], "dashboard_url": m["dashboard_url"]}
            for m in answer["members"]
        ],
        "attention": [
            {key: item[key] for key in ("member", "title", "status", "topic", "link")}
            for item in answer["attention"]
        ],
    }


def prepare_why(engine: Engine, hub: Settings) -> None:
    """Read the exports of the projects whose repository the hub last found public, with the
    instance's token and no grant, for the renders that follow: only those in the operator's
    own namespaces, the only ones that token serves (§11.4, §16.9)."""
    if hub.forge_github_token is None or not hub.forge_instance_namespaces:
        return
    with engine.connect() as conn:
        rows = conn.execute(
            namespace.join_owner(
                select(
                    t.project.c.id, t.project.c.repository_url, namespace.owner_handle()
                ).select_from(t.project)
            ).where(t.project.c.public_page == "on", t.project.c.repository_public.is_(True))
        ).all()
    reader = forge.Forge(hub.forge_github_token)
    for row in rows:
        if not forge_access.serves(hub.forge_instance_namespaces, row[2]):
            continue
        try:
            WHY_CACHE.get(reader, row.id, row.repository_url, 0)
        except ktw.Busy:
            continue


def render_views(conn: Connection, hub: Settings, project_id: str) -> list[public_pages.Page]:
    project = conn.execute(select(t.project).where(t.project.c.id == project_id)).first()
    if project is None or not served(conn, project):
        return []
    full = namespace.full_name(conn, project)
    who = members(conn, project_id)
    columns, gone = board_rows(conn, project_id, who)
    by_instance = hub.forge_github_token is not None and forge_access.serves(
        hub.forge_instance_namespaces, full.split("/", 1)[0]
    )
    why = why_data(conn, project, f"/{full}/why", by_instance)
    faces = shown_pictures(conn, who)
    views = (
        ("board", "Board", board_data(columns, who, gone)),
        ("team", "Team", members_data(who, faces)),
        ("organisation", "Organisation", organisation_data(who, faces)),
        ("why", "Why", why),
    )
    pages = []
    for view, heading, data in views:
        path = f"/{full}/{view}"
        # The HTML in the dashboard's design, from `data` alone (`public_design.page`).
        content = public_design.page(view, data, path)
        pages.append(
            public_pages.page(
                hub,
                path,
                f"{heading} of {project.name} ({full})",
                content,
                (project.name,),
                view,
                data,
            )
        )
    return pages


# The views follow their project's page: the same targets (§16.9).
public_pages.register(public_pages.Kind(KIND, render_views, targets, prepare=prepare_why))
