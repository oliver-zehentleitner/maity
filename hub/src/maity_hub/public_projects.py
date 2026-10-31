"""A project's public page (docs/api.md §16.9): `GET /{owner}/{slug}` while the project's
`public_page` is `on`.

It shows the project's `name` and `full_name`, its state and the `public_about` text; the
members, the agents, the repository and the statistics follow in the next steps. A page is not
served for an archived project, for one a moderation hold stands on, or while its namespace
owner is suspended, waiting for approval or deleted, or an organisation that is suspended or
deleted. Whatever changes one of these calls `public_pages.touch` in its transaction.
"""

from __future__ import annotations

import hashlib
from html import escape
from typing import Any

from sqlalchemy import Connection, select

from maity_hub import (
    clock,
    landing,
    moderation,
    namespace,
    public_pages,
    public_people,
    render,
    swarm,
)
from maity_hub import tables as t
from maity_hub.config import Settings
from maity_hub.errors import invalid

KIND = "project"
ABOUT_MAX_BYTES = 4096  # 4 KiB (§16.9)


def about_problem(value: str) -> str | None:
    """Why a `public_about` may not be stored: `too_long`, `control_character`, or the `line N`
    of the first line the landing page's Markdown rules (§16.7) refuse; None when it is fine."""
    if len(value.encode()) > ABOUT_MAX_BYTES:
        return "too_long"
    if landing.CONTROL.search(value):
        return "control_character"
    return landing.markdown_problem(value)


def check_about(value: str | None) -> str | None:
    """The text to store, or `invalid` (`details.fields.public_about`); empty is none."""
    if not value:
        return None
    problem = about_problem(value)
    if problem is not None:
        raise invalid({"public_about": problem})
    return value


def _owner_served(conn: Connection, project: Any) -> bool:
    if project.owner_org_id is not None:
        org = conn.execute(select(t.org).where(t.org.c.id == project.owner_org_id)).first()
        return (
            org is not None
            and org.deleted_at is None
            and moderation.hold(conn, "org", org.id) is None
        )
    human = conn.execute(select(t.human).where(t.human.c.id == project.owner_human_id)).first()
    return bool(
        human is not None
        and human.account_status == "active"
        and human.deleted_at is None
        and human.suspended_at is None
    )


def served(conn: Connection, project: Any) -> bool:
    """Whether the project has a page now."""
    return bool(
        project.public_page == "on"
        and project.state != "archived"
        and moderation.hold(conn, "project", project.id) is None
        and _owner_served(conn, project)
    )


def team(conn: Connection, project_id: str) -> tuple[list[Any], list[Any], int]:
    """Who the page shows (§16.9): the human members whose own profile is public, the agents
    whose owner's profile is public, and the number of the agents it does not show. Active
    memberships only, in the order of the handles; an isolated agent (§6.28) is neither shown
    nor counted."""
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
    return humans, shown, len(agents) - len(shown)


STAT_DAYS = 30
_STAT_LABELS = (
    ("cards_done", "Cards done"),
    ("reviews_given", "Reviews given"),
    ("prs_merged", "Pull requests merged"),
    ("handovers", "Handovers"),
    ("claim_to_done_median_seconds", "Median, claim to done"),
    ("review_to_done_median_seconds", "Median, review to done"),
)


def agent_statistics(conn: Connection, project_id: str) -> dict[str, Any]:
    """The project's statistics reduced for the public (§16.9, §6.22): the last 30 days over
    the agents only, so that no human's contribution appears. `totals` (with
    `cards_done_per_day`) count every agent that is not isolated; `members` has a row, with its
    counters, for each agent the page names (a public owner profile, no hold)."""
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
    _, named, _ = team(conn, project_id)
    people = {
        by_agent[a.id]: {"handle": a.handle, "display_name": a.display_name}
        for a in named
        if a.id in by_agent
    }
    found = swarm.CACHE.get(conn, project_id)
    folded: dict[str, Any] = swarm.fold(
        found, people, days=STAT_DAYS, include=lambda member: member in agents
    )
    return {"totals": folded["totals"], "members": folded["members"]}


def _duration(seconds: int | None) -> str:
    if seconds is None:
        return "-"
    hours, rest = divmod(seconds, 3600)
    return f"{hours} h {rest // 60} min" if hours else f"{rest // 60} min"


def _value(key: str, value: Any) -> str:
    if key.endswith("seconds"):
        return _duration(value)
    return "-" if value is None else str(value)


def _per_day_html(series: list[dict[str, Any]]) -> str:
    """The cards done per day as bars: inline style only, the text of each day in its title."""
    peak = max((day["count"] for day in series), default=0) or 1
    bars = "".join(
        f'<span title="{escape(day["date"])}: {day["count"]}" style="display:inline-block;'
        f"width:6px;margin-right:2px;background:currentColor;opacity:.6;"
        f'height:{1 + 40 * day["count"] // peak}px"></span>'
        for day in series
    )
    return f'<p aria-label="Cards done per day, last {STAT_DAYS} days">{bars}</p>'


def _statistics_html(stats: dict[str, Any]) -> str:
    totals = stats["totals"]
    items = "".join(
        f"<li>{escape(label)}: {escape(_value(key, totals[key]))}</li>"
        for key, label in _STAT_LABELS
    )
    html = f"<h2>The agents, last {STAT_DAYS} days</h2><ul>{items}</ul>"
    html += f"<h3>Cards done per day</h3>{_per_day_html(totals['cards_done_per_day'])}"
    if stats["members"]:
        head = "".join(f"<th>{escape(label)}</th>" for _, label in _STAT_LABELS)
        body = "".join(
            f"<tr><td>{escape(row['display_name'])} ({escape(row['handle'])})</td>"
            + "".join(f"<td>{escape(_value(key, row[key]))}</td>" for key, _ in _STAT_LABELS)
            + "</tr>"
            for row in stats["members"]
        )
        html += f"<h3>Per agent</h3><table><tr><th>Agent</th>{head}</tr>{body}</table>"
    return html


def pages_of_member(conn: Connection, human_id: str) -> list[tuple[str, str]]:
    """The public project pages that show the person: a member, or the owner of an agent that
    is one (a person's profile turning private or public changes them, §16.9)."""
    m = t.membership.c
    agents = select(t.agent_profile.c.id).where(t.agent_profile.c.owner_id == human_id)
    ids = conn.execute(
        select(t.project.c.id)
        .join(t.membership, m.project_id == t.project.c.id)
        .where(
            t.project.c.public_page == "on",
            m.active.is_(True),
            (m.human_id == human_id) | m.agent_id.in_(agents),
        )
        .distinct()
        .order_by(t.project.c.id)
    ).scalars()
    return [(KIND, project_id) for project_id in ids]


def render_project(conn: Connection, hub: Settings, project_id: str) -> list[public_pages.Page]:
    project = conn.execute(select(t.project).where(t.project.c.id == project_id)).first()
    if project is None or not served(conn, project):
        return []
    full = namespace.full_name(conn, project)
    about = (
        f'<div class="about">{render.markdown(project.public_about, ugc=True)}</div>'
        if project.public_about
        else ""
    )
    # The repository only while the forge's last answer said it is public (§16.9).
    shown_url = project.repository_url if project.repository_public is True else None
    repository = ""
    if shown_url and landing.safe_target(shown_url):
        link = (
            f'<a href="{escape(shown_url, quote=True)}" rel="nofollow ugc">{escape(shown_url)}</a>'
        )
        repository = f"<p>{link}</p>"
    humans, agents, others = team(conn, project.id)
    people = "".join(
        f'<li><a href="/{escape(h.handle, quote=True)}">{escape(h.display_name)}</a></li>'
        for h in humans
    )
    bots = "".join(f"<li>{escape(a.display_name)} ({escape(a.handle)})</li>" for a in agents)
    more = f"<p>and {others} more agent{'s' if others != 1 else ''}</p>" if others else ""
    team_html = (f"<h2>People</h2><ul>{people}</ul>" if people else "") + (
        f"<h2>Agents</h2><ul>{bots}</ul>{more}" if bots else more
    )
    statistics_html = _statistics_html(agent_statistics(conn, project.id))
    content = (
        f'<p class="eyebrow">{escape(full)}</p><h1>{escape(project.name)}</h1>'
        f'<p class="tag">{escape(project.state)}</p>{about}{repository}{team_html}{statistics_html}'
    )
    path = f"/{full}"
    body = render.page_document(
        lang="en",
        title=f"{project.name} ({full})",
        canonical=f"{hub.public_url.rstrip('/')}{path}",
        content=content,
    )
    digest = hashlib.sha256(
        "\x00".join(
            (
                full,
                project.name,
                project.state,
                project.public_about or "",
                shown_url or "",
                team_html,
                statistics_html,
            )
        ).encode()
    )
    return [public_pages.Page(path=path, body=body, inputs=digest.hexdigest(), lastmod=clock.now())]


def targets(conn: Connection) -> list[str]:
    return list(
        conn.execute(
            select(t.project.c.id).where(t.project.c.public_page == "on").order_by(t.project.c.id)
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
    """The pages of every project the organisation owns: it was suspended or deleted."""
    for project_id in conn.execute(
        select(t.project.c.id).where(
            t.project.c.owner_org_id == org_id, t.project.c.public_page == "on"
        )
    ).scalars():
        public_pages.touch(conn, KIND, project_id, removal=removal)


public_pages.register(public_pages.Kind(KIND, render_project, targets))
