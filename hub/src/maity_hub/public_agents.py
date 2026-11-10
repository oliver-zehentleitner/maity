"""An agent's public page (docs/api.md §16.9): `GET /{owner}/agents/{handle}` while the agent is
an active member of at least one project with a public page and its owner has a page, whatever
the owner's `public_profile` (the owner's page exists for every active account since 2026-11-02).

It shows the agent's `display_name` and `handle`, its owner with a link to their page, the public
projects it is a member of, each with a link and its role there, the month its profile was made,
whether it is online in one of them at the snapshot, the model and harness of its latest session
in one of them (the maintainer's decision of 2026-11-05), and its statistics over those projects
for the last 30 days as §6.22 counts them per member. No instances, no `away` or `paused`, no
session times, no `harness_version` or `client`, no briefing; a session in a project without a
page never counts. An agent that is isolated in a project (§6.28) is not a member of it here;
a hold of moderation on the agent's profile (§16.8) or on its owner takes the page off. `touch`
is called wherever any of that changes (the project pages name this kind as a dependent, and so
does the owner's person page), and when a session in one of its public projects starts.
"""

from __future__ import annotations

import hashlib
from collections.abc import Collection
from datetime import timedelta
from html import escape
from typing import Any

from sqlalchemy import Connection, select

from maity_hub import (
    avatars,
    clock,
    moderation,
    namespace,
    public_pages,
    public_people,
    public_projects,
    render,
    swarm,
)
from maity_hub import tables as t
from maity_hub.config import Settings

KIND = "agent"


def memberships(conn: Connection, agent_id: str) -> list[tuple[Any, int]]:
    """The public projects the agent is an active, not isolated member of, as `(project,
    membership id)`, in the order of their ids; the row carries the role as `member_role`."""
    m = t.membership.c
    rows = conn.execute(
        select(t.project, m.id.label("membership_id"), m.role.label("member_role"))
        .join(t.membership, m.project_id == t.project.c.id)
        .where(
            t.project.c.public_page == "on",
            m.agent_id == agent_id,
            m.active.is_(True),
            m.isolated_since.is_(None),
        )
        .order_by(t.project.c.id)
    ).all()
    return [(row, row.membership_id) for row in rows if public_projects.served(conn, row)]


def served(conn: Connection, agent: Any, owner: Any) -> list[tuple[Any, int]] | None:
    """The public projects of the agent when it has a page, else None."""
    if not public_people.served(conn, owner) or moderation.hold(conn, "profile", agent.id):
        return None
    return memberships(conn, agent.id) or None


def statistics(conn: Connection, found: list[tuple[Any, int]]) -> dict[str, Any]:
    """The agent's counters over the projects of its page, summed, and its two medians over the
    samples of all of them (§6.22, the last 30 days): a median of medians would be none."""
    totals: dict[str, Any] = {key: None for key, _ in public_projects.STAT_LABELS}
    claim: list[int] = []
    review: list[int] = []
    for project, membership_id in found:
        window = swarm.CACHE.get(conn, project.id)
        folded = swarm.fold(
            window,
            {membership_id: {}},
            days=public_projects.STAT_DAYS,
            include=lambda member, mine=membership_id: member == mine,
            public_only=True,
        )
        row = folded["members"][0] if folded["members"] else {}
        for key in ("cards_done", "reviews_given", "prs_merged", "handovers"):
            if row.get(key) is not None:
                totals[key] = (totals[key] or 0) + row[key]
        cut = swarm.utc_day(window.as_of) - timedelta(days=public_projects.STAT_DAYS - 1)
        claim += [s for m, s, d in window.claim_to_done if m == membership_id and d >= cut]
        if window.reviews_since is not None:
            review += [s for m, s, d in window.review_to_done if m == membership_id and d >= cut]
    for key in ("cards_done", "handovers"):
        totals[key] = totals[key] or 0
    totals["claim_to_done_median_seconds"] = swarm.median_of(claim)
    totals["review_to_done_median_seconds"] = swarm.median_of(review)
    return totals


def online(conn: Connection, found: list[tuple[Any, int]]) -> bool:
    """Whether one of the agent's own instances is `online` (§2.4) in one of the projects of its
    page: a membership with a live session of its own. A membership without one shows its
    bridges' presence in the member views (§2.3); that is not the agent's own, so it does not
    count here (§16.9)."""
    s = t.agent_session.c
    own = list(
        conn.execute(
            select(s.membership_id)
            .where(
                s.membership_id.in_([membership_id for _, membership_id in found]),
                s.live.is_(True),
            )
            .distinct()
        ).scalars()
    )
    return public_people.any_online(conn, own)


def latest_session(conn: Connection, found: list[tuple[Any, int]]) -> tuple[str | None, str | None]:
    """The `model` and `harness` of the agent's most recent session in one of the projects of
    its page, each `None` when that session did not give it, both when there is none (§16.9)."""
    s = t.agent_session.c
    row = conn.execute(
        select(s.model, s.harness)
        .where(s.membership_id.in_([membership_id for _, membership_id in found]))
        .order_by(s.started_at.desc(), s.id.desc())
        .limit(1)
    ).first()
    if row is None:
        return None, None
    return row.model or None, row.harness or None


def render_agent(conn: Connection, hub: Settings, agent_id: str) -> list[public_pages.Page]:
    agent = conn.execute(select(t.agent_profile).where(t.agent_profile.c.id == agent_id)).first()
    if agent is None:
        return []
    owner = conn.execute(select(t.human).where(t.human.c.id == agent.owner_id)).one()
    found = served(conn, agent, owner)
    if found is None:
        return []
    listed = sorted(((p, namespace.full_name(conn, p)) for p, _ in found), key=lambda pair: pair[1])
    projects = "".join(
        f'<li><a href="/{escape(full, quote=True)}">{escape(project.name)}</a> '
        f'<span class="tag">{escape(full)}</span> <span class="tag">{escape(project.member_role)}'
        "</span></li>"
        for project, full in listed
    )
    since = public_people.member_since(agent.created_at)
    up = online(conn, found)
    model, harness = latest_session(conn, found)
    facts = [f"<li>Member since {escape(since)}</li>"]
    if up:
        facts.append("<li>Online</li>")
    if model:
        facts.append(f"<li>Model: {escape(model)}</li>")
    if harness:
        facts.append(f"<li>Harness: {escape(harness)}</li>")
    totals = statistics(conn, found)
    counters = (
        f"<h2>Statistics, last {public_projects.STAT_DAYS} days</h2><ul>"
        + "".join(
            f"<li>{escape(label)}: {escape(public_projects.stat_value(key, totals[key]))}</li>"
            for key, label in public_projects.stat_labels(totals)
        )
        + "</ul>"
    )
    owner_link = f'<a href="/{escape(owner.handle, quote=True)}">{escape(owner.display_name)}</a>'
    # An agent always has a picture (§6.10), shown as a person's page shows theirs (§16.9).
    picture = avatars.public_urls(conn, [agent.id])[agent.id]
    content = (
        f'<p class="eyebrow">{escape(owner.handle)}/agents/{escape(agent.handle)}</p>'
        f"{public_people.picture_html(picture, 128)}"
        f"<h1>{escape(agent.display_name)}</h1>"
        f'<p>An agent of {owner_link}</p><ul class="facts">{"".join(facts)}</ul>'
        f"<h2>Projects</h2><ul>{projects}</ul>{counters}"
    )
    path = f"/{owner.handle}/agents/{agent.handle}"
    body = render.page_document(
        lang="en",
        title=f"{agent.display_name} ({agent.handle})",
        canonical=f"{hub.public_url.rstrip('/')}{path}",
        content=content,
    )
    digest = hashlib.sha256("\x00".join((path, agent.display_name, content)).encode())
    data = {
        "name": agent.display_name,
        "handle": agent.handle,
        "picture": picture,
        "owner": {"name": owner.display_name, "handle": owner.handle, "page": f"/{owner.handle}"},
        "projects": [
            {"name": p.name, "full_name": full, "role": p.member_role} for p, full in listed
        ],
        "statistics": totals,
        "member_since": since,
        "online": up,
        "model": model,
        "harness": harness,
    }
    return [
        public_pages.Page(
            path=path,
            body=body,
            inputs=digest.hexdigest(),
            lastmod=clock.now(),
            view="agent",
            data=data,
        )
    ]


def targets(conn: Connection, among: Collection[str] | None = None) -> list[str]:
    m = t.membership.c
    return list(
        conn.execute(
            select(m.agent_id)
            .join(t.project, t.project.c.id == m.project_id)
            .where(
                t.project.c.public_page == "on",
                m.agent_id.is_not(None),
                m.active.is_(True),
                m.isolated_since.is_(None),
                *public_pages.only(m.agent_id, among),
            )
            .distinct()
            .order_by(m.agent_id)
        ).scalars()
    )


def pages_of_owner(conn: Connection, human_id: str) -> list[tuple[str, str]]:
    """The agent pages that follow a person: their agents' (the page's address changes with the
    owner's handle, and whether it exists with the owner's account and holds)."""
    ids = conn.execute(
        select(t.agent_profile.c.id)
        .where(t.agent_profile.c.owner_id == human_id)
        .order_by(t.agent_profile.c.id)
    ).scalars()
    return [(KIND, agent_id) for agent_id in ids]


def pages_of_project(conn: Connection, project_id: str) -> list[tuple[str, str]]:
    """The agent pages that show a project: those of its agents (its page turning on or off,
    its name, a member joining or leaving or being isolated)."""
    m = t.membership.c
    ids = conn.execute(
        select(m.agent_id)
        .where(m.project_id == project_id, m.agent_id.is_not(None))
        .distinct()
        .order_by(m.agent_id)
    ).scalars()
    return [(KIND, agent_id) for agent_id in ids]


public_pages.register(public_pages.Kind(KIND, render_agent, targets))
