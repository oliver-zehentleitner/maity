"""The public views of a project (docs/api.md §16.9): Board, Members and Organisation, each a
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
from html import escape
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
    public_pages,
    public_people,
    render,
)
from maity_hub import tables as t
from maity_hub.config import Settings
from maity_hub.public_projects import served

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


def _who(person: Person | None, gone_agent: bool = False) -> str:
    """The holder of a card: by name only while the page names them. A holder no longer among
    the members (isolated, removed) is "an agent" when it was one, else "a member"."""
    if person is None:
        return "an agent" if gone_agent else "a member"
    if person.shown:
        return f"{escape(person.name or '')} ({escape(person.handle or '')})"
    return "a member" if person.human else "an agent"


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


def board_html(
    columns: list[tuple[str, list[Any]]], who: dict[int, Person], gone: set[int], full: str
) -> str:
    """Each card's id links its own page (§16.9, "Card")."""
    base = escape(f"/{full}/tasks/", quote=True)
    html = []
    for status, rows in columns:
        items = "".join(
            f'<li><a class="tag" href="{base}{escape(r.id, quote=True)}">{escape(r.id)}</a> '
            f"{escape(r.title)}"
            + (f' <span class="tag">{escape(r.label)}</span>' if r.label else "")
            + (
                f' <span class="tag">{_who(who.get(r.claim_holder), r.claim_holder in gone)}</span>'
                if r.claim_holder
                else ""
            )
            + "</li>"
            for r in rows
        )
        html.append(
            f"<h2>{escape(status.replace('_', ' '))} ({len(rows)})</h2>"
            + (f"<ul>{items}</ul>" if items else "")
        )
    return "".join(html)


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


def members_data(who: dict[int, Person]) -> dict[str, Any]:
    shown = sorted((p for p in who.values() if p.shown), key=lambda p: (p.handle or "", p.id))
    return {
        "shown": [{**(_shown(p) or {}), "trust": p.trust, "role": p.role} for p in shown],
        "others": [{"role": r, "count": n} for r, n in sorted(_other_roles(who).items())],
    }


def _boss(p: Person, who: dict[int, Person]) -> int | None:
    """A boss who is no active member is no line."""
    return p.reports_to if p.reports_to in who and p.reports_to != p.id else None


def _tree_order(p: Person) -> tuple[int, str, str, int]:
    return (0, p.handle or "", p.role, p.id) if p.shown else (1, "", p.role, p.id)


def organisation_data(who: dict[int, Person]) -> dict[str, Any]:
    """The nodes carry a number of this answer, so no member id leaves the hub."""
    ordered = sorted(who.values(), key=_tree_order)
    index = {p.id: i for i, p in enumerate(ordered)}
    nodes = []
    for p in ordered:
        boss = _boss(p, who)
        nodes.append(
            {
                "index": index[p.id],
                "person": _shown(p),
                "role": p.role,
                "reports_to": None if boss is None else index[boss],
            }
        )
    return {"nodes": nodes}


def members_html(who: dict[int, Person]) -> str:
    shown = sorted((p for p in who.values() if p.shown), key=lambda p: (p.handle or "", p.id))
    items = "".join(
        f'<li><a href="{escape(p.address or "", quote=True)}">{escape(p.name or "")}</a>'
        f" ({escape(p.handle or '')}) "
        f'<span class="tag">{escape(p.trust)} · {escape(p.role)}</span></li>'
        for p in shown
    )
    others = "".join(
        f"<li>{n} × {escape(role)}</li>" for role, n in sorted(_other_roles(who).items())
    )
    return (f"<ul>{items}</ul>" if items else "") + (
        f"<h2>Others</h2><ul>{others}</ul>" if others else ""
    )


def organisation_html(who: dict[int, Person]) -> str:
    """The reporting lines among the members: a boss who is no active member is no line."""
    children: dict[int | None, list[Person]] = {}
    for p in who.values():
        children.setdefault(_boss(p, who), []).append(p)

    def node(p: Person, seen: frozenset[int]) -> str:
        label = (
            f"{escape(p.name or '')} ({escape(p.handle or '')}) " if p.shown else ""
        ) + f'<span class="tag">{escape(p.role)}</span>'
        below = [c for c in children.get(p.id, []) if c.id not in seen]
        inner = "".join(node(c, seen | {c.id}) for c in sorted(below, key=_tree_order))
        return f"<li>{label}{f'<ul>{inner}</ul>' if inner else ''}</li>"

    roots = sorted(children.get(None, []), key=_tree_order)
    return "<ul>" + "".join(node(p, frozenset({p.id})) for p in roots) + "</ul>" if roots else ""


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


def why_html(data: dict[str, Any]) -> str:
    if not data["readable"]:
        return "<p>The Keep the Why of this project is not public, or not read yet.</p>"
    status = data["summary"]["status"]
    counts = "".join(f"<li>{escape(key)}: {value}</li>" for key, value in status.items() if value)
    family = "".join(
        (
            f'<li><a href="{escape(m["dashboard_url"], quote=True)}" rel="nofollow ugc">'
            f'{escape(m["name"] or m["path"])}</a></li>'
            if m["dashboard_url"]
            else f'<li>{escape(m["name"] or m["path"])}</li>'
        )
        for m in data["family"]
    )
    attention = "".join(
        f'<li><a href="{escape(a["link"], quote=True)}" rel="nofollow ugc">{escape(a["title"])}</a>'
        f' <span class="tag">{escape(a["status"])}</span></li>'
        for a in data["attention"]
    )
    return (
        f"<p>{data['summary']['entries']} entries</p><ul>{counts}</ul>"
        + (f"<h2>Family</h2><ul>{family}</ul>" if family else "")
        + (f"<h2>Needs attention</h2><ul>{attention}</ul>" if attention else "")
    )


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
    views = (
        ("board", "Board", board_html(columns, who, gone, full), board_data(columns, who, gone)),
        ("members", "Members", members_html(who), members_data(who)),
        ("organisation", "Organisation", organisation_html(who), organisation_data(who)),
        ("why", "Why", why_html(why), why),
    )
    pages = []
    for view, heading, inner, data in views:
        content = (
            f'<p class="eyebrow"><a href="/{escape(full, quote=True)}">{escape(full)}</a></p>'
            f"<h1>{escape(project.name)}: {heading}</h1>{inner}"
        )
        path = f"/{full}/{view}"
        digest = hashlib.sha256("\x00".join((path, project.name, content)).encode())
        pages.append(
            public_pages.Page(
                path=path,
                body=render.page_document(
                    lang="en",
                    title=f"{heading} of {project.name} ({full})",
                    canonical=f"{hub.public_url.rstrip('/')}{path}",
                    content=content,
                ),
                inputs=digest.hexdigest(),
                lastmod=clock.now(),
                view=view,
                data=data,
            )
        )
    return pages


def targets(conn: Connection) -> list[str]:
    return list(
        conn.execute(
            select(t.project.c.id).where(t.project.c.public_page == "on").order_by(t.project.c.id)
        ).scalars()
    )


public_pages.register(public_pages.Kind(KIND, render_views, targets, prepare=prepare_why))
