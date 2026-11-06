"""A person's public page (docs/api.md §16.9): `GET /{handle}` for every active account, and
its tab of their agents, `GET /{handle}/agents` ("A person's agents").

The maintainer's decision of 2026-11-02: profiles are public by default, and one turned off
is not invisible. The page always shows the `display_name` and the `handle`, with the agents
that have a page; with `public_profile` on also the `public_bio`, the links, the projects
with a public page they are a member of with their role in each, the month they joined, and
whether they are online in one of those projects while `public_presence` is on as well; their
numbers there only while `public_stats` is on too (the maintainer's decisions of 2026-11-05).
The agents page lists the agents the person's `public_agents` names, with what of each a visitor
may see; it is a page of the same target, rendered with the person's page and taken off with it.
A page whose profile is off is `noindex` and out of the sitemap. Never an address or a
session. A person who is suspended, waits
for approval, is deleted or is hidden by moderation (§16.8) has no page: the page is taken off
in the transaction that changed it, by `public_pages.touch`.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from html import escape
from typing import Any, NamedTuple

from sqlalchemy import Connection, select

from maity_hub import clock, moderation, person_links, public_pages, render
from maity_hub import tables as t
from maity_hub.config import Settings

KIND = "person"
AGENTS_VIEW = "person_agents"
# What the agents page lists (§16.9): the agents that have a page, or every one with a membership.
PUBLIC_AGENTS = ("public_projects", "all")
BIO_MAX = 280
# Every C0 control character, and the bidirectional overrides and isolates (§16.9).
_FORBIDDEN = re.compile("[\u0000-\u001f\u202a-\u202e\u2066-\u2069]")


def bio_problem(value: str) -> str | None:
    """`control_character` or `too_long` for a `public_bio` that may not be stored, else None."""
    if _FORBIDDEN.search(value):
        return "control_character"
    if len(value) > BIO_MAX:
        return "too_long"
    return None


def served(conn: Connection, human: Any) -> bool:
    """Whether the person has a page and is named on public pages: their account is active and
    not suspended or deleted, and no hold of moderation stands on their profile. Their own
    choice (`public_profile`) decides what the page shows, not whether it exists (§16.9)."""
    return bool(
        human.account_status == "active"
        and human.deleted_at is None
        and human.suspended_at is None
        and moderation.hold(conn, "profile", human.id) is None
    )


def _links(human: Any) -> str:
    """The website and the names on the networks, while the person lets everyone see them
    (§16.9); each link carries `rel="me nofollow"` so a network can confirm the website."""
    if human.links_visible != "everyone":
        return ""
    items: list[str] = []
    if human.website:
        link = escape(human.website, quote=True)
        items.append(f'<li><a href="{link}" rel="me nofollow">{escape(human.website)}</a></li>')
    for network, shown_as in person_links.built(human.social).items():
        label = escape(network)
        if shown_as.startswith("https://"):
            items.append(
                f'<li>{label}: <a href="{escape(shown_as, quote=True)}" rel="me nofollow">'
                f"{escape(human.social[network])}</a></li>"
            )
        else:  # Discord has no public profile address: text
            items.append(f"<li>{label}: {escape(shown_as)}</li>")
    return f"<ul>{''.join(items)}</ul>" if items else ""


class Listed(NamedTuple):
    """A public project on a person's or an agent's page, with the member's role there."""

    full_name: str
    name: str
    role: str
    project: Any
    membership_id: int


def member_since(created_at: datetime) -> str:
    """The month and year a profile was created, never the day (§16.9)."""
    return created_at.strftime("%Y-%m")


def any_online(conn: Connection, membership_ids: list[int]) -> bool:
    """Whether the member is `online` (§2.4) in one of these memberships now: at the snapshot
    when the page is rendered."""
    from maity_hub.availability import presences_of

    if not membership_ids:
        return False
    rows = conn.execute(
        select(t.membership)
        .where(t.membership.c.id.in_(membership_ids))
        .order_by(t.membership.c.id)
    ).all()
    return any(presence == "online" for presence in presences_of(conn, rows).values())


class ListedAgent(NamedTuple):
    """An agent the person's agents page lists (§16.9): its page's path, the roles of the
    public projects that page lists and the model and harness it shows; `None`, `[]`, `None`
    and `None` for an agent without a page, which shows only its name and handle."""

    agent: Any
    page: str | None
    roles: list[str]
    model: str | None
    harness: str | None


def listed_agents(conn: Connection, human: Any) -> list[ListedAgent]:
    """The agents the person's agents page lists, by handle (§16.9, "A person's agents"):
    those that have a page, and under `public_agents: all` also every other one with an active
    membership in any project; never a deleted one or one held by moderation. Nothing while the
    person has no page. One list for the page, the visitors' route and `GET /people`, so they
    never disagree; the picture's public rule asks it too (§6.10)."""
    from maity_hub import public_agents

    if not served(conn, human):
        return []
    agents = conn.execute(
        select(t.agent_profile).where(
            t.agent_profile.c.owner_id == human.id, t.agent_profile.c.deleted_at.is_(None)
        )
    ).all()
    m = t.membership.c
    working = (
        set(
            conn.execute(
                select(m.agent_id).where(
                    m.agent_id.in_([agent.id for agent in agents]), m.active.is_(True)
                )
            ).scalars()
        )
        if human.public_agents == "all" and agents
        else set()
    )
    listed: list[ListedAgent] = []
    for agent in sorted(agents, key=lambda row: row.handle):
        found = public_agents.served(conn, agent, human)
        if found is not None:
            model, harness = public_agents.latest_session(conn, found)
            roles = sorted({project.member_role for project, _ in found})
            page = f"/{human.handle}/agents/{agent.handle}"
            listed.append(ListedAgent(agent, page, roles, model, harness))
        elif agent.id in working and moderation.hold(conn, "profile", agent.id) is None:
            listed.append(ListedAgent(agent, None, [], None, None))
    return listed


def agent_entry(listed: ListedAgent) -> dict[str, Any]:
    """One agent as the visitors' route answers it (§16.9, `person_agents`). `picture` stays
    `null` until the public picture address exists (tsk-q155psrk6tzz)."""
    return {
        "name": listed.agent.display_name,
        "handle": listed.agent.handle,
        "picture": None,
        "page": listed.page,
        "roles": listed.roles,
        "model": listed.model,
        "harness": listed.harness,
    }


def _listed(conn: Connection, human: Any) -> list[Listed]:
    """The projects with a public page the person is a member of, by full name, only while
    their profile is on (§16.9)."""
    from maity_hub import namespace, public_projects

    m = t.membership.c
    projects = conn.execute(
        select(t.project, m.id.label("membership_id"), m.role.label("member_role"))
        .join(t.membership, m.project_id == t.project.c.id)
        .where(t.project.c.public_page == "on", m.human_id == human.id, m.active.is_(True))
        .order_by(t.project.c.id)
    ).all()
    return (
        sorted(
            (
                Listed(namespace.full_name(conn, p), p.name, p.member_role, p, p.membership_id)
                for p in projects
                if public_projects.served(conn, p)
            ),
            key=lambda listed: listed.full_name,
        )
        if human.public_profile
        else []
    )


class Shown(NamedTuple):
    """What the page shows beyond name, handle and agents, each `None` while it does not."""

    member_since: str | None
    online: bool | None
    statistics: dict[str, Any] | None


STAT_KEYS = ("cards_done", "reviews_given", "prs_merged")  # a person's three (§16.9)


def _shown(conn: Connection, human: Any, named: list[Listed]) -> Shown:
    """Member since, online and the numbers, by the person's switches (§16.9): none of them
    while `public_profile` is off, online only with `public_presence` on as well, the numbers
    only with `public_stats` on as well. The numbers are those of §6.22 per member over the
    listed projects for the last 30 days, `prs_merged` only where a read found a public
    repository (`None` otherwise); never the agent's handovers or medians."""
    from maity_hub import public_agents

    if not human.public_profile:
        return Shown(None, None, None)
    online = (
        any_online(conn, [listed.membership_id for listed in named])
        if human.public_presence
        else None
    )
    numbers = None
    if human.public_stats:
        totals = public_agents.statistics(
            conn, [(listed.project, listed.membership_id) for listed in named]
        )
        numbers = {key: totals[key] for key in STAT_KEYS}
    return Shown(member_since(human.created_at), online, numbers)


CURRENT = ' aria-current="page"'


def _tabs(human: Any, current: str) -> str:
    """The tabs **Profile** and **Agents** both pages carry (§16.9)."""
    base = f"/{escape(human.handle, quote=True)}"
    tabs = (("profile", base, "Profile"), ("agents", f"{base}/agents", "Agents"))
    links = "".join(
        f'<a href="{href}"{CURRENT if name == current else ""}>{label}</a>'
        for name, href, label in tabs
    )
    return f'<nav aria-label="Tabs">{links}</nav>'


def _agent_item(listed: ListedAgent, *, details: bool) -> str:
    """One agent: its name, linked where it has a page, and its handle; on the agents page
    (`details`) also its roles, model and harness, which only an agent with a page has."""
    agent = listed.agent
    name = escape(agent.display_name)
    if listed.page is not None:
        name = f'<a href="{escape(listed.page, quote=True)}">{name}</a>'
    item = f"{name} ({escape(agent.handle)})"
    if details:
        item += "".join(f' <span class="tag">{escape(role)}</span>' for role in listed.roles)
        facts = [
            f"{label}: {escape(value)}"
            for label, value in (("Model", listed.model), ("Harness", listed.harness))
            if value
        ]
        if facts:
            item += f'<br><span class="sub">{" · ".join(facts)}</span>'
    return f"<li>{item}</li>"


def _listed_html(human: Any, named: list[Listed], agents: list[ListedAgent], shown: Shown) -> str:
    from maity_hub import public_projects

    html = ""
    facts = []
    if shown.member_since is not None:
        facts.append(f"<li>Member since {escape(shown.member_since)}</li>")
    if shown.online:
        facts.append("<li>Online</li>")
    if facts:
        html += f'<ul class="facts">{"".join(facts)}</ul>'
    if named:
        items = "".join(
            f'<li><a href="/{escape(listed.full_name, quote=True)}">{escape(listed.name)}</a> '
            f'<span class="tag">{escape(listed.role)}</span></li>'
            for listed in named
        )
        html += f"<h2>Projects</h2><ul>{items}</ul>"
    if shown.statistics is not None:
        lines = "".join(
            f"<li>{escape(label)}: {escape(public_projects.stat_value(key, shown.statistics[key]))}"
            "</li>"
            for key, label in public_projects.STAT_LABELS
            if key in STAT_KEYS and (key != "prs_merged" or shown.statistics[key] is not None)
        )
        html += f"<h2>Statistics, last {public_projects.STAT_DAYS} days</h2><ul>{lines}</ul>"
    if agents:
        items = "".join(_agent_item(listed, details=False) for listed in agents)
        tab = f"/{escape(human.handle, quote=True)}/agents"
        html += f'<h2>Agents</h2><ul>{items}</ul><p><a href="{tab}">All agents</a></p>'
    return html


def _person(human: Any) -> dict[str, Any]:
    """The person as the visitors' route names them beside a list (`owner`)."""
    return {"name": human.display_name, "handle": human.handle, "page": f"/{human.handle}"}


def _data(human: Any, named: list[Listed], agents: list[ListedAgent], shown: Shown) -> dict[str, Any]:
    """What the visitors' route answers; `website` and `social` only as the page shows them."""
    data: dict[str, Any] = {
        "name": human.display_name,
        "handle": human.handle,
        "bio": human.public_bio if human.public_profile else None,
        "projects": [
            {"name": listed.name, "full_name": listed.full_name, "role": listed.role}
            for listed in named
        ],
        "agents": [agent_entry(listed) for listed in agents],
        "member_since": shown.member_since,
        "online": shown.online,
        "statistics": shown.statistics,
    }
    if human.public_profile and human.links_visible == "everyone":
        data["website"] = human.website
        data["social"] = {
            network: human.social[network] for network in person_links.built(human.social)
        }
    return data


def render_person(conn: Connection, hub: Settings, human_id: str) -> list[public_pages.Page]:
    human = conn.execute(select(t.human).where(t.human.c.id == human_id)).first()
    if human is None or not served(conn, human):
        return []
    chosen = bool(human.public_profile)  # the personal details, by the person's choice
    bio = f'<p class="sub">{escape(human.public_bio)}</p>' if chosen and human.public_bio else ""
    links = _links(human) if chosen else ""
    named = _listed(conn, human)
    agents = listed_agents(conn, human)
    shown = _shown(conn, human, named)
    listed = _listed_html(human, named, agents, shown)
    heading = f'<p class="eyebrow">{escape(human.handle)}</p><h1>{escape(human.display_name)}</h1>'
    content = f'{heading}{_tabs(human, "profile")}{bio}{links}{listed}'
    path = f"/{human.handle}"
    body = render.page_document(
        lang="en",
        title=f"{human.display_name} ({human.handle})",
        canonical=f"{hub.public_url.rstrip('/')}{path}",
        content=content,
        indexed=chosen,
    )
    inputs = hashlib.sha256(
        "\x00".join(
            (
                human.handle,
                human.display_name,
                "on" if chosen else "off",
                human.public_bio or "" if chosen else "",
                links,
                listed,
            )
        ).encode()
    )
    return [
        public_pages.Page(
            path=path,
            body=body,
            inputs=inputs.hexdigest(),
            lastmod=clock.now(),
            view="person",
            data=_data(human, named, agents, shown),
            indexed=chosen,
        ),
        _agents_page(hub, human, heading, agents, chosen),
    ]


def _agents_page(
    hub: Settings, human: Any, heading: str, agents: list[ListedAgent], indexed: bool
) -> public_pages.Page:
    """`/{handle}/agents` (§16.9, "A person's agents"): the listed agents with what of each a
    visitor may see, or a sentence when none is listed; `noindex` with the person's page."""
    items = "".join(_agent_item(listed, details=True) for listed in agents)
    shown = f"<ul>{items}</ul>" if agents else "<p>No agents are listed here.</p>"
    content = f'{heading}{_tabs(human, "agents")}<h2>Agents</h2>{shown}'
    path = f"/{human.handle}/agents"
    body = render.page_document(
        lang="en",
        title=f"Agents of {human.display_name} ({human.handle})",
        canonical=f"{hub.public_url.rstrip('/')}{path}",
        content=content,
        indexed=indexed,
    )
    inputs = hashlib.sha256("\x00".join((path, "on" if indexed else "off", content)).encode())
    return public_pages.Page(
        path=path,
        body=body,
        inputs=inputs.hexdigest(),
        lastmod=clock.now(),
        view=AGENTS_VIEW,
        data={"owner": _person(human), "agents": [agent_entry(listed) for listed in agents]},
        indexed=indexed,
    )


def touch_owner_of(
    conn: Connection, agent_id: str, *, removal: bool = True, only_all: bool = False
) -> None:
    """The owner's pages of an agent that changed (§16.9, "A person's agents"): its name, or
    with `only_all` a membership that only `public_agents: all` lists. Nothing for a member
    that is no agent."""
    owner = conn.execute(
        select(t.human)
        .join(t.agent_profile, t.agent_profile.c.owner_id == t.human.c.id)
        .where(t.agent_profile.c.id == agent_id)
    ).first()
    if owner is None or (only_all and owner.public_agents != "all"):
        return
    public_pages.touch(conn, KIND, owner.id, removal=removal, dependents=False)


def targets(conn: Connection) -> list[str]:
    return list(
        conn.execute(
            select(t.human.c.id)
            .where(t.human.c.account_status == "active", t.human.c.deleted_at.is_(None))
            .order_by(t.human.c.id)
        ).scalars()
    )


def dependents(conn: Connection, human_id: str) -> list[tuple[str, str]]:
    """The project pages that show the person: they change with the person's profile."""
    from maity_hub import public_agents, public_projects

    return [
        *public_projects.pages_of_member(conn, human_id),
        *public_agents.pages_of_owner(conn, human_id),
    ]


public_pages.register(public_pages.Kind(KIND, render_person, targets, dependents))
