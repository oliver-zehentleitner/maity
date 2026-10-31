"""A person's website and their names on seven networks (docs/api.md §16.9, "A person's links").

The hub stores names, never URLs, and builds each link from the name, so that a link goes
where its label says. `links_visible` says who sees them: `private`, `friends` (follow does not
exist yet: nobody), `colleagues` (the humans who are active members of a project the person is an
active member of; agents never), `friends_and_colleagues` and `everyone`. They are read per
reader, so they are never in an event that goes to everyone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import Connection, select

from maity_hub import tables as t
from maity_hub.errors import invalid

VISIBILITY = ("private", "friends", "colleagues", "friends_and_colleagues", "everyone")
NETWORKS = ("github", "gitlab", "x", "mastodon", "bluesky", "linkedin", "discord")
WEBSITE_MAX = 200

_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_HOST = rf"{_LABEL}(?:\.{_LABEL})+"
FORMS = {
    "github": re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?"),
    "gitlab": re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,254}"),
    "x": re.compile(r"[A-Za-z0-9_]{1,15}"),
    "mastodon": re.compile(rf"@([A-Za-z0-9_]{{1,30}})@({_HOST})"),
    "bluesky": re.compile(rf"{_HOST}|did:plc:[a-z2-7]{{24}}"),
    "linkedin": re.compile(r"[A-Za-z0-9-]{3,100}"),
    "discord": re.compile(r"[a-z0-9_.]{2,32}"),
}
_HOST_MAX = 253


def _dns(host: str) -> bool:
    """A DNS name of the `<host>` form: at least one dot, ASCII labels, and a last label that
    is not all digits (so no IPv4 literal)."""
    return (
        len(host) <= _HOST_MAX
        and re.fullmatch(_HOST, host) is not None
        and not host.rsplit(".", 1)[1].isdigit()
    )


def normalised(network: str, name: str) -> str | None:
    """The name as stored, or None when it is not of its form: the host of a Mastodon name and
    a Bluesky handle are lower-cased, every other name is stored as given."""
    if network == "mastodon":
        user, _, host = name[1:].partition("@") if name.startswith("@") else ("", "", "")
        host = host.lower()
        if not user or not _dns(host) or FORMS["mastodon"].fullmatch(f"@{user}@{host}") is None:
            return None
        return f"@{user}@{host}"
    if network == "bluesky":
        lowered = name.lower()
        if lowered.startswith("did:plc:"):
            return lowered if FORMS["bluesky"].fullmatch(lowered) else None
        return lowered if _dns(lowered) and FORMS["bluesky"].fullmatch(lowered) else None
    if network == "gitlab" and name.lower().endswith((".git", ".atom")):
        return None
    return name if FORMS[network].fullmatch(name) else None


def website_problem(value: str, max_length: int = WEBSITE_MAX) -> str | None:
    """`too_long` or `format` for a website that may not be stored, else None. A project's
    links (§6.11) take the same rule with their own length (`project_links`)."""
    if len(value) > max_length:
        return "too_long"
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
        return "format"
    try:
        parts = urlsplit(value)
        host = parts.hostname
        parts.port  # noqa: B018  (a port that is no number raises)
    except ValueError:
        return "format"
    # `netloc` is the host alone: no user part, no port, no IPv6 brackets.
    if parts.scheme != "https" or not host or parts.netloc.lower() != host or not _dns(host):
        return "format"
    return None


def checked(
    website: str | None,
    social: Any,
    visible: str | None,
    stored: dict[str, str] | None,
) -> tuple[str | None, dict[str, str], str | None]:
    """The values to store, or `invalid` naming every field that fails. `social` merges: a
    network given sets or (null) clears it, one left out stays."""
    errors: dict[str, str] = {}
    if website is not None and website != "":
        problem = website_problem(website)
        if problem is not None:
            errors["website"] = problem
    if visible is not None and visible not in VISIBILITY:
        errors["links_visible"] = "unknown"
    merged = dict(stored or {})
    if social is not None and not isinstance(social, dict):
        errors["social"] = "format"
        social = {}
    for network, name in (social or {}).items():
        if network not in NETWORKS:
            errors[f"social.{network}"] = "unknown"
        elif name is None or name == "":
            merged.pop(network, None)
        elif not isinstance(name, str) or (fixed := normalised(network, name)) is None:
            errors[f"social.{network}"] = "format"
        else:
            merged[network] = fixed
    if errors:
        raise invalid(errors)
    return (website or None), merged, visible


def address(network: str, name: str) -> str | None:
    """The link a name stands for; Discord has no public profile address."""
    if network == "github":
        return f"https://github.com/{name}"
    if network == "gitlab":
        return f"https://gitlab.com/{name}"
    if network == "x":
        return f"https://x.com/{name}"
    if network == "mastodon":
        _, user, host = name.split("@")
        return f"https://{host}/@{user}"
    if network == "bluesky":
        return f"https://bsky.app/profile/{name}"
    if network == "linkedin":
        return f"https://www.linkedin.com/in/{name}"
    return None


def built(social: dict[str, str] | None) -> dict[str, str]:
    """Each network's link, and for Discord the name as text."""
    return {
        network: address(network, name) or name
        for network, name in (social or {}).items()
        if network in NETWORKS
    }


@dataclass(frozen=True)
class Reader:
    """Who reads: a human (`human_id`) or an agent (None)."""

    human_id: str | None


def _colleagues(conn: Connection, person_ids: set[str], reader: str) -> set[str]:
    """Those of `person_ids` who are active members of a project the reader is an active
    member of."""
    mine = (
        select(t.membership.c.project_id)
        .where(t.membership.c.human_id == reader, t.membership.c.active.is_(True))
        .scalar_subquery()
    )
    return set(
        conn.execute(
            select(t.membership.c.human_id)
            .where(
                t.membership.c.human_id.in_(person_ids),
                t.membership.c.active.is_(True),
                t.membership.c.project_id.in_(mine),
            )
            .distinct()
        ).scalars()
    )


def admitted(
    conn: Connection, people: dict[str, str], reader: Reader, held: set[str] | None = None
) -> set[str]:
    """Of `people` (human id to `links_visible`), those whose links the reader sees. Under a
    hold on the profile (`held`) the links count as members-only: `everyone` acts as
    `colleagues` (§16.9)."""
    held = held or set()
    seen = {
        h
        for h, value in people.items()
        if h == reader.human_id or (value == "everyone" and h not in held)
    }
    if reader.human_id is None:
        return seen
    wants = {
        h
        for h, value in people.items()
        if value in ("colleagues", "friends_and_colleagues") or (value == "everyone" and h in held)
    }
    if wants - seen:
        seen |= _colleagues(conn, wants - seen, reader.human_id)
    return seen  # `friends` is the people the person follows: nobody until follow exists


def announce(conn: Connection, human_id: str) -> None:
    """Tell the person's projects that their links changed: `member_updated` with `changed:
    ["links"]` and nothing else new, because who may read them depends on the reader (§16.9);
    each reader reads the member again."""
    from maity_hub.events import Actor, emit
    from maity_hub.views import member_view

    rows = conn.execute(
        select(t.membership)
        .where(t.membership.c.human_id == human_id, t.membership.c.active.is_(True))
        .order_by(t.membership.c.id)
    ).all()
    for row in rows:
        emit(
            conn,
            row.project_id,
            "member_updated",
            ["all"],
            {**member_view(conn, row), "changed": ["links"]},
            actor=Actor(None),
            subject=("member", human_id),
        )


def shown(human: Any) -> dict[str, Any]:
    """`website` and `social` as a reader sees them."""
    return {"website": human.website, "social": built(human.social)}
