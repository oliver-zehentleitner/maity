"""An agent's public page (docs/api.md §16.9): `GET /{owner}/agents/{handle}` while the owner's
`public_profile` is on and the agent is an active member of at least one project with a public
page.

It shows the agent's `display_name` and `handle`, its owner with a link to their page, the public
projects it is a member of, each with a link, and its statistics over those projects for the last
30 days as §6.22 counts them per member. No presence, no instances, no model or harness, no
briefing. An agent that is isolated in a project (§6.28) is not a member of it here; a hold of
moderation on the agent's profile (§16.8) or on its owner takes the page off. `touch` is called
wherever any of that changes (the project pages name this kind as a dependent, and so does the
owner's person page).
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from html import escape
from typing import Any

from sqlalchemy import Connection, select

from maity_hub import (
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
    membership id)`, in the order of their ids."""
    m = t.membership.c
    rows = conn.execute(
        select(t.project, m.id.label("membership_id"))
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
        )
        row = folded["members"][0] if folded["members"] else {}
        for key in ("cards_done", "reviews_given", "prs_merged", "handovers"):
            if row.get(key) is not None:
                totals[key] = (totals[key] or 0) + row[key]
        cut = swarm.utc_day(window.as_of) - timedelta(days=public_projects.STAT_DAYS - 1)
        claim += [s for m, s, d in window.claim_to_done if m == membership_id and d >= cut]
        if window.reviews_since is not None:
            review += [s for m, s, d in window.review_to_done if m == membership_id and d >= cut]
    for key in ("cards_done", "prs_merged", "handovers"):
        totals[key] = totals[key] or 0
    totals["claim_to_done_median_seconds"] = swarm.median_of(claim)
    totals["review_to_done_median_seconds"] = swarm.median_of(review)
    return totals


def render_agent(conn: Connection, hub: Settings, agent_id: str) -> list[public_pages.Page]:
    agent = conn.execute(select(t.agent_profile).where(t.agent_profile.c.id == agent_id)).first()
    if agent is None:
        return []
    owner = conn.execute(select(t.human).where(t.human.c.id == agent.owner_id)).one()
    found = served(conn, agent, owner)
    if found is None:
        return []
    projects = "".join(
        f'<li><a href="/{escape(full, quote=True)}">{escape(project.name)}</a> '
        f'<span class="tag">{escape(full)}</span></li>'
        for project, full in sorted(
            ((p, namespace.full_name(conn, p)) for p, _ in found), key=lambda pair: pair[1]
        )
    )
    totals = statistics(conn, found)
    counters = (
        f"<h2>Statistics, last {public_projects.STAT_DAYS} days</h2><ul>"
        + "".join(
            f"<li>{escape(label)}: {escape(public_projects.stat_value(key, totals[key]))}</li>"
            for key, label in public_projects.STAT_LABELS
        )
        + "</ul>"
    )
    owner_link = f'<a href="/{escape(owner.handle, quote=True)}">{escape(owner.display_name)}</a>'
    content = (
        f'<p class="eyebrow">{escape(owner.handle)}/agents/{escape(agent.handle)}</p>'
        f"<h1>{escape(agent.display_name)}</h1>"
        f"<p>An agent of {owner_link}</p><h2>Projects</h2><ul>{projects}</ul>{counters}"
    )
    path = f"/{owner.handle}/agents/{agent.handle}"
    body = render.page_document(
        lang="en",
        title=f"{agent.display_name} ({agent.handle})",
        canonical=f"{hub.public_url.rstrip('/')}{path}",
        content=content,
    )
    digest = hashlib.sha256("\x00".join((path, agent.display_name, content)).encode())
    return [public_pages.Page(path=path, body=body, inputs=digest.hexdigest(), lastmod=clock.now())]


def targets(conn: Connection) -> list[str]:
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
            )
            .distinct()
            .order_by(m.agent_id)
        ).scalars()
    )


def pages_of_owner(conn: Connection, human_id: str) -> list[tuple[str, str]]:
    """The agent pages that follow a person: their agents' (the page's address and whether it
    exists change with the owner's profile and handle)."""
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
