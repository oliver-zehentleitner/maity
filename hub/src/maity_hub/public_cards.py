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

A public project's outsider reading the member routes (§2.3) reads the cards by the same rule
(`outside_clause`, `outside_shown`), and no hidden card's id in another card's view
(`outside_views`).
"""

from __future__ import annotations

import hashlib
from collections.abc import Collection
from typing import Any

from sqlalchemy import Connection, and_, func, or_, select

from maity_hub import clock, moderation, namespace, public_design, public_pages, render
from maity_hub import tables as t
from maity_hub.cards import CLOSED
from maity_hub.config import Settings
from maity_hub.public_project_views import _holder, members
from maity_hub.public_projects import served

KIND = "card"


def shown(card: Any) -> bool:
    """Whether the card itself may stand on a public page: a `security` card only once it is
    done (§16.9). The project and the hold are checked by the caller."""
    return (card.label or "").lower() != "security" or card.status == "done"


def shown_clause() -> Any:
    """`shown` as a condition on `card`, for a query of cards: what the Board's columns leave
    out (`public_project_views.board_rows`), and what a public project's outsider does not
    read through the member routes either (§2.3)."""
    c = t.card.c
    return or_(c.status == "done", c.label.is_(None), func.lower(c.label) != "security")


def unheld_clause() -> Any:
    """No moderation hold on the card, as a condition on `card`: the hold `render_card` and
    `board_rows` read (`moderation.hold`, any hold row of the card), so a card under one is
    on no board, has no page, and is in no list an outsider reads (§2.3, §16.8)."""
    h = t.moderation_hold.c
    held = select(h.report_id).where(h.target_type == "card", h.target_id == t.card.c.id)
    return ~held.exists()


def outside_clause() -> Any:
    """The cards a public project's outsider reads through the member routes (§2.3): those the
    public Board shows, `shown_clause` without a hold (`unheld_clause`)."""
    return and_(shown_clause(), unheld_clause())


def outside_shown(conn: Connection, card: Any) -> bool:
    """`outside_clause` for one card read already: `shown` and no hold, as `render_card`."""
    return shown(card) and moderation.hold(conn, "card", card.id) is None


def _hidden_rows(conn: Connection, referenced: set[str], parents: set[str]) -> list[Any]:
    """The cards an outsider does not read (not `outside_clause`) among `referenced`, and among
    the children of `parents`: one query for a page of cards."""
    c = t.card.c
    if not referenced and not parents:
        return []
    return list(
        conn.execute(
            select(c.id, c.parent, c.status).where(
                or_(c.id.in_(referenced), c.parent.in_(parents)), ~outside_clause()
            )
        )
    )


def hidden_among(conn: Connection, ids: set[str]) -> set[str]:
    """The cards among `ids` an outsider does not read (not `outside_clause`)."""
    return {row.id for row in _hidden_rows(conn, ids, set())}


EDGE_FIELDS = ("depends_on", "ships_with", "related")


def _release_ids(release: dict[str, Any]) -> set[str]:
    """The card ids a release object names (`releases.release_view`)."""
    found = {pr["task_id"] for pr in release.get("pull_requests") or [] if pr.get("task_id")}
    found |= {card for group in release.get("groups") or [] for card in group}
    for item in (release.get("readiness") or {}).get("blocking") or []:
        if item.get("task"):
            found.add(item["task"])
        found |= set(item.get("tasks") or [])
    return found


def _release_without(release: dict[str, Any], hidden: set[str]) -> dict[str, Any]:
    """The release object with no trace of a hidden card: a pull request only a hidden card
    reported, a hidden card in a group or a blocker, and a blocker that names nothing else."""
    dropped = {
        pr["number"] for pr in release.get("pull_requests") or [] if pr.get("task_id") in hidden
    }
    groups = [
        [card for card in group if card not in hidden] for group in release.get("groups") or []
    ]
    blocking = []
    readiness = release.get("readiness") or {}
    for item in readiness.get("blocking") or []:
        if item.get("task") in hidden or item.get("pr") in dropped:
            continue
        if "tasks" in item:
            rest = [card for card in item["tasks"] if card not in hidden]
            if len(rest) < 2:
                continue
            item = {**item, "tasks": rest}
        blocking.append(item)
    return {
        **release,
        "pull_requests": [
            pr for pr in release.get("pull_requests") or [] if pr["number"] not in dropped
        ],
        "groups": [group for group in groups if len(group) > 1],
        "readiness": {**readiness, "blocking": blocking},
    }


def outside_views(conn: Connection, views: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Card views as a public project's outsider reads them (§2.3): no trace of a card it does
    not read (a not-done `security` card, a card under a hold), neither in `depends_on`,
    `ships_with`, `related`, `parent`, the `children` counts nor a release's pull requests,
    groups and blockers. The hidden cards among those the views name are found in one query,
    whatever the number of views."""
    referenced: set[str] = set()
    for view in views:
        for name in EDGE_FIELDS:
            referenced.update(view[name])
        if view["parent"]:
            referenced.add(view["parent"])
        if view["release"]:
            referenced |= _release_ids(view["release"])
    rows = _hidden_rows(conn, referenced, {view["id"] for view in views})
    hidden = {row.id for row in rows if row.id in referenced}
    unseen: dict[str, list[Any]] = {}
    for row in rows:
        if row.parent is not None:
            unseen.setdefault(row.parent, []).append(row)
    if not hidden and not unseen:
        return views
    shaped = []
    for view in views:
        view = dict(view)
        for name in EDGE_FIELDS:
            view[name] = [card for card in view[name] if card not in hidden]
        if view["parent"] in hidden:
            view["parent"] = None
        children = unseen.get(view["id"], [])
        if children:
            view["children"] = {
                "open": view["children"]["open"]
                - sum(child.status not in CLOSED for child in children),
                "total": view["children"]["total"] - len(children),
            }
        if view["release"]:
            view["release"] = _release_without(view["release"], hidden)
        shaped.append(view)
    return shaped


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

    body = card.body or ""
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
    # The HTML in the dashboard's design, from `data` alone (`public_design.page`).
    content = public_design.page(KIND, data, path)
    digest = hashlib.sha256("\x00".join((path, project.name, content)).encode())
    return [
        public_pages.Page(
            path=path,
            body=render.page_document(
                lang="en",
                title=f"{card.title} ({card.id}) · {project.name}",
                canonical=f"{hub.public_url.rstrip('/')}{path}",
                content=content,
                styled=False,
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


def naming(conn: Connection, project_id: str, principal_id: str) -> list[str]:
    """The cards of one project whose page names a member (`render_card`): as its claim holder,
    a note's author or a note's latest editor, under any membership the principal held there."""
    c, n, m = t.card.c, t.card_note.c, t.membership.c
    held = select(m.id).where(
        m.project_id == project_id, or_(m.agent_id == principal_id, m.human_id == principal_id)
    )
    ids = set(conn.execute(held).scalars())
    if not ids:
        return []
    found = set(
        conn.execute(
            select(c.id).where(c.project_id == project_id, c.claim_holder.in_(ids))
        ).scalars()
    )
    found |= set(
        conn.execute(
            select(n.card_id)
            .join(t.card, c.id == n.card_id)
            .where(c.project_id == project_id, n.author.in_(ids))
        ).scalars()
    )
    # The editor is in JSON: the few edited notes of the project are matched here.
    edited = conn.execute(
        select(n.card_id, n.edited)
        .join(t.card, c.id == n.card_id)
        .where(c.project_id == project_id, n.edited.is_not(None))
    )
    found |= {row.card_id for row in edited if row.edited["by"] in ids}
    return sorted(found)


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
