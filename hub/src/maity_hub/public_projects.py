"""A project's public page (docs/api.md §16.9): `GET /{owner}/{slug}` while the project's
`public_page` is `on`.

It shows the project's `name` and `full_name`, its state and the `public_about` text, its
people and agents, the repository and its links, the statistics, and a snapshot of what is
happening (Recently, who is online); its views are `public_project_views`. A page is not
served for an archived project, for one a moderation hold stands on, or while its namespace
owner is suspended, waiting for approval or deleted, or an organisation that is suspended or
deleted. Whatever changes one of these calls `public_pages.touch` in its transaction.
"""

from __future__ import annotations

from collections.abc import Collection
from html import escape
from typing import Any

from sqlalchemy import Connection, select

from maity_hub import (
    clock,
    landing,
    moderation,
    namespace,
    project_links,
    public_design,
    public_pages,
    public_people,
    render,
    swarm,
)
from maity_hub import tables as t
from maity_hub.chunks import chunks
from maity_hub.config import Settings
from maity_hub.errors import invalid

KIND = "project"
VIEWS = "project_views"  # the kind of its Board, Team, Organisation and Why pages
ABOUT_MAX_BYTES = 4096  # 4 KiB (§16.9)


def about_problem(value: str) -> str | None:
    """Why a `public_about` may not be stored: `too_long`, `control_character`, or the `line N`
    of the first line the landing page's Markdown rules (§16.7) refuse; None when it is fine."""
    if landing.CONTROL.search(value):  # before the size: a lone surrogate does not encode
        return "control_character"
    if len(value.encode()) > ABOUT_MAX_BYTES:
        return "too_long"
    return landing.markdown_problem(value)


def check_about(value: str | None) -> str | None:
    """The text to store, or `invalid` (`details.fields.public_about`); empty is none."""
    if not value:
        return None
    problem = about_problem(value)
    if problem is not None:
        raise invalid({"public_about": problem})
    return value


# Each question below asks in IN lists of at most `chunks.CHUNK` ids: `/explore` and the
# landing page's count judge every project with a page on the instance, which no quota bounds.


def served_of(conn: Connection, rows: Collection[Any]) -> set[str]:
    """The ids of `rows` that have a page now, each judged by its own `public_page`, `state`
    and owner columns: the one rule of `served`, `served_among` and the public lists, which
    pass the rows they read. The page is on, the project is not archived and under no
    moderation hold, and its namespace owner is an organisation that is not deleted and under
    no hold, or a human who is active, not deleted and not suspended. At most four statements
    for every `chunks.CHUNK` rows, none when no row has its page on."""
    return standing_of(
        conn, [row for row in rows if row.public_page == "on" and row.state != "archived"]
    )


def standing_of(conn: Connection, rows: Collection[Any]) -> set[str]:
    """The ids of `rows` whose project and namespace owner may show anything in public, the
    part of `served_of` that is not the page's own columns: the project under no moderation
    hold, and its owner an organisation that is not deleted and under no hold, or a human who
    is active, not deleted and not suspended. The badge asks it too (§6.20), which is served
    without a page. At most four statements for every `chunks.CHUNK` rows, none for none."""
    rows = list(rows)
    if not rows:
        return set()
    held: set[str] = set()
    for ids in chunks(row.id for row in rows):
        held.update(moderation.holds_of(conn, "project", ids))
    rows = [row for row in rows if row.id not in held]
    if not rows:
        return set()
    org_ids = {row.owner_org_id for row in rows if row.owner_org_id is not None}
    human_ids = {row.owner_human_id for row in rows if row.owner_org_id is None}
    orgs: set[str] = set()
    for ids in chunks(org_ids):
        found = set(
            conn.execute(
                select(t.org.c.id).where(t.org.c.id.in_(ids), t.org.c.deleted_at.is_(None))
            ).scalars()
        )
        orgs |= found - set(moderation.holds_of(conn, "org", sorted(found)))
    humans: set[str] = set()
    h = t.human.c
    for ids in chunks(human_ids):
        humans.update(
            conn.execute(
                select(h.id).where(
                    h.id.in_(ids),
                    h.account_status == "active",
                    h.deleted_at.is_(None),
                    h.suspended_at.is_(None),
                )
            ).scalars()
        )
    return {
        row.id
        for row in rows
        if (
            row.owner_org_id in orgs
            if row.owner_org_id is not None
            else row.owner_human_id in humans
        )
    }


def served(conn: Connection, project: Any) -> bool:
    """Whether the project has a page now. The row given is judged as it is, not read again:
    a PATCH asks this of the project as it will be (`agent_owners.effective` under
    `routes.projects._refuse_outside_roles`), with a `public_page` not yet written."""
    return bool(served_of(conn, [project]))


def served_among(conn: Connection, project_ids: Collection[str]) -> set[str]:
    """Of `project_ids`, those that have a page now: `served` for many projects at once, as
    stored (the starred tabs on every `GET /me`, §5.1). It reads their rows, one statement for
    every `chunks.CHUNK` ids, and judges them by `served_of`. An id that names no project is simply
    not among them."""
    p = t.project.c
    rows: list[Any] = []
    for ids in chunks(project_ids):
        rows.extend(
            conn.execute(
                select(p.id, p.public_page, p.state, p.owner_org_id, p.owner_human_id).where(
                    p.id.in_(ids), p.public_page == "on", p.state != "archived"
                )
            )
        )
    return served_of(conn, rows)


def public_for_outsiders(conn: Connection, project_ids: Collection[str]) -> set[str]:
    """Of `project_ids`, those public for a reader who is no member: `served_among`, and none
    at all while the instance serves no public pages (`MAITY_PUBLIC_PAGES` off, §16.9). Fail
    closed, as ruled for the stars (hub/context/persistence.md c0e833f1). `served`,
    `served_of` and `served_among` themselves do not ask: most of their callers render pages,
    which happens only while pages are served, and the others (`agent_owners.effective`,
    `landing_stats`) keep their own rules."""
    if not public_pages.serving():
        return set()
    return served_among(conn, project_ids)


def team(conn: Connection, project_id: str) -> tuple[list[Any], list[Any]]:
    """Who the page names (§16.9): every human member and every agent, by handle, whatever
    their profile says; an open project never only counts them. Active memberships only, in
    the order of the handles. A person or agent profile under a hold of moderation (§16.8), a
    suspended owner's agent and an isolated agent (§6.28) are neither named nor counted."""
    m = t.membership.c
    people = conn.execute(
        select(t.human)
        .join(t.membership, m.human_id == t.human.c.id)
        .where(m.project_id == project_id, m.active.is_(True))
        .order_by(t.human.c.handle)
    ).all()
    humans = [h for h in people if public_people.served(conn, h)]
    agents = conn.execute(
        select(t.agent_profile)
        .join(t.membership, m.agent_id == t.agent_profile.c.id)
        .where(m.project_id == project_id, m.active.is_(True), m.isolated_since.is_(None))
        .order_by(t.agent_profile.c.handle)
    ).all()
    owners = (
        {
            h.id: h
            for h in conn.execute(
                select(t.human).where(t.human.c.id.in_({a.owner_id for a in agents}))
            )
        }
        if agents
        else {}
    )
    # An agent profile under a hold of moderation (§16.8) is no more named than a person's.
    held = moderation.holds_of(conn, "profile", [a.id for a in agents])
    shown = [
        a for a in agents if a.id not in held and public_people.served(conn, owners[a.owner_id])
    ]
    return humans, shown


def member_pictures(
    conn: Connection, humans: list[tuple[str, bool]], agents: list[str]
) -> dict[str, str | None]:
    """The picture of each member as their own page shows it (§16.9), by human or agent id:
    a person's (`humans`, each with their `public_profile`) only while their profile is on,
    `None` otherwise; an agent's always. The one rule of every page whose `data` names members
    with a picture: the project page and its Team and Organisation tabs."""
    from maity_hub import avatars

    pictures: dict[str, str | None] = dict.fromkeys(human_id for human_id, _ in humans)
    pictures |= avatars.public_urls(
        conn, [*(human_id for human_id, shown in humans if shown), *agents]
    )
    return pictures


def team_details(
    conn: Connection, project_id: str, agents: list[Any]
) -> tuple[dict[str, str], dict[str, str | None]]:
    """What the page's data adds to each one it names besides the picture (§16.9, `project`):
    the role of the membership in this project, as the Team tab shows it, and an agent's
    harness, as its own page shows it. The picture follows the member's own page
    (`member_pictures`, read once by `render_project`)."""
    from maity_hub import public_agents

    m = t.membership.c
    roles: dict[str, str] = {}
    for human_id, agent_id, role in conn.execute(
        select(m.human_id, m.agent_id, m.role).where(m.project_id == project_id, m.active.is_(True))
    ).all():
        roles[human_id or agent_id] = role
    harnesses: dict[str, str | None] = {}
    for a in agents:
        found = public_agents.memberships(conn, a.id)
        harnesses[a.id] = public_agents.latest_session(conn, found)[1] if found else None
    return roles, harnesses


STAT_DAYS = 30


def agent_statistics(
    conn: Connection, project_id: str, named: list[Any] | None = None
) -> dict[str, Any]:
    """The project's statistics reduced for the public (§16.9, §6.22): the last 30 days over
    the agents only, so that no human's contribution appears. `totals` (with
    `cards_done_per_day`) count every agent that is not isolated; `members` has a row, with its
    counters, for each agent the page names (no hold on its profile, an owner not suspended, not
    isolated: `team`). `named` is what `team` found, when the caller has it already."""
    m = t.membership.c
    rows = conn.execute(
        select(m.id, m.agent_id).where(
            m.project_id == project_id,
            m.active.is_(True),
            m.agent_id.is_not(None),
            m.isolated_since.is_(None),  # an isolated agent is not counted
        )
    ).all()
    agents = {row.id for row in rows}
    by_agent = {row.agent_id: row.id for row in rows}
    if named is None:
        _, named = team(conn, project_id)
    people = {
        by_agent[a.id]: {"handle": a.handle, "name": a.display_name, "display_name": a.display_name}
        for a in named
        if a.id in by_agent
    }
    found = swarm.CACHE.get(conn, project_id)
    folded: dict[str, Any] = swarm.fold(
        found, people, days=STAT_DAYS, include=lambda member: member in agents, public_only=True
    )
    return {"totals": folded["totals"], "members": folded["members"]}


def pages_with_picture(conn: Connection, owner_id: str) -> list[tuple[str, str]]:
    """The project pages that show a member's picture (§16.9, `project`, `team` and
    `organisation`): the page and the views (its Team and Organisation tabs) of each public
    project where the person or the agent is an active member, in its team and in `online`."""
    m = t.membership.c
    ids = conn.execute(
        select(t.project.c.id)
        .join(t.membership, m.project_id == t.project.c.id)
        .where(
            t.project.c.public_page == "on",
            m.active.is_(True),
            (m.human_id == owner_id) | (m.agent_id == owner_id),
        )
        .distinct()
        .order_by(t.project.c.id)
    ).scalars()
    return [(kind, project_id) for project_id in ids for kind in (KIND, VIEWS)]


def pages_of_member(conn: Connection, human_id: str) -> list[tuple[str, str]]:
    """The public project pages that show the person: a member, or the owner of an agent that
    is one (a moderation hold on the person's profile, its lifting, a rename or a change of
    what the profile shows changes them, §16.9), and the card pages whose holder, a note's
    author or a note's latest editor is one of those memberships, which name them as the
    Board names a holder: by handle, or "member" while a hold stands."""
    from maity_hub import public_cards

    m = t.membership.c
    agents = select(t.agent_profile.c.id).where(t.agent_profile.c.owner_id == human_id)
    theirs = (
        m.active.is_(True),
        (m.human_id == human_id) | m.agent_id.in_(agents),
    )
    ids = conn.execute(
        select(t.project.c.id)
        .join(t.membership, m.project_id == t.project.c.id)
        .where(t.project.c.public_page == "on", *theirs)
        .distinct()
        .order_by(t.project.c.id)
    ).scalars()
    held = (
        select(t.card.c.id)
        .join(t.membership, m.id == t.card.c.claim_holder)
        .join(t.project, t.project.c.id == t.card.c.project_id)
        .where(t.project.c.public_page == "on", *theirs)
    )
    noted = (
        select(t.card_note.c.card_id)
        .join(t.membership, m.id == t.card_note.c.author)
        .join(t.card, t.card.c.id == t.card_note.c.card_id)
        .join(t.project, t.project.c.id == t.card.c.project_id)
        .where(t.project.c.public_page == "on", *theirs)
    )
    # The latest editor of a note is named on the page too; `edited` keeps their membership in
    # JSON, so the few edited notes of the person's projects are matched here.
    mine = set(
        conn.execute(
            select(m.id)
            .join(t.project, t.project.c.id == m.project_id)
            .where(t.project.c.public_page == "on", *theirs)
        ).scalars()
    )
    edited = conn.execute(
        select(t.card_note.c.card_id, t.card_note.c.edited)
        .join(t.card, t.card.c.id == t.card_note.c.card_id)
        .where(
            t.card_note.c.edited.is_not(None),
            t.card.c.project_id.in_(select(m.project_id).where(m.id.in_(mine))),
        )
    )
    by_them = {row.card_id for row in edited if row.edited["by"] in mine}
    cards = sorted(set(conn.execute(held).scalars()) | set(conn.execute(noted).scalars()) | by_them)
    return [(kind, project_id) for project_id in ids for kind in (KIND, VIEWS)] + [
        (public_cards.KIND, card) for card in cards
    ]


def render_project(conn: Connection, hub: Settings, project_id: str) -> list[public_pages.Page]:
    """The project's page: its `data` first, then the HTML in the dashboard's design as a pure
    function of it (`public_design.page`), so the two cannot show different things."""
    project = conn.execute(select(t.project).where(t.project.c.id == project_id)).first()
    if project is None or not served(conn, project):
        return []
    full = namespace.full_name(conn, project)
    # The repository only while the forge's last answer said it is public (§16.9).
    shown_url = project.repository_url if project.repository_public is True else None
    # The project's own links (§6.11): one into the repository's path only while it is public.
    shown_links = project_links.public(
        project.links, project.repository_url, project.repository_public
    )
    humans, agents = team(conn, project.id)
    statistics = agent_statistics(conn, project.id, agents)
    from maity_hub import public_agents, public_snapshot
    from maity_hub.public_project_views import members, shown_pictures

    # The members are read once for the page: the Members figure, the pictures of everyone it
    # names and who is online all come from this one read.
    who = members(conn, project.id)
    pictures = shown_pictures(conn, who)
    entries = public_snapshot.ticker(conn, project)
    up = public_snapshot.online(conn, who, pictures)
    owners = dict(
        conn.execute(
            select(t.human.c.id, t.human.c.handle).where(
                t.human.c.id.in_({a.owner_id for a in agents})
            )
        ).all()
    )
    roles, harnesses = team_details(conn, project.id, agents)
    data = {
        "name": project.name,
        "full_name": full,
        "about": project.public_about,
        "state": project.state,
        "repository_url": shown_url if shown_url and landing.safe_target(shown_url) else None,
        "links": [u for u in shown_links if landing.safe_target(u)],
        "people": [
            {
                "name": h.display_name,
                "handle": h.handle,
                "page": f"/{h.handle}",
                "picture": pictures.get(h.id),
                "role": roles.get(h.id),
            }
            for h in humans
        ],
        "agents": [
            {
                "name": a.display_name,
                "handle": a.handle,
                "page": public_agents.path_of(owners[a.owner_id], a.handle),
                "picture": pictures.get(a.id),
                "role": roles.get(a.id),
                "harness": harnesses.get(a.id),
            }
            for a in agents
        ],
        # The Members figure: the Team tab's list, those it names and those it only counts.
        "members": len(who),
        "statistics": statistics,
        "ticker": entries,
        # The snapshot's time: `data` is stored on every render, the HTML and the sitemap's
        # date only change with what the page shows.
        "online": {**up, "as_of": clock.rfc3339(clock.now())},
    }
    path = f"/{full}"
    content = public_design.page(KIND, data, path)
    return [
        public_pages.page(
            hub, path, f"{project.name} ({full})", content, (project.name,), KIND, data
        )
    ]


def targets(conn: Connection, among: Collection[str] | None = None) -> list[str]:
    return list(
        conn.execute(
            select(t.project.c.id)
            .where(t.project.c.public_page == "on", *public_pages.only(t.project.c.id, among))
            .order_by(t.project.c.id)
        ).scalars()
    )


def touch_of_agent(conn: Connection, agent_id: str, *, removal: bool = True) -> None:
    """The pages of every public project the agent is a member of: its `display_name` changed."""
    m = t.membership.c
    for project_id in conn.execute(
        select(t.project.c.id)
        .join(t.membership, m.project_id == t.project.c.id)
        .where(t.project.c.public_page == "on", m.agent_id == agent_id, m.active.is_(True))
        .distinct()
        .order_by(t.project.c.id)
    ).scalars():
        public_pages.touch(conn, KIND, project_id, removal=removal)


def touch_owned(conn: Connection, human_id: str, *, removal: bool = True) -> None:
    """The pages of every project whose namespace owner is the human: their account changed."""
    for project_id in conn.execute(
        select(t.project.c.id).where(
            t.project.c.owner_human_id == human_id, t.project.c.public_page == "on"
        )
    ).scalars():
        public_pages.touch(conn, KIND, project_id, removal=removal)


def touch_of_org(conn: Connection, org_id: str, *, removal: bool = True) -> None:
    """The organisation's page and those of every project it owns: it was suspended, deleted
    or renamed."""
    from maity_hub import public_orgs

    public_pages.touch(conn, public_orgs.KIND, org_id, removal=removal)
    for project_id in conn.execute(
        select(t.project.c.id).where(
            t.project.c.owner_org_id == org_id, t.project.c.public_page == "on"
        )
    ).scalars():
        public_pages.touch(conn, KIND, project_id, removal=removal)


def dependents(conn: Connection, project_id: str) -> list[tuple[str, str]]:
    """The pages that show a project: its views (Board, Team, Organisation, Why, which follow its
    page: served, named and shown alike), its agents' pages, and the person pages that list it
    or its agents: its human members' and the owners' of its agent members, who need not be
    members themselves (§16.9)."""
    from maity_hub import public_cards

    return _dependents(conn, project_id, public_cards.of_project(conn, project_id))


def member_dependents(
    conn: Connection, project_id: str, principal_id: str
) -> list[tuple[str, str]]:
    """`dependents` for a change of one member: the same pages, but of the card pages only those
    that name the member, as its claim holder, a note's author or its latest editor. No other
    card page shows a member, so none other changes; a project's card pages are too many to
    remove and render again for every member change (hub/context/public-pages.md fe966f9c)."""
    from maity_hub import public_cards

    return _dependents(conn, project_id, public_cards.naming(conn, project_id, principal_id))


def _dependents(conn: Connection, project_id: str, cards: list[str]) -> list[tuple[str, str]]:
    from maity_hub import public_agents, public_cards, public_orgs

    m = t.membership.c
    members = conn.execute(
        select(m.human_id, t.agent_profile.c.owner_id)
        .select_from(t.membership.outerjoin(t.agent_profile, t.agent_profile.c.id == m.agent_id))
        .where(m.project_id == project_id)
    ).all()
    people = sorted({h for h, _ in members if h} | {o for _, o in members if o})
    org = conn.execute(
        select(t.project.c.owner_org_id).where(t.project.c.id == project_id)
    ).scalar()
    return [
        (VIEWS, project_id),
        *[(public_cards.KIND, card) for card in cards],
        *([(public_orgs.KIND, org)] if org else []),
        *public_agents.pages_of_project(conn, project_id),
        *[(public_people.KIND, person) for person in people],
        *_shared_agent_pages(conn, project_id),
    ]


def _shared_agent_pages(conn: Connection, project_id: str) -> list[tuple[str, str]]:
    """The other public project pages with an agent of this project: each names the agent's
    harness, read from its latest session in any of its public projects (§16.9), so a change
    of this one (its page, its state, a member) may change what they show."""
    m = t.membership.c
    other = t.membership.alias("other")
    ids = conn.execute(
        select(other.c.project_id)
        .select_from(other.join(t.project, t.project.c.id == other.c.project_id))
        .where(
            other.c.agent_id.in_(
                select(m.agent_id).where(m.project_id == project_id, m.agent_id.is_not(None))
            ),
            other.c.project_id != project_id,
            other.c.active.is_(True),
            t.project.c.public_page == "on",
        )
        .distinct()
        .order_by(other.c.project_id)
    ).scalars()
    return [(KIND, other_id) for other_id in ids]


def explore_html(
    conn: Connection,
    hub: Settings,
    *,
    setting: dict[str, Any],
    legal: dict[str, Any],
    stats: dict[str, Any] | None,
    lang: str | None,
    accept_language: str | None,
) -> str:
    """The page of `/explore`: every project that has a page now, by name, as cards in the
    frame of §16.7.5 (`setting`, `legal`, `stats` and `accept_language` are the frame's). It
    shows only what those pages already show, and is rendered per request, behind the public
    cache."""
    p = t.project.c
    candidates = conn.execute(
        select(p.id, p.name, p.public_page, p.state, p.owner_org_id, p.owner_human_id).where(
            p.public_page == "on", p.state != "archived"
        )
    ).all()
    public = served_of(conn, candidates)
    names = namespace.full_names(conn, public)
    shown = sorted(
        ((names[row.id], row.name) for row in candidates if row.id in public),
        key=lambda item: (item[1].casefold(), item[0]),
    )

    def monogram_of(full: str, name: str) -> str:
        return public_design.monogram(name, full.rsplit("/", 1)[-1])

    def page(lang: str, words: dict[str, str]) -> tuple[str, str]:
        # As the approved mockup draws it (tsk-tp97v64vpy5z): the landing's dark hero, then the
        # projects as cards. No count is shown, so no figure can be 0.
        # Projects have no picture, so the tile shows the first letter of the name in the
        # accent colour, else that of the slug (the approved mockup, README point 8).
        cards = "".join(
            f'<li><a class="xcard" href="/{escape(full, quote=True)}">'
            f'<span class="pmark" aria-hidden="true">{escape(monogram_of(full, name))}</span>'
            f"<b>{escape(name)}</b><small>{escape(full)}</small>"
            f'<span class="go">{escape(words["open"])} <span aria-hidden="true">→</span></span>'
            "</a></li>"
            for full, name in shown
        )
        listed = (
            f'<ul class="xgrid">{cards}</ul>'
            if cards
            else f'<p class="empty-note">{escape(words["none"])}</p>'
        )
        content = (
            '<section class="hero dz xhero"><div class="wrap">'
            f'<p class="eyebrow">{escape(words["kicker"])}</p>'
            f'<h1>{escape(words["heading"])}</h1><p class="sub">{escape(words["sub"])}</p>'
            "</div></section>"
            f'<section class="sec"><div class="wrap">{listed}</div></section>'
        )
        return words["title"], content

    return render.framed_document(
        section="explore",
        page=page,
        canonical=f"{hub.public_url.rstrip('/')}/explore",
        setting=setting,
        legal=legal,
        stats=stats,
        lang=lang,
        accept_language=accept_language,
    )


public_pages.register(public_pages.Kind(KIND, render_project, targets, dependents))
