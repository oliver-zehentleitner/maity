"""The public page of one card (docs/api.md §16.9, "Card"): `/{owner}/{slug}/tasks/{id}`, the
dashboard's address of the card, while the project's page is served.

A card's text is public like an issue on a forge: the maintainer's decision of 2026-11-02
(hub/context/public-pages.md). What stays out is everything around it: notes, history,
requests, links, release and contract text. A card labelled `security` has a page only once
it is `done`, a card under a moderation hold has none, and the holder is named only as the
Board names them. Whatever changes a card calls `public_pages.touch` for the kind `card`.
"""

from __future__ import annotations

import hashlib
from html import escape
from typing import Any

from sqlalchemy import Connection, select

from maity_hub import clock, moderation, namespace, public_pages, render
from maity_hub import tables as t
from maity_hub.config import Settings
from maity_hub.public_project_views import _holder, _who, members
from maity_hub.public_projects import served

KIND = "card"


def shown(card: Any) -> bool:
    """Whether the card itself may stand on a public page: a `security` card only once it is
    done (§16.9). The project and the hold are checked by the caller."""
    return (card.label or "").lower() != "security" or card.status == "done"


def _gone_agent(conn: Connection, membership_id: int) -> bool:
    """A holder that is no longer among the members: an agent when it was one."""
    return (
        conn.execute(
            select(t.membership.c.agent_id).where(t.membership.c.id == membership_id)
        ).scalar()
        is not None
    )


def render_card(conn: Connection, hub: Settings, card_id: str) -> list[public_pages.Page]:
    card = conn.execute(select(t.card).where(t.card.c.id == card_id)).first()
    if card is None or not shown(card):
        return []
    project = conn.execute(select(t.project).where(t.project.c.id == card.project_id)).first()
    if project is None or not served(conn, project):
        return []
    if moderation.hold(conn, "card", card.id) is not None:
        return []
    full = namespace.full_name(conn, project)
    person = None
    gone = False
    if card.claim_holder is not None:
        person = members(conn, project.id, only=card.claim_holder).get(card.claim_holder)
        gone = person is None and _gone_agent(conn, card.claim_holder)
    status = card.status.replace("_", " ")
    tags = [escape(status)]
    if card.label:
        tags.append(escape(card.label))
    if card.claim_holder is not None:
        tags.append(_who(person, gone))
    body = card.body or ""
    content = (
        f'<p class="eyebrow"><a href="/{escape(full, quote=True)}/board">'
        f"{escape(project.name)}: Board</a></p>"
        f"<h1>{escape(card.title)}</h1>"
        f'<p><span class="tag">{escape(card.id)}</span> '
        + " ".join(f'<span class="tag">{tag}</span>' for tag in tags)
        + "</p>"
        + (render.markdown(body, ugc=True) if body.strip() else "")
    )
    path = f"/{full}/tasks/{card.id}"
    data = {
        "id": card.id,
        "title": card.title,
        "status": card.status,
        "label": card.label,
        "holder": _holder(person, gone) if card.claim_holder is not None else None,
        "body": body,
    }
    digest = hashlib.sha256("\x00".join((path, project.name, content)).encode())
    return [
        public_pages.Page(
            path=path,
            body=render.page_document(
                lang="en",
                title=f"{card.title} ({card.id}) · {project.name}",
                canonical=f"{hub.public_url.rstrip('/')}{path}",
                content=content,
            ),
            inputs=digest.hexdigest(),
            lastmod=clock.now(),
            view="card",
            data=data,
        )
    ]


def of_project(conn: Connection, project_id: str) -> list[str]:
    """The cards of one project, each a possible page."""
    return list(
        conn.execute(
            select(t.card.c.id).where(t.card.c.project_id == project_id).order_by(t.card.c.id)
        ).scalars()
    )


def targets(conn: Connection) -> list[str]:
    """Every card of a project that may have a page; `render_card` decides for each."""
    return list(
        conn.execute(
            select(t.card.c.id)
            .select_from(t.card.join(t.project, t.project.c.id == t.card.c.project_id))
            .where(t.project.c.public_page == "on")
            .order_by(t.card.c.id)
        ).scalars()
    )


public_pages.register(public_pages.Kind(KIND, render_card, targets))
