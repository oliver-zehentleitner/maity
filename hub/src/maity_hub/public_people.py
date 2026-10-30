"""A person's public page (docs/api.md §16.9): `GET /{handle}` while the person's
`public_profile` is on.

It shows the `display_name`, the `handle` and the `public_bio`, and (in the steps that follow) the
projects with a public page they are a member of, their links and their agents that have a page.
Never an address, a session or who is online. A person who is suspended, waits for approval, is
deleted or is hidden by moderation (§16.8) has no page: the page is taken off in the transaction
that changed it, by `public_pages.touch`.
"""

from __future__ import annotations

import hashlib
import re
from html import escape
from typing import Any

from sqlalchemy import Connection, select

from maity_hub import clock, moderation, public_pages, render
from maity_hub import tables as t
from maity_hub.config import Settings

KIND = "person"
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
    """Whether the person has a page: they chose one, their account is active and not
    suspended or deleted, and no hold of moderation stands on their profile."""
    return bool(
        human.public_profile
        and human.account_status == "active"
        and human.deleted_at is None
        and human.suspended_at is None
        and moderation.hold(conn, "profile", human.id) is None
    )


def render_person(conn: Connection, hub: Settings, human_id: str) -> list[public_pages.Page]:
    human = conn.execute(select(t.human).where(t.human.c.id == human_id)).first()
    if human is None or not served(conn, human):
        return []
    bio = f'<p class="sub">{escape(human.public_bio)}</p>' if human.public_bio else ""
    content = (
        f'<p class="eyebrow">{escape(human.handle)}</p><h1>{escape(human.display_name)}</h1>{bio}'
    )
    path = f"/{human.handle}"
    body = render.page_document(
        lang="en",
        title=f"{human.display_name} ({human.handle})",
        canonical=f"{hub.public_url.rstrip('/')}{path}",
        content=content,
    )
    inputs = hashlib.sha256(
        "\x00".join((human.handle, human.display_name, human.public_bio or "")).encode()
    )
    return [public_pages.Page(path=path, body=body, inputs=inputs.hexdigest(), lastmod=clock.now())]


def targets(conn: Connection) -> list[str]:
    return list(
        conn.execute(
            select(t.human.c.id).where(t.human.c.public_profile.is_(True)).order_by(t.human.c.id)
        ).scalars()
    )


public_pages.register(public_pages.Kind(KIND, render_person, targets))
