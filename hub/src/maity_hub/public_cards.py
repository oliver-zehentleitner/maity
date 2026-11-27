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
(`outside_clause`, `outside_card`), and no hidden card's id in another card's view
(`outside_views`), each decided in the statement that reads the rows it returns.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

from sqlalchemy import Connection, and_, case, func, or_, select

from maity_hub import clock, moderation, namespace, public_design, public_pages
from maity_hub import tables as t
from maity_hub.cards import CLOSED
from maity_hub.config import Settings
from maity_hub.public_members import holder_data, members
from maity_hub.public_projects import served

KIND = "card"


def shown(card: Any) -> bool:
    """Whether the card itself may stand on a public page (§16.9): every card but one labelled
    `security`, in any case, that is not `done`; no label and the empty label are not
    `security`. The project and the hold are checked by the caller.

    The rule on a row already read (the card's page, the snapshot's ticker); `shown_clause`
    is its twin for a query, and the two change together: `tests/test_public_board_rule.py`
    holds them to the same answer on every status and label of its matrix."""
    return (card.label or "").lower() != "security" or card.status == "done"


def shown_clause(card: Any = t.card) -> Any:
    """`shown` as a condition on `card` (the table or an alias of it), for a query of cards:
    what the Board's columns leave out (`public_project_views.board_rows`, which reads it
    rather than a rule of its own), and what a public project's outsider does not read through
    the member routes either (§2.3, `outside_clause`).

    The same answer as `shown`, spelled for SQL: `done`, or no label (NULL is named, since
    `lower(NULL) != 'security'` is NULL, not true), or a label that lowered is not `security`;
    never NULL itself (`status` is NOT NULL, and a NULL `label` is the second term), so its
    negation is exactly the rest. The two agree on the labels the hub writes: its card routes
    accept only `cards.LABELS` (`fix`, `feature`, `chore`) or none, so no blank and nothing
    outside ASCII, which the parity test checks on the engine it runs on; beyond those an
    engine's `lower` or comparison may differ from Python's."""
    c = card.c
    return or_(c.status == "done", c.label.is_(None), func.lower(c.label) != "security")


def unheld_clause(card: Any = t.card) -> Any:
    """No moderation hold on the card, as a condition on `card`: the hold `render_card` and
    `board_rows` read (`moderation.hold`, any hold row of the card), so a card under one is
    on no board, has no page, and is in no list an outsider reads (§2.3, §16.8)."""
    h = t.moderation_hold.c
    held = select(h.report_id).where(h.target_type == "card", h.target_id == card.c.id)
    return ~held.exists()


def outside_clause(card: Any = t.card) -> Any:
    """The cards a public project's outsider reads through the member routes (§2.3): those the
    public Board shows, `shown_clause` without a hold (`unheld_clause`).

    Decided in the statement that reads the rows it returns, never in one before: on the
    server engines each statement reads its own snapshot (READ COMMITTED), so a card that
    became `security` or held after an earlier statement read it would otherwise reach the
    outsider (hub/context/public-pages.md, as #2005 decides a request on its full rows)."""
    return and_(shown_clause(card), unheld_clause(card))


def outside_card(card_id: Any) -> Any:
    """`outside_clause` for the card `card_id` (a column) names, as a condition on a query of
    what belongs to one card (its history, its notes): the statement that reads them reads
    nothing while the card is one the outsider does not read."""
    return select(t.card.c.id).where(t.card.c.id == card_id, outside_clause()).exists()


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
    groups and blockers.

    One statement, read after every other read of the views, decides it all on the rows it
    returns (`outside_clause`): the views' own cards, the cards they name and their children.
    A view whose card the outsider no longer reads by then is dropped, the `children` counts
    are counted again from the children it reads, and a named card hidden by then is left
    out, so no card that became `security` or held after the statement that listed it, or
    after the edges were read, reaches the outsider (READ COMMITTED)."""
    if not views:
        return views
    own = {view["id"] for view in views}
    referenced: set[str] = set()
    for view in views:
        for name in EDGE_FIELDS:
            if isinstance(view.get(name), list):
                referenced.update(view[name])
        if isinstance(view.get("parent"), str):
            referenced.add(view["parent"])
        if isinstance(view.get("release"), dict) and not view["release"].get("redacted"):
            referenced |= _release_ids(view["release"])
    c = t.card.c
    seen = case((outside_clause(), 1), else_=0).label("seen")
    rows = conn.execute(
        select(c.id, c.parent, c.status, seen).where(
            or_(c.id.in_(referenced | own), c.parent.in_(own))
        )
    ).all()
    kept = {row.id for row in rows if row.seen}
    hidden = referenced - kept
    children = {card: {"open": 0, "total": 0} for card in own}
    for row in rows:
        if row.seen and row.parent in children:
            children[row.parent]["total"] += 1
            children[row.parent]["open"] += row.status not in CLOSED
    shaped = []
    for view in views:
        if view["id"] not in kept:
            continue
        view = dict(view)
        for name in EDGE_FIELDS:
            if isinstance(view.get(name), list):
                view[name] = [card for card in view[name] if card in kept]
        if isinstance(view.get("parent"), str) and view["parent"] in hidden:
            view["parent"] = None
        if "children" in view:
            view["children"] = children[view["id"]]
        if isinstance(view.get("release"), dict) and not view["release"].get("redacted"):
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
        "holder": holder_data(person, gone) if card.claim_holder is not None else None,
        "body": body,
        "notes": [
            {
                "id": note.id,
                "author": holder_data(*author(note)),
                "body": None if note.redacted else note.body or "",
                "state": note.state,
                "created_at": clock.rfc3339(note.created_at),
                "redacted": bool(note.redacted),
                "edited": (
                    {
                        "by": holder_data(*editor(note)),
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
    return [
        public_pages.page(
            hub,
            path,
            f"{card.title} ({card.id}) · {project.name}",
            content,
            (project.name,),
            KIND,
            data,
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
