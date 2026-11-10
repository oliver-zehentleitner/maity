"""The public page of one card (docs/api.md §16.9, "Card"): `/{owner}/{slug}/tasks/{id}`, the
dashboard's address of the card, while the project's page is served.

A card's text is public like an issue on a forge: the maintainer's decision of 2026-11-02
(hub/context/public-pages.md), and so are its notes, as comments on an issue (a second
decision of that day). What stays out is the rest around it: history, requests, links,
release and contract text. A card labelled `security` has a page only once it is `done`, a
card under a moderation hold has none, and the holder and the notes' authors are named only
as the Board names a holder; an edited note shows its edit mark and reason, never its old
text; a redacted note shows as removed, without its reason. Whatever
changes a card or its notes calls `public_pages.touch` for the kind `card`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Collection
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


def _notes(conn: Connection, card_id: str) -> list[Any]:
    """The card's notes, oldest first (§6.16)."""
    n = t.card_note.c
    return list(
        conn.execute(
            select(t.card_note).where(n.card_id == card_id).order_by(n.created_at, n.id)
        ).all()
    )


def _time(when: str) -> str:
    return f'<time datetime="{escape(when, quote=True)}">{escape(when[:10])}</time>'


def _note_html(note: Any, who: str, editor: str | None) -> str:
    tags = [who, _time(clock.rfc3339(note.created_at))]
    if note.state != "open":
        tags.append(escape(note.state))
    if editor is not None and note.edited and not note.redacted:
        mark = f"edited by {editor} {_time(note.edited['at'])}"
        if note.edited.get("reason"):
            mark += f": {escape(note.edited['reason'])}"
        tags.append(mark)
    text = (
        '<p class="muted">Removed.</p>'
        if note.redacted
        else render.markdown(note.body or "", ugc=True)
    )
    return f'<li><p class="muted">{" · ".join(tags)}</p>{text}</li>'


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
    notes = _notes(conn, card.id)
    named = {note.author for note in notes} | {
        note.edited["by"] for note in notes if note.edited and not note.redacted
    }
    if card.claim_holder is not None:
        named.add(card.claim_holder)
    people = members(conn, project.id, only=named) if named else {}
    person = None
    gone = False
    if card.claim_holder is not None:
        person = people.get(card.claim_holder)
        gone = person is None and _gone_agent(conn, card.claim_holder)

    def author(note: Any) -> Any:
        return people.get(note.author), note.author_kind == "agent"

    def editor(note: Any) -> Any:
        """The latest editor: the author, or a human with `events:admin` (§6.16)."""
        if not note.edited or note.redacted:
            return None
        by = note.edited["by"]
        return people.get(by), by == note.author and note.author_kind == "agent"

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
        + (
            '<h2>Notes</h2><ol class="notes">'
            + "".join(
                _note_html(note, _who(*author(note)), _who(*editor(note)) if editor(note) else None)
                for note in notes
            )
            + "</ol>"
            if notes
            else ""
        )
    )
    path = f"/{full}/tasks/{card.id}"
    data = {
        "id": card.id,
        "title": card.title,
        "status": card.status,
        "label": card.label,
        "holder": _holder(person, gone) if card.claim_holder is not None else None,
        "body": body,
        "notes": [
            {
                "id": note.id,
                "author": _holder(*author(note)),
                "body": None if note.redacted else note.body or "",
                "state": note.state,
                "created_at": clock.rfc3339(note.created_at),
                "redacted": bool(note.redacted),
                "edited": (
                    {
                        "by": _holder(*editor(note)),
                        "at": note.edited["at"],
                        "reason": note.edited.get("reason"),
                    }
                    if editor(note)
                    else None
                ),
            }
            for note in notes
        ],
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


def targets(conn: Connection, among: Collection[str] | None = None) -> list[str]:
    """Every card of a project that may have a page; `render_card` decides for each."""
    return list(
        conn.execute(
            select(t.card.c.id)
            .select_from(t.card.join(t.project, t.project.c.id == t.card.c.project_id))
            .where(t.project.c.public_page == "on", *public_pages.only(t.card.c.id, among))
            .order_by(t.card.c.id)
        ).scalars()
    )


public_pages.register(public_pages.Kind(KIND, render_card, targets))
