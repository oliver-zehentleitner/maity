"""The public project pages in the dashboard's design (docs/api.md §16.9): the HTML of a stored
page as a pure function of its `kind`, its `data` and its `path`.

The structure is the one `web/js/visitor.js` draws for a visitor without a session: the same
elements, classes and order, the same `data-kind` and the same static `aria` attributes, so
the page a crawler and a reader without script get is the page the dashboard then draws over
it, styled by the frame's stylesheets (`landing_assets/public-sections.css`) and by nothing of
its own. `page` takes only what the visitors' route serves as `data`, so the HTML cannot show
anything the data does not, nor the other way round (hub/context/public-pages.md). The person,
agent and organisation pages are not drawn here (tsk-2t7efzj1p8zt).

The fixed words are English, from `web/i18n/en.json` under the same keys (`WORDS`); times are
UTC in one fixed English form, `Nov 15, 2026, 19:39 UTC` (`when`), numbers plain digits.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from html import escape
from typing import Any
from urllib.parse import quote

from maity_hub import landing, render

# The kinds drawn here: a project's Overview, its four views and a card's page.
KINDS = ("project", "board", "team", "organisation", "why", "card")
# The kinds whose content stands as sections across the page; a card's stands in a column.
ACROSS = ("project", "board", "team", "organisation", "why")

# The dashboard's English words, each under its key in web/i18n/en.json, so that a check can
# compare them. A dict is a plural: `one` and `other`.
WORDS: dict[str, Any] = {
    "nav.overview": "Overview",
    "nav.board": "Board",
    "nav.members": "Team",
    "nav.organisation": "Organisation",
    "nav.why": "Why",
    "visitor.stat.members": "Members",
    "visitor.stat.cards_done": "Cards done",
    "visitor.stat.reviews_given": "Reviews given",
    "visitor.stat.prs_merged": "Pull requests merged",
    "visitor.stat.handovers": "Handovers",
    "visitor.stat.window": "30 days",
    "visitor.note.incorporated": "worked in",
    "visitor.note.dismissed": "dismissed",
    "visitor.note.edited": "edited by {who}, {at}",
    "visitor.note.edited_reason": "edited by {who}, {at}: {reason}",
    "visitor.holder.member": "A member",
    "visitor.holder.agent": "An agent",
    "visitor.online": "Online",
    "visitor.others": "Others",
    "visitor.now": "Right now",
    "visitor.now.people": {"one": "{count} person", "other": "{count} people"},
    "visitor.now.agents": {"one": "{count} agent", "other": "{count} agents"},
    "visitor.now.both": "{people} · {agents} online",
    "visitor.now.one": "{who} online",
    "visitor.now.working": "working on this project",
    "visitor.now.more": "+{count}",
    "visitor.now.more.label": {"one": "and {count} more", "other": "and {count} more"},
    "visitor.team.both": "{people} and {agents}",
    "visitor.team.all": {"one": "{count} member →", "other": "All {count} members →"},
    "visitor.recently": "Recently",
    "visitor.merged": "Recently merged",
    "visitor.merged.window": "Pull requests and decisions of the last 7 days",
    "visitor.merged.pill": "Merged",
    "visitor.merged.by": "by {author}",
    "visitor.merged.touches": "touches {areas}",
    "visitor.why.unread": "The Keep the Why of this project is not public, or not read yet.",
    "visitor.why.entries": "{count} entries",
    "visitor.why.family": "Family",
    "visitor.why.attention": "Needs attention",
    "cards.column.proposed": "Proposed",
    "cards.column.open": "Open",
    "cards.column.in_progress": "In progress",
    "cards.column.blocked": "Blocked",
    "cards.column.review": "Review",
    "cards.column.done": "Done",
    "cards.column.cancelled": "Cancelled",
    "cards.label.fix": "fix",
    "cards.label.feature": "feature",
    "cards.label.chore": "chore",
    "cardpanel.notes": "Notes",
    "jfa.redacted": "Removed.",
    "overview.board.cards": {"one": "{count} card", "other": "{count} cards"},
    "project.link.repository": "Repository",
    "project.link.issues": "Issues",
    "project.link.wiki": "Wiki",
    "project.link.discussions": "Discussions",
    "state.plan": "Plan",
    "state.build": "Build",
    "state.review": "Review",
    "state.launch": "Launch",
    "state.archived": "Archived",
    "role.coder": "Coder",
    "role.reviewer": "Reviewer",
    "role.tester": "Tester",
    "role.manager": "Manager",
    "role.designer": "Designer",
    "role.writer": "Writer",
    "role.ops": "Ops",
    "role.proxy": "Proxy",
    "role.expert": "Expert",
    "role.red_team": "Red team",
    "role.blue_team": "Blue team",
    "role.purple_team": "Purple team",
    "why.status.needs_review": "needs review",
    "why.status.pending_confirmation": "pending confirmation",
    "why.status.open": "open",
    "why.status.active": "active",
    "why.status.superseded": "superseded",
    "why.status.other": "other",
    "report.sign_in": "Sign in to report",
    "report.label.project": "Report this project to the instance's admins",
    "report.label.card": "Report this card to the instance's admins",
}

VIEWS = (
    ("", "nav.overview"),
    ("/board", "nav.board"),
    ("/team", "nav.members"),
    ("/organisation", "nav.organisation"),
    ("/why", "nav.why"),
)
COUNTERS = ("cards_done", "reviews_given", "prs_merged", "handovers")
NOTE_STATES = ("incorporated", "dismissed")
# A Keep the Why status as the export writes it, and its word's key (web/js/why.js).
WHY_STATUS = {
    "needs-review": "why.status.needs_review",
    "pending-confirmation": "why.status.pending_confirmation",
    "open": "why.status.open",
    "active": "why.status.active",
    "superseded": "why.status.superseded",
    "other": "why.status.other",
}
FORGE_HOSTS = {"github.com": "GitHub", "gitlab.com": "GitLab"}
HOST = re.compile(r"^https://(?:www\.)?([^/?#:]+)(?::\d+)?([^?#]*)", re.IGNORECASE)
REPO_PAGES = {"issues", "wiki", "discussions"}
AGENT_PAGE = re.compile(r"^/[^/]+/agents/[^/]+$")
STACK = 8  # faces in Right now
TEAM_CARDS = 12  # member cards on the Overview
# GitHub's mark (Octicons, MIT), as visitor.js draws it beside the repository.
GITHUB_MARK = (
    "M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01"
    "-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 "
    "1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 "
    "0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 "
    "0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 "
    "3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8"
    ".01 8.01 0 0016 8c0-4.42-3.58-8-8-8z"
)


# --- words and small parts -----------------------------------------------------------------


def t(key: str, **values: Any) -> str:
    """A word of `WORDS`, plain text (escape it where it goes into HTML); a plural by `count`."""
    word = WORDS[key]
    if isinstance(word, dict):
        word = word["one" if values.get("count") == 1 else "other"]
    return str(word).format(**values)


def _e(value: Any) -> str:
    return escape(str(value), quote=True)


def word_of(prefix: str, value: str | None) -> str:
    """A value of the contract in words (`state.build`); one without a word stays as it comes."""
    key = f"{prefix}.{value}"
    return t(key) if key in WORDS else str(value)


def when(value: str) -> str:
    """An RFC 3339 time as `Nov 15, 2026, 19:39 UTC`; an unreadable value stays as given."""
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except (AttributeError, ValueError):
        return str(value)
    return f"{moment:%b} {moment.day}, {moment:%Y, %H:%M} UTC"


def monogram(name: str | None, slug: str | None) -> str:
    """The first letter of `name`, else the first character of `slug`, in upper case."""
    letter = next((c for c in name or "" if c.isalpha()), (slug or "")[:1])
    return letter.upper()


def is_route(page: Any) -> bool:
    return isinstance(page, str) and page.startswith("/") and landing.safe_target(page)


def safe_url(url: Any) -> str | None:
    return url if isinstance(url, str) and url and landing.safe_target(url) else None


def external(url: Any, label: str) -> str | None:
    safe = safe_url(url)
    return f'<a href="{_e(safe)}" rel="nofollow ugc">{_e(label)}</a>' if safe else None


def who(person: dict[str, Any]) -> str:
    name = _e(person.get("name") or "")
    page = person.get("page")
    return f'<a href="{_e(page)}">{name}</a>' if is_route(page) else f"<span>{name}</span>"


def holder_label(holder: Any) -> str | None:
    if not holder:
        return None
    if holder == "member":
        return f'<span class="muted">{_e(t("visitor.holder.member"))}</span>'
    if holder == "agent":
        return f'<span class="muted">{_e(t("visitor.holder.agent"))}</span>'
    return who(holder)


def face(person: dict[str, Any], kind: str, px: int) -> str:
    """A member's picture at the size the hub serves for it, or their letter where none."""
    cls = f"av {kind} av-{px}"
    picture = person.get("picture")
    if not isinstance(picture, str) or not picture:
        letter = monogram(person.get("name"), person.get("handle"))
        return f'<span class="{cls} ini" aria-hidden="true">{_e(letter)}</span>'
    src = f"{picture}{'&' if '?' in picture else '?'}s={128 if px > 32 else 64}"
    return f'<img class="{cls}" src="{_e(src)}" alt="" width="{px}" height="{px}" decoding="async">'


def _time(at: str) -> str:
    return f'<time datetime="{_e(at)}">{_e(when(at))}</time>'


def headcount(people: int, agents: int) -> str | None:
    p = t("visitor.now.people", count=people) if people else None
    a = t("visitor.now.agents", count=agents) if agents else None
    return t("visitor.team.both", people=p, agents=a) if p and a else p or a


# --- the hero, the band and the tab bar ------------------------------------------------------


def short_label(url: str, repo: str | None) -> str:
    """A project link's word in the link row: a page of the repository by its word, any other
    by its host and path."""
    if repo:
        base = re.sub(r"\.git$", "", repo.rstrip("/"))
        if url.lower().startswith(base.lower() + "/"):
            page = re.split(r"[/?#]", url[len(base) + 1 :])[0].lower()
            if page in REPO_PAGES:
                return t(f"project.link.{page}")
    found = HOST.match(url)
    return (found[1] + found[2]).rstrip("/") if found else url


def report_row(path: str, what: str) -> str:
    """The report control where the dashboard has it: a link to the sign-in that comes back to
    the page with `?report` (render.report_link's semantics), and the form's empty slot."""
    back = quote(f"{path}?report", safe="")
    label = t(f"report.label.{what}")
    return (
        f'<p class="report-row"><a class="button small report-open" href="/login?next={back}"'
        f' rel="nofollow" title="{_e(label)}">{_e(t("report.sign_in"))}</a></p>'
        '<div class="report-slot"></div>'
    )


def right_now(d: dict[str, Any]) -> str:
    online = d.get("online")
    if not online or not (online.get("humans", 0) > 0 or online.get("agents", 0) > 0):
        return ""
    people = t("visitor.now.people", count=online["humans"])
    agents = t("visitor.now.agents", count=online["agents"])
    if online["humans"] > 0 and online["agents"] > 0:
        said = t("visitor.now.both", people=people, agents=agents)
    else:
        said = t("visitor.now.one", who=people if online["humans"] > 0 else agents)
    named = online.get("named") or []
    bots = {a.get("page") for a in d.get("agents") or []}
    faces = []
    for p in named[:STACK]:
        pic = face(p, "ag" if p.get("page") in bots else "hu", 30)
        name = _e(p.get("name") or "")
        if is_route(p.get("page")):
            faces.append(f'<a href="{_e(p["page"])}" title="{name}" aria-label="{name}">{pic}</a>')
        else:
            faces.append(f'<span role="img" title="{name}" aria-label="{name}">{pic}</span>')
    more = len(named) - STACK
    if more > 0:
        label = _e(t("visitor.now.more.label", count=more))
        said_more = _e(t("visitor.now.more", count=more))
        faces.append(f'<span class="more" title="{label}">{said_more}</span>')
    stack = f'<div class="stack">{"".join(faces)}</div>' if named else ""
    return (
        f'<div class="ph-live"><p class="eyebrow">{_e(t("visitor.now"))}</p>'
        f'<p class="big"><i class="dot" aria-hidden="true"></i>{_e(said)}</p>{stack}'
        f'<p class="muted">{_e(t("visitor.now.working"))}</p></div>'
    )


def hero(kind: str, d: dict[str, Any], path: str, base: str) -> str:
    owner, slug = base.strip("/").split("/")[:2]
    overview = kind == "project"
    title = d.get("name") if overview else d.get("title") if kind == "card" else slug
    crumb_slug = _e(slug) if path == base else f'<a href="{_e(base)}">{_e(slug)}</a>'
    mark = (
        ""
        if kind == "card"
        else f'<span class="pmark" aria-hidden="true">'
        f'{_e(monogram(d.get("name") if overview else "", slug))}</span>'
    )
    state = f'<span class="chip state">{_e(word_of("state", d.get("state")))}</span>'
    repo = safe_url(d.get("repository_url")) if overview else None
    button = ""
    if repo:
        found = HOST.match(repo)
        forge = FORGE_HOSTS.get(found[1].lower()) if found else None
        icon = (
            '<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false" class="ico">'
            f'<path d="{GITHUB_MARK}" fill="currentColor"></path></svg>'
            if forge == "GitHub"
            else ""
        )
        button = (
            f'<a class="btn btn-secondary" href="{_e(repo)}" rel="nofollow ugc" title="{_e(repo)}">'
            f'{icon}{_e(forge or t("project.link.repository"))}</a>'
        )
    links = []
    for url in (d.get("links") or []) if overview else []:
        safe = safe_url(url)
        if safe:
            links.append(
                f'<a href="{_e(safe)}" rel="nofollow ugc" title="{_e(safe)}">'
                f"{_e(short_label(safe, repo))}</a>"
            )
    about = d.get("about") if overview else None
    return (
        '<section class="phero hero dz"><div class="wrap"><div class="ph-main">'
        f'<p class="crumb">{_e(owner)} / {crumb_slug}</p>'
        f'<div class="ph-title">{mark}<h1>{_e(title or "")}</h1>{state if overview else ""}</div>'
        + (f'<div class="sub about">{render.markdown(about, ugc=True)}</div>' if about else "")
        + f'<div class="cta"><span class="cta-slot"></span>{button}</div>'
        + (f'<p class="plinks">{" · ".join(links)}</p>' if links else "")
        + report_row(path, "card" if kind == "card" else "project")
        + "</div>"
        + (right_now(d) if overview else "")
        + "</div></section>"
    )


def band(d: dict[str, Any]) -> str:
    totals = (d.get("statistics") or {}).get("totals") or {}
    figures = [(t("visitor.stat.members"), d.get("members"), False)] + [
        (t(f"visitor.stat.{key}"), totals.get(key), True) for key in COUNTERS
    ]
    shown = [
        f'<div class="stat"><b>{n}</b><span class="label">{_e(label)}</span>'
        + (f'<small>{_e(t("visitor.stat.window"))}</small>' if window else "")
        + "</div>"
        for label, n, window in figures
        if isinstance(n, int) and not isinstance(n, bool) and n > 0
    ]
    if not shown:
        return ""
    return f'<section class="band"><div class="wrap stats5">{"".join(shown)}</div></section>'


def tab_bar(kind: str, path: str, base: str, title: str) -> str:
    tabs = "".join(
        f'<a href="{_e(base + view)}" class="view-tab"'
        + (
            ' aria-current="page"'
            if base + view == path or (kind == "card" and view == "/board")
            else ""
        )
        + f">{_e(t(key))}</a>"
        for view, key in VIEWS
    )
    return f'<nav class="ptabs" aria-label="{_e(title)}"><div class="wrap">{tabs}</div></nav>'


# --- the sections ----------------------------------------------------------------------------


def tab_section(kind: str, title: str, note: str | None, parts: str) -> str:
    return (
        f'<section class="sec tab-sec {kind}-sec"><div class="wrap"><div class="sec-h">'
        f"<h2>{_e(title)}</h2>"
        + (f'<p class="muted">{_e(note)}</p>' if note else "")
        + f"</div>{parts}</div></section>"
    )


def member_card(p: dict[str, Any], kind: str, online: bool) -> str:
    facts = ""
    if p.get("role"):
        facts += f'<span class="chip role">{_e(word_of("role", p["role"]))}</span>'
    if kind == "ag" and p.get("harness"):
        facts += f'<span class="h">{_e(p["harness"])}</span>'
    inner = (
        face(p, kind, 44)
        + f'<span class="mc-t"><b>{_e(p.get("name") or "")}</b>'
        + f'<small>@{_e(p.get("handle") or "")}</small>'
        + (f'<span class="mc-m">{facts}</span>' if facts else "")
        + "</span>"
    )
    if online:
        word = _e(t("visitor.online"))
        inner += f'<i class="dot" role="img" aria-label="{word}" title="{word}"></i>'
    if is_route(p.get("page")):
        return f'<a class="mcard" href="{_e(p["page"])}">{inner}</a>'
    return f'<div class="mcard">{inner}</div>'


def team_section(d: dict[str, Any], base: str) -> str:
    people, agents = d.get("people") or [], d.get("agents") or []
    everyone = [(p, "hu") for p in people] + [(a, "ag") for a in agents]
    if not everyone:
        return ""
    up = {p.get("page") for p in ((d.get("online") or {}).get("named") or [])}
    line = headcount(len(people), len(agents))
    members = d.get("members")
    more = (
        f'<a class="more-l" href="{_e(base + "/team")}">'
        f'{_e(t("visitor.team.all", count=members))}</a>'
        if isinstance(members, int) and not isinstance(members, bool)
        else ""
    )
    cards = "".join(member_card(p, kind, p.get("page") in up) for p, kind in everyone[:TEAM_CARDS])
    return (
        '<section class="sec team-cards"><div class="wrap"><div class="sec-h">'
        f'<h2>{_e(t("nav.members"))}</h2><p class="muted">{_e(line or "")}</p>{more}</div>'
        f'<div class="mgrid">{cards}</div></div></section>'
    )


def pr_card(e: dict[str, Any]) -> str:
    m = e.get("merge") or {}
    url = safe_url(e.get("url"))
    facts = []
    if m.get("author"):
        facts.append(t("visitor.merged.by", author=m["author"]))
    if isinstance(m.get("areas"), list) and m["areas"]:
        facts.append(t("visitor.merged.touches", areas=", ".join(m["areas"])))
    number = m.get("pr")
    inner = (
        '<span class="pr-h">'
        + (
            f'<span class="num">#{number}</span>'
            if isinstance(number, int) and not isinstance(number, bool)
            else ""
        )
        + f'<span class="merged">{_e(t("visitor.merged.pill"))}</span>{_time(e["at"])}</span>'
        + f'<b>{_e(m.get("title") or e.get("text") or "")}</b>'
        + (f"<small>{_e(' · '.join(facts))}</small>" if facts else "")
    )
    if url:
        return f'<a class="pr" href="{_e(url)}" rel="nofollow ugc">{inner}</a>'
    return f'<div class="pr">{inner}</div>'


def recently(ticker: list[dict[str, Any]] | None) -> str:
    if not ticker:
        return ""
    merges = [e for e in ticker if e.get("type") == "merge"]
    others = [e for e in ticker if e.get("type") != "merge"]
    heading = t("visitor.merged") if merges else t("visitor.recently")
    return (
        '<section class="sec alt recently"><div class="wrap"><div class="sec-h">'
        f'<h2>{_e(heading)}</h2><p class="muted">{_e(t("visitor.merged.window"))}</p></div>'
        + (f'<div class="prgrid">{"".join(pr_card(e) for e in merges)}</div>' if merges else "")
        + (
            '<ul class="dec">'
            + "".join(
                f'<li>{_time(e["at"])}<span>{_e(e.get("text") or "")}</span></li>' for e in others
            )
            + "</ul>"
            if others
            else ""
        )
        + "</div></section>"
    )


def board(d: dict[str, Any], base: str) -> str:
    columns = d.get("columns") or []
    empty = not any(col["cards"] for col in columns)
    region = f' role="region" tabindex="0" aria-label="{_e(t("nav.board"))}"' if empty else ""
    parts = []
    for col in columns:
        name = word_of("cards.column", col["status"])
        cards = "".join(
            f'<article class="card" data-card="{_e(c["id"])}" aria-label="{_e(c["title"])}">'
            f'<header><a class="card-id" href="{_e(base + "/tasks/" + c["id"])}">{_e(c["id"])}</a>'
            + (
                f'<span class="chip label">{_e(word_of("cards.label", c["label"]))}</span>'
                if c.get("label")
                else ""
            )
            + f'</header><h4>{_e(c["title"])}</h4>{holder_label(c.get("holder")) or ""}</article>'
            for c in col["cards"]
        )
        parts.append(
            f'<section class="column" data-status="{_e(col["status"])}" aria-label="{_e(name)}">'
            f'<h3>{_e(name)} ({len(col["cards"])})</h3>{cards}</section>'
        )
    count = sum(len(col["cards"]) for col in columns)
    return tab_section(
        "board",
        t("nav.board"),
        t("overview.board.cards", count=count),
        f'<div class="columns"{region}>{"".join(parts)}</div>',
    )


def team(d: dict[str, Any]) -> str:
    shown = d.get("shown") or []
    named = [(p, "hu") for p in shown if not AGENT_PAGE.match(p.get("page") or "")] + [
        (p, "ag") for p in shown if AGENT_PAGE.match(p.get("page") or "")
    ]
    people = sum(1 for _, kind in named if kind == "hu")
    others = d.get("others") or []
    parts = (
        f'<div class="mgrid">{"".join(member_card(p, k, False) for p, k in named)}</div>'
        if named
        else ""
    )
    if others:
        parts += (
            f'<h3>{_e(t("visitor.others"))}</h3><ul class="role-counts">'
            + "".join(
                f'<li><b>{_e(o["count"])}</b>'
                f'<span class="chip role">{_e(word_of("role", o["role"]))}</span></li>'
                for o in others
            )
            + "</ul>"
        )
    return tab_section("team", t("nav.members"), headcount(people, len(named) - people), parts)


def organisation(d: dict[str, Any]) -> str:
    nodes = d.get("nodes") or []

    def below(index: int | None) -> list[dict[str, Any]]:
        return [n for n in nodes if n.get("reports_to") == index]

    def card(n: dict[str, Any]) -> str:
        role = f'<span class="chip role">{_e(word_of("role", n.get("role")))}</span>'
        p = n.get("person")
        if not p:
            return f'<span class="onode anon">{role}</span>'
        agent = bool(AGENT_PAGE.match(p.get("page") or ""))
        inner = (
            face(p, "ag" if agent else "hu", 30)
            + f'<span class="mc-t"><b>{_e(p.get("name") or "")}</b>'
            + f'<small>@{_e(p.get("handle") or "")}</small></span>{role}'
        )
        if is_route(p.get("page")):
            return f'<a class="onode" href="{_e(p["page"])}">{inner}</a>'
        return f'<span class="onode">{inner}</span>'

    def tree(found: list[dict[str, Any]], seen: frozenset[int]) -> str:
        """A line back to a node already drawn is not followed: the answer is data."""
        if not found:
            return ""
        items = []
        for n in found:
            after = seen | {n["index"]}
            items.append(
                f"<li>{card(n)}"
                + tree([c for c in below(n["index"]) if c["index"] not in after], after)
                + "</li>"
            )
        return f"<ul>{''.join(items)}</ul>"

    named = [n for n in nodes if n.get("person")]
    people = sum(1 for n in named if not AGENT_PAGE.match(n["person"].get("page") or ""))
    return tab_section(
        "organisation",
        t("nav.organisation"),
        headcount(people, len(named) - people),
        f'<div class="otree">{tree(below(None), frozenset())}</div>',
    )


def why(d: dict[str, Any]) -> str:
    if not d.get("readable"):
        return tab_section(
            "why", t("nav.why"), None, f'<p class="muted">{_e(t("visitor.why.unread"))}</p>'
        )

    def kin(m: dict[str, Any]) -> str:
        label = m.get("name") or m.get("path") or ""
        url = safe_url(m.get("dashboard_url"))
        inner = (
            f'<span class="pmark sm" aria-hidden="true">{_e(monogram(label, m.get("path")))}</span>'
            f'<span class="mc-t"><b>{_e(label)}</b>'
            + (f'<small>{_e(m["path"])}</small>' if m.get("name") and m.get("path") else "")
            + "</span>"
        )
        if url:
            return f'<a class="mcard" href="{_e(url)}" rel="nofollow ugc">{inner}</a>'
        return f'<div class="mcard">{inner}</div>'

    family, attention = d.get("family") or [], d.get("attention") or []
    parts = ""
    if family:
        parts += (
            f'<h3>{_e(t("visitor.why.family"))}</h3>'
            f'<div class="mgrid">{"".join(kin(m) for m in family)}</div>'
        )
    if attention:
        items = []
        for a in attention:
            status = a.get("status")
            word = t(WHY_STATUS[status]) if status in WHY_STATUS else status
            title = a.get("title") or ""
            items.append(
                f'<li><span class="chip status">{_e(word)}</span>'
                f'<span>{external(a.get("link"), title) or _e(title)}</span></li>'
            )
        parts += (
            f'<h3>{_e(t("visitor.why.attention"))}</h3><ul class="dec att">{"".join(items)}</ul>'
        )
    entries = (d.get("summary") or {}).get("entries", 0)
    return tab_section("why", t("nav.why"), t("visitor.why.entries", count=entries), parts)


def _edit_mark(edited: dict[str, Any]) -> str:
    who = holder_label(edited.get("by")) or _e(t("visitor.holder.member"))
    at = _e(when(edited.get("at") or ""))
    key = "visitor.note.edited_reason" if edited.get("reason") else "visitor.note.edited"
    # The words around the holder's element, filled as the dashboard's `M.tn` fills them.
    parts = re.split(r"(\{who\}|\{at\}|\{reason\})", WORDS[key])
    fill = {"{who}": who, "{at}": at, "{reason}": _e(edited.get("reason") or "")}
    return "".join(fill.get(part, _e(part)) for part in parts)


def card(d: dict[str, Any]) -> str:
    head = (
        f'<p><span class="card-id">{_e(d["id"])}</span> '
        f'<span class="label-tag">{_e(word_of("cards.column", d["status"]))}</span>'
        + (
            f' <span class="label-tag">{_e(word_of("cards.label", d["label"]))}</span>'
            if d.get("label")
            else ""
        )
        + (f" {holder_label(d['holder'])}" if d.get("holder") else "")
        + "</p>"
    )
    body = d.get("body") or ""
    text = f'<div class="about">{render.markdown(body, ugc=True)}</div>' if body.strip() else ""
    notes = d.get("notes") or []
    items = []
    for n in notes:
        line = f'{holder_label(n.get("author")) or ""} · {_e(when(n["created_at"]))}'
        if n.get("state") in NOTE_STATES:
            line += " · " + _e(t(f"visitor.note.{n['state']}"))
        if n.get("edited") and not n.get("redacted"):
            line += " · " + _edit_mark(n["edited"])
        shown = (
            f'<p class="muted">{_e(t("jfa.redacted"))}</p>'
            if n.get("redacted")
            else f'<div class="about">{render.markdown(n.get("body") or "", ugc=True)}</div>'
        )
        items.append(f'<li data-note="{_e(n["id"])}"><p class="muted">{line}</p>{shown}</li>')
    listed = (
        f'<h2>{_e(t("cardpanel.notes"))}</h2><ol class="card-notes">{"".join(items)}</ol>'
        if notes
        else ""
    )
    return head + text + listed


# --- the page --------------------------------------------------------------------------------


def base_of(path: str) -> str:
    """The project's address under which a view of it stands: `/<owner>/<slug>`."""
    return "/" + "/".join(path.strip("/").split("/")[:2])


def page(kind: str, data: dict[str, Any], path: str) -> str:
    """The content of `<main>` for a stored page of `kind` at `path`, from its `data` alone."""
    if kind not in KINDS:
        raise ValueError(f"no design for the public page kind {kind}")
    base = base_of(path)
    title = data.get("title") if kind == "card" else data.get("name") or base[1:]
    if kind == "project":
        inner = team_section(data, base) + recently(data.get("ticker"))
    elif kind == "board":
        inner = board(data, base)
    elif kind == "team":
        inner = team(data)
    elif kind == "organisation":
        inner = organisation(data)
    elif kind == "why":
        inner = why(data)
    else:
        inner = f'<div class="stored-page"><div class="wrap">{card(data)}</div></div>'
    return (
        f'<section class="view-visitor public-view" data-kind="{kind}">'
        + hero(kind, data, path, base)
        + (band(data) if kind == "project" else "")
        + tab_bar(kind, path, base, title or "")
        + inner
        + "</section>"
    )
