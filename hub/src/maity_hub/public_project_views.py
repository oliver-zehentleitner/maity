"""The public views of a project (docs/api.md §16.9): Board, Team and Organisation, each a
page of its own at `/{owner}/{slug}/<view>` while the project's page is served.

Who is named follows the project page: every active member and every agent that is not
isolated, by handle, whatever their profile says; only a moderation hold on a profile makes
them a count or a box with a role, never a name, and a card under a hold is on no board.
Whatever changes one of these inputs calls `public_pages.touch` for the kind `project_views`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Collection
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
    public_people,
    render,
)
from maity_hub import tables as t
from maity_hub.config import Settings
from maity_hub.public_projects import member_pictures, served

KIND = "project_views"
# Apart from the members' cache, which may have read with an owner's grant: what the public
# Why shows comes from the instance's own token only (§11.4, §16.9).
WHY_CACHE = ktw.Cache()
BOARD_LIMIT = 200  # cards per open column (§16.9)
CLOSED_DAYS = 30  # the window of `done` and `cancelled`


class Person:
    """A member as the views show them: `handle` is None for one that is not shown."""

    def __init__(
        self,
        row: Any,
        handle: str | None,
        name: str | None,
        human: bool,
        address: str | None = None,
        presence_named: bool = True,
        profile_on: bool = True,
    ) -> None:
        self.address = address  # the member's own page: a person's, or the agent's under its owner
        self.id = row.id
        self.role = row.role
        self.trust = row.trust
        self.reports_to = row.reports_to
        self.handle = handle
        self.name = name
        self.human = human
        # Named and counted as online on a public page: off by a person's `public_presence` (§16.9).
        self.presence_named = presence_named
        # The person or the agent, and whether their own page shows their picture (§16.9): a
        # person's `public_profile`; an agent's page always shows one.
        self.principal: str = row.human_id or row.agent_id
        self.profile_on = profile_on

    @property
    def shown(self) -> bool:
        return self.handle is not None


def members(
    conn: Connection, project_id: str, only: Collection[int] | None = None
) -> dict[int, Person]:
    """Every active member by membership id, an isolated agent not among them (§6.28); the names
    only of those the page shows (no profile hold on an agent, §16.8). With `only`, those
    memberships, for a page that names a few members (a card's holder and note authors)."""
    m = t.membership.c
    found: dict[int, Person] = {}
    query = select(t.membership).where(
        m.project_id == project_id, m.active.is_(True), m.isolated_since.is_(None)
    )
    if only is not None:
        query = query.where(m.id.in_(list(only)))
    rows = conn.execute(query.order_by(m.id)).all()
    humans = {
        h.id: h
        for h in conn.execute(
            select(t.human).where(t.human.c.id.in_({r.human_id for r in rows if r.human_id}))
        )
    }
    agents = {
        a.id: a
        for a in conn.execute(
            select(t.agent_profile).where(
                t.agent_profile.c.id.in_({r.agent_id for r in rows if r.agent_id})
            )
        )
    }
    owners = {
        h.id: h
        for h in conn.execute(
            select(t.human).where(t.human.c.id.in_({a.owner_id for a in agents.values()}))
        )
    }
    held = moderation.holds_of(conn, "profile", [r.agent_id for r in rows if r.agent_id])
    for row in rows:
        if row.human_id:
            human = humans[row.human_id]
            ok = public_people.served(conn, human)
            found[row.id] = Person(
                row,
                human.handle if ok else None,
                human.display_name,
                True,
                f"/{human.handle}" if ok else None,
                bool(human.public_presence),
                bool(human.public_profile),
            )
        else:
            agent = agents[row.agent_id]
            ok = agent.id not in held and public_people.served(conn, owners[agent.owner_id])
            owner = owners[agent.owner_id]
            found[row.id] = Person(
                row,
                agent.handle if ok else None,
                agent.display_name,
                False,
                f"/{owner.handle}/agents/{agent.handle}" if ok else None,
            )
    return found


def person_data(name: str, handle: str, page: str) -> dict[str, str]:
    """Someone shown, as the visitors' route names them (§16.9)."""
    return {"name": name, "handle": handle, "page": page}


def _shown(person: Person) -> dict[str, str] | None:
    if not person.shown:
        return None
    return person_data(person.name or "", person.handle or "", person.address or "")


def _holder(person: Person | None, gone_agent: bool) -> dict[str, str] | str:
    if person is None:
        return "agent" if gone_agent else "member"
    return _shown(person) or ("member" if person.human else "agent")


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
                            _holder(who.get(r.claim_holder), r.claim_holder in gone)
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


def shown_pictures(conn: Connection, who: dict[int, Person]) -> dict[str, str | None]:
    """The picture of each member the views name, as their own page shows it (§16.9), by human
    or agent id: the project page's rule (`public_projects.member_pictures`). One read for the
    Team and the Organisation tab."""
    shown = [p for p in who.values() if p.shown]
    return member_pictures(
        conn,
        [(p.principal, p.profile_on) for p in shown if p.human],
        [p.principal for p in shown if not p.human],
    )


def _pictured(person: Person, pictures: dict[str, str | None]) -> dict[str, Any] | None:
    """Someone shown with the picture their own page shows; None for one the page does not name."""
    named = _shown(person)
    return None if named is None else {**named, "picture": pictures.get(person.principal)}


def members_data(who: dict[int, Person], pictures: dict[str, str | None]) -> dict[str, Any]:
    """The Team tab's `data` (§16.9, `team`): each one shown with the picture their own page
    shows (`pictures`)."""
    shown = sorted((p for p in who.values() if p.shown), key=lambda p: (p.handle or "", p.id))
    return {
        "shown": [
            {**(_pictured(p, pictures) or {}), "trust": p.trust, "role": p.role} for p in shown
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
                "person": _pictured(p, pictures),
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
    (hub/context/public-pages.md)."""
    if project.repository_public is not True or not served:
        return {"readable": False}
    row = public_pages.get(conn, path)
    stored = row.data if row is not None and row.view == "why" and row.data["readable"] else None
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
        digest = hashlib.sha256("\x00".join((path, project.name, content)).encode())
        pages.append(
            public_pages.Page(
                path=path,
                body=render.page_document(
                    lang="en",
                    title=f"{heading} of {project.name} ({full})",
                    canonical=f"{hub.public_url.rstrip('/')}{path}",
                    content=content,
                    styled=False,
                ),
                inputs=digest.hexdigest(),
                lastmod=clock.now(),
                view=view,
                data=data,
            )
        )
    return pages


def targets(conn: Connection, among: Collection[str] | None = None) -> list[str]:
    return list(
        conn.execute(
            select(t.project.c.id)
            .where(t.project.c.public_page == "on", *public_pages.only(t.project.c.id, among))
            .order_by(t.project.c.id)
        ).scalars()
    )


public_pages.register(public_pages.Kind(KIND, render_views, targets, prepare=prepare_why))
