"""A person's public page (docs/api.md §16.9): `GET /{handle}` for every active account, with
their agents on it ("A person's agents"). `/{handle}/agents` is no page: the maintainer took
the agents' tab back on 2026-11-15 (req-xkxaq2c3cjjq), and the address names nothing.

The maintainer's decision of 2026-11-02: profiles are public by default, and one turned off
is not invisible. The page always shows the `display_name`, the `handle` and the agents the
person's `public_agents` names, with what of each a visitor may see; with `public_profile` on
also the `public_bio`, the links, the projects
with a public page they are a member of with their role in each, the month they joined, and
whether they are online in one of those projects while `public_presence` is on as well; their
numbers there only while `public_stats` is on too (the maintainer's decisions of 2026-11-05).
A page whose profile is off is `noindex` and out of the sitemap. Never an address or a
session. A person who is suspended, waits
for approval, is deleted or is hidden by moderation (§16.8) has no page: the page is taken off
in the transaction that changed it, by `public_pages.touch`.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Collection
from datetime import datetime
from typing import Any, NamedTuple

from sqlalchemy import Connection, select

from maity_hub import clock, moderation, person_links, public_pages, render
from maity_hub import tables as t
from maity_hub.config import Settings

KIND = "person"
# Which agents the page lists (§16.9): those that have a page, or every one with a membership.
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
    picture: str | None = None  # its public address (§6.10); every agent has a picture


def listed_agents(conn: Connection, human: Any) -> list[ListedAgent]:
    """The agents the person's agents page lists, by handle (§16.9, "A person's agents"):
    those that have a page, and under `public_agents: all` also every other one with an active
    membership in any project; never a deleted one or one held by moderation. Nothing while the
    person has no page. One list for the page, the visitors' route and `GET /people`, so they
    never disagree; the picture's public rule asks it too (§6.10)."""
    from maity_hub import avatars, public_agents

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
    pictures = avatars.public_urls(conn, [entry.agent.id for entry in listed])
    return [entry._replace(picture=pictures.get(entry.agent.id)) for entry in listed]


def agent_entry(listed: ListedAgent) -> dict[str, Any]:
    """One agent as the visitors' route answers it (§16.9, `person`'s `agents`); `picture` is its
    public address (§6.10)."""
    return {
        "name": listed.agent.display_name,
        "handle": listed.agent.handle,
        "picture": listed.picture,
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


def _data(
    human: Any,
    named: list[Listed],
    agents: list[ListedAgent],
    shown: Shown,
    picture: str | None,
) -> dict[str, Any]:
    """What the visitors' route answers; `website` and `social` only as the page shows them."""
    data: dict[str, Any] = {
        "name": human.display_name,
        "handle": human.handle,
        "picture": picture,
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
    """The person's page: its `data` first, then the HTML in the dashboard's design as a pure
    function of it (`public_design.profile`), so the two cannot show different things."""
    human = conn.execute(select(t.human).where(t.human.c.id == human_id)).first()
    if human is None or not served(conn, human):
        return []
    from maity_hub import avatars, public_design

    chosen = bool(human.public_profile)  # the personal details, by the person's choice
    # The picture while the profile is on (§16.9), else the letter.
    picture = avatars.public_urls(conn, [human.id])[human.id] if chosen else None
    named = _listed(conn, human)
    agents = listed_agents(conn, human)
    shown = _shown(conn, human, named)
    data = _data(human, named, agents, shown, picture)
    path = f"/{human.handle}"
    # One page: the agents stand under the projects, no tabs (§16.9, "A person's agents").
    content = public_design.profile(KIND, data, path)
    body = render.page_document(
        lang="en",
        title=f"{human.display_name} ({human.handle})",
        canonical=f"{hub.public_url.rstrip('/')}{path}",
        content=content,
        indexed=chosen,
        styled=False,
    )
    inputs = hashlib.sha256(
        "\x00".join((path, human.display_name, "on" if chosen else "off", content)).encode()
    )
    page = public_pages.Page(
        path=path,
        body=body,
        inputs=inputs.hexdigest(),
        lastmod=clock.now(),
        view=KIND,
        data=data,
        indexed=chosen,
    )
    return [page]


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


def targets(conn: Connection, among: Collection[str] | None = None) -> list[str]:
    return list(
        conn.execute(
            select(t.human.c.id)
            .where(
                t.human.c.account_status == "active",
                t.human.c.deleted_at.is_(None),
                *public_pages.only(t.human.c.id, among),
            )
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
