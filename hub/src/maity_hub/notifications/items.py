"""The items a human's bell shows (docs/api.md §18.1, §18.2), derived when they are read:
from the events of the projects the human is a member of, and from the human's own
account records. Nothing here is stored but the read marks; every item is checked
against what the human may read now.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, func, select

from maity_hub import avatars, clock, events, inbox
from maity_hub import tables as t
from maity_hub.access import Membership
from maity_hub.notifications import records

WINDOW = timedelta(days=30)
KINDS = ("inbox", "chat", "mention", "card", "agent", "ticker", "jour_fixe", "security", "system")
CARD_EVENTS = (
    "task_created",
    "task_updated",
    "task_claimed",
    "task_released",
    "task_assigned",
    "task_reported",
)
EVENT_KINDS = (
    "request_created",
    "request_answered",
    "request_withdrawn",
    "message",
    "mentioned",
    "placement_reported",
    "ticker",
    *CARD_EVENTS,
)
CARD_REASONS = ("creator", "assignee", "holder", "agent_holder", "agent_assignee", "watcher")
TITLE_MAX = 200


@dataclass
class Item:
    kind: str
    at: datetime
    title: str | None
    target: dict[str, str] | None
    url: str
    seq: int | None = None  # an item from an event
    record: int | None = None  # an item from an account record
    project_id: str | None = None
    actor_membership: int | None = None
    reason: str | None = None
    redacted: bool = False
    read: bool = False
    member: bool = True  # False for a personal request of a project the human is not in
    record_type: str | None = None
    session_id: str | None = None  # a security item's session
    text: str | None = None  # a message's text, shown only where the human asked (§18.2)

    @property
    def id(self) -> str:
        return f"ntf-{self.seq}" if self.seq is not None else f"ntf-acr-{self.record}"

    @property
    def order(self) -> tuple[datetime, int, int]:
        """§18.2: by `at`, then events before records, then by number."""
        return (self.at, 0 if self.seq is not None else 1, self.seq or self.record or 0)


@dataclass
class Scope:
    """What one read needs about the human: the active memberships and where each began."""

    human_id: str
    public_url: str
    memberships: list[Membership] = field(default_factory=list)
    joined_seq: dict[str, int] = field(default_factory=dict)  # project id → highest seq then

    def membership(self, project_id: str) -> Membership | None:
        return next((m for m in self.memberships if m.project.id == project_id), None)


def scope(conn: Connection, human_id: str, public_url: str) -> Scope:
    rows = conn.execute(
        select(t.membership, t.project)
        .join(t.project, t.project.c.id == t.membership.c.project_id)
        .where(t.membership.c.human_id == human_id, t.membership.c.active.is_(True))
    ).all()
    found = Scope(human_id, public_url)
    for row in rows:
        member = conn.execute(select(t.membership).where(t.membership.c.id == row.id)).one()
        project = conn.execute(select(t.project).where(t.project.c.id == row.project_id)).one()
        found.memberships.append(Membership(project, member, "human"))
        # Joining never replays a project's history (§18.2).
        found.joined_seq[project.id] = int(
            conn.execute(
                select(func.coalesce(func.max(t.event.c.seq), 0)).where(
                    t.event.c.project_id == project.id, t.event.c.at <= member.joined_at
                )
            ).scalar_one()
        )
    return found


def derive(conn: Connection, where: Scope) -> list[Item]:
    """Every item of the last 30 days (security items: while their record lives), newest
    first, with its read flag."""
    now = clock.now()
    found: list[Item] = []
    for mine in where.memberships:
        found += _from_events(conn, where, mine, now)
    found += _from_records(conn, where, now)
    found.sort(key=lambda item: item.order, reverse=True)
    return found


# --- events --------------------------------------------------------------------------


def _from_events(conn: Connection, where: Scope, mine: Membership, now: datetime) -> list[Item]:
    rows = conn.execute(
        select(t.event)
        .where(
            t.event.c.project_id == mine.project.id,
            t.event.c.seq > where.joined_seq[mine.project.id],
            t.event.c.at >= now - WINDOW,
            t.event.c.kind.in_(EVENT_KINDS),
        )
        .order_by(t.event.c.seq)
    ).all()
    if not rows:
        return []
    hidden = events.hidden_redactions(conn, rows, mine.row)
    marks = set(
        conn.execute(
            select(t.notification_read.c.seq).where(
                t.notification_read.c.human_id == where.human_id,
                t.notification_read.c.seq.in_([r.seq for r in rows]),
            )
        ).scalars()
    )
    chats = _chat_marks(conn, mine)
    items = []
    for row in rows:
        if row.actor_membership == mine.id:
            continue  # a human's own actions never notify them
        item = _classify(conn, where, mine, row, hidden)
        if item is None:
            continue
        if item.kind == "chat" or (item.kind == "mention" and row.conversation_id is not None):
            item.read = row.seq <= chats.get(row.conversation_id, 0) or row.seq in marks
        else:
            item.read = row.seq in marks
        items.append(item)
    return items


def _classify(
    conn: Connection, where: Scope, mine: Membership, row: Any, hidden: frozenset[str]
) -> Item | None:
    """The one item an event gives this human, or None: `inbox` wins over everything,
    `mention` over `card` and `chat` (§18.1)."""
    principal = where.human_id
    readable = events.readable_by(row, mine.row, principal, hidden)
    payload = row.payload or {}
    project = mine.project
    base: dict[str, Any] = {
        "at": row.at,
        "seq": row.seq,
        "project_id": project.id,
        "actor_membership": row.actor_membership,
        "redacted": bool(row.redacted),
    }
    if row.kind.startswith("request_") and readable:
        request = _request(conn, row.subject_id)
        if request is None or request.personal:
            return None  # a personal request is one item, from its record
        mine_too = (
            inbox.addressed_to(conn, request, mine)
            if row.kind == "request_created"
            else inbox.is_asker(request, mine)
        )
        if not mine_too:
            return None
        verb = "asks" if row.kind == "request_created" else "answered"
        if row.kind == "request_withdrawn":
            verb = "withdrew"
        who = _name(conn, row.actor_membership) if row.actor_membership else "Maity"
        return Item(
            kind="inbox",
            title=_cut(f"{who} {verb}: {request.title}"),
            target={"type": "request", "id": request.id},
            url=_url(where, f"/#/p/{project.slug}/inbox"),
            **base,
        )
    if row.kind == "message" and readable:
        mentioned = principal in [m.get("member_id") for m in payload.get("mentions") or []]
        writer = _name(conn, row.actor_membership)
        if row.conversation_id is not None and f"member:{principal}" in (row.audience or []):
            title = f"{writer} in {_handle(conn, row.conversation_id)}"
            if mentioned:
                title = f"{writer} mentioned you in {_handle(conn, row.conversation_id)}"
            return Item(
                kind="mention" if mentioned else "chat",
                text=None if row.redacted else payload.get("body"),
                title=None if row.redacted else _cut(title),
                target={"type": "conversation", "id": row.conversation_id},
                url=_url(where, f"/#/p/{project.slug}/chat/{row.conversation_id}"),
                **base,
            )
        if mentioned and payload.get("type") != "chat":
            return Item(
                kind="mention",
                title=None if row.redacted else _cut(f"{writer} mentioned you in {project.name}"),
                target={"type": "project", "id": project.slug},
                url=_url(where, f"/#/p/{project.slug}/messages"),
                **base,
            )
        return None
    if row.kind == "mentioned" and readable and f"member:{principal}" in (row.audience or []):
        task = payload.get("task") or {}
        return Item(
            kind="mention",
            title=_cut(
                f"{_name(conn, row.actor_membership)} mentioned you in "
                f"{task.get('id')} {task.get('title')}"
            ),
            target={"type": "task", "id": str(task.get("id"))},
            url=_url(where, f"/#/p/{project.slug}/board?task={task.get('id')}"),
            **base,
        )
    if row.kind in CARD_EVENTS:
        card = _card(conn, row.subject_id)
        if card is None:
            return None
        reason = _card_reason(conn, card, mine)
        # A watch is no audience token: the watcher's check is reading the card (§18.1).
        if reason is None or not (readable or reason == "watcher"):
            return None
        return Item(
            kind="card",
            title=_cut(f"{card.id} {card.title}: {_change(conn, row, card)}"),
            target={"type": "task", "id": card.id},
            url=_url(where, f"/#/p/{project.slug}/board?task={card.id}"),
            reason=reason,
            **base,
        )
    if row.kind == "placement_reported" and readable:
        if payload.get("state") != "failed" and payload.get("reason") != "quota":
            return None
        placement = conn.execute(
            select(t.placement).where(t.placement.c.id == row.subject_id)
        ).first()
        if placement is None or not _concerns_placement(conn, placement, principal):
            return None
        agent = _placement_handle(conn, placement)
        why = payload.get("reason") or payload.get("state")
        return Item(
            kind="agent",
            title=_cut(f"{agent} stopped: {why}"),
            target={"type": "placement", "id": placement.id},
            url=_url(where, f"/#/p/{project.slug}/agents"),
            **base,
        )
    if row.kind == "ticker" and readable and f"member:{principal}" in (row.audience or []):
        return Item(
            kind="ticker",
            title=None if row.redacted else _cut(f"{project.name}: {payload.get('text', '')}"),
            target={"type": "ticker", "id": str(row.seq)},
            url=_url(where, f"/#/p/{project.slug}/ticker"),
            **base,
        )
    return None


def _card_reason(conn: Connection, card: Any, mine: Membership) -> str | None:
    """Which relation makes the card the human's, the first in §18.2's order."""
    if card.created_by == mine.id:
        return "creator"
    if card.assigned_to == mine.id:
        return "assignee"
    if card.claim_holder == mine.id:
        return "holder"
    if _owned_agent(conn, card.claim_holder, mine.row.human_id):
        return "agent_holder"
    if _owned_agent(conn, card.assigned_to, mine.row.human_id):
        return "agent_assignee"
    watching = conn.execute(
        select(t.card_watch.c.card_id).where(
            t.card_watch.c.card_id == card.id, t.card_watch.c.membership_id == mine.id
        )
    ).first()
    if watching is not None or mine.row.human_id in ((card.contract or {}).get("watchers") or []):
        return "watcher"
    return None


def _change(conn: Connection, row: Any, card: Any) -> str:
    payload = row.payload or {}
    if row.kind == "task_created":
        return "created"
    if row.kind == "task_updated":
        changed = payload.get("fields") or []
        return f"status {card.status}" if "status" in changed else "edited"
    if row.kind in ("task_claimed", "task_assigned"):
        verb = "claimed" if row.kind == "task_claimed" else "assigned"
        holder = payload.get("holder")
        return f"{verb} by {_principal_name(conn, holder)}" if holder else verb
    return "released" if row.kind == "task_released" else "reported"


# --- account records -----------------------------------------------------------------


def _from_records(conn: Connection, where: Scope, now: datetime) -> list[Item]:
    rows = conn.execute(
        select(t.account_record).where(
            t.account_record.c.human_id == where.human_id,
            t.account_record.c.at >= now - records.KEPT,
            t.account_record.c.type.in_(
                (*records.SECURITY, *records.SYSTEM, "personal_request_created")
            ),
        )
    ).all()
    items = []
    for row in rows:
        data = row.data or {}
        if row.type == "personal_request_created":
            if row.at < now - WINDOW:
                continue
            request = _request(conn, data.get("request_id"))
            if request is None:
                continue
            asker = _name(conn, request.asked_by) if request.asked_by else "Maity"
            items.append(
                Item(
                    kind="inbox",
                    at=row.at,
                    record=row.n,
                    project_id=request.project_id,
                    title=_cut(f"{asker} asks you: {request.title}"),
                    target={"type": "request", "id": request.id},
                    url=_url(where, f"/#/requests/{request.id}"),
                    read=row.read_at is not None,
                    member=where.membership(request.project_id) is not None,
                    record_type=row.type,
                )
            )
        elif row.type == "session_created":
            method = data.get("method")
            items.append(
                Item(
                    kind="security",
                    at=row.at,
                    record=row.n,
                    title=_cut(
                        f"New sign-in: {data.get('browser') or 'a browser'} on "
                        f"{data.get('os') or 'an unknown system'} ({method})"
                    ),
                    target={"type": "session", "id": str(data.get("session_id"))},
                    url=_url(where, "/#/account/sessions"),
                    read=row.read_at is not None,
                    record_type=row.type,
                    session_id=data.get("session_id"),
                )
            )
        elif row.type == "email_address_changed":
            items.append(
                Item(
                    kind="security",
                    at=row.at,
                    record=row.n,
                    title="Sign-in address changed",
                    target={"type": "settings", "id": "notifications"},
                    url=_url(where, "/#/account/notifications"),
                    read=row.read_at is not None,
                    record_type=row.type,
                )
            )
        elif row.type == "mail_disabled" and row.at >= now - WINDOW:
            items.append(
                Item(
                    kind="system",
                    at=row.at,
                    record=row.n,
                    title=_cut(f"Mail to {data.get('address')} disabled after 3 failures"),
                    target={"type": "settings", "id": "notifications"},
                    url=_url(where, "/#/account/notifications"),
                    read=row.read_at is not None,
                    record_type=row.type,
                )
            )
    return items


# --- views ---------------------------------------------------------------------------


CONTENT_MAX = 120


def view(
    conn: Connection, where: Scope, item: Item, content: frozenset[str] = frozenset()
) -> dict[str, Any]:
    """`content` is the kinds whose message text the human's `browser.content` asks for."""
    project = None
    if item.project_id is not None:
        row = conn.execute(
            select(t.project.c.slug, t.project.c.name).where(t.project.c.id == item.project_id)
        ).one()
        project = {"slug": row.slug, "name": row.name}
        if item.record_type == "personal_request_created":
            project["member"] = item.member
    answer: dict[str, Any] = {
        "id": item.id,
        **({"seq": item.seq} if item.seq is not None else {"record": f"acr-{item.record}"}),
        "kind": item.kind,
        "at": clock.rfc3339(item.at),
        "project": project,
        "actor": _actor(conn, item.actor_membership),
        "title": None if item.redacted else item.title,
        "target": item.target,
        "url": item.url,
        "read": item.read,
        "redacted": item.redacted,
    }
    if item.reason is not None:
        answer["reason"] = item.reason
    if item.kind in content and isinstance(item.text, str) and not item.redacted:
        # Plain text: Markdown not rendered, line breaks folded into spaces (§18.2).
        flat = " ".join(item.text.split())
        answer["content"] = flat[:CONTENT_MAX]
    return answer


def _actor(conn: Connection, membership_id: int | None) -> dict[str, Any] | None:
    if membership_id is None:
        return None
    row = conn.execute(select(t.membership).where(t.membership.c.id == membership_id)).first()
    if row is None:
        return None
    principal = row.human_id or row.agent_id
    return {
        "member_id": principal,
        "display_name": _name(conn, membership_id),
        "avatar_url": avatars.urls(conn, [principal])[principal],
    }


# --- small lookups -------------------------------------------------------------------


def _request(conn: Connection, request_id: str | None) -> Any:
    if request_id is None:
        return None
    return conn.execute(select(t.request).where(t.request.c.id == request_id)).first()


def _card(conn: Connection, card_id: str | None) -> Any:
    if card_id is None:
        return None
    return conn.execute(select(t.card).where(t.card.c.id == card_id)).first()


def actor_name(conn: Connection, membership_id: int | None) -> str:
    """A member's display name, an agent's handle marked `(agent)`."""
    return _name(conn, membership_id)


def _name(conn: Connection, membership_id: int | None) -> str:
    row = conn.execute(select(t.membership).where(t.membership.c.id == membership_id)).first()
    if row is None:
        return "someone"
    return _principal_name(conn, row.human_id or row.agent_id)


def _principal_name(conn: Connection, principal: str | None) -> str:
    if principal is None:
        return "someone"
    if principal.startswith("hum-"):
        name = conn.execute(
            select(t.human.c.display_name).where(t.human.c.id == principal)
        ).scalar()
        return str(name or principal)
    handle = conn.execute(
        select(t.agent_profile.c.handle).where(t.agent_profile.c.id == principal)
    ).scalar()
    return f"{handle or principal} (agent)"


def _handle(conn: Connection, agent_id: str) -> str:
    handle = conn.execute(
        select(t.agent_profile.c.handle).where(t.agent_profile.c.id == agent_id)
    ).scalar()
    return str(handle or agent_id)


def _owned_agent(conn: Connection, membership_id: int | None, human_id: str) -> bool:
    if membership_id is None:
        return False
    owner = conn.execute(
        select(t.agent_profile.c.owner_id)
        .join(t.membership, t.membership.c.agent_id == t.agent_profile.c.id)
        .where(t.membership.c.id == membership_id)
    ).scalar()
    return bool(owner == human_id)


def _concerns_placement(conn: Connection, placement: Any, human_id: str) -> bool:
    """The owner of the placement's agent profile, and its creator (§18.1)."""
    return placement.created_by == human_id or _owned_agent(conn, placement.membership_id, human_id)


def _placement_handle(conn: Connection, placement: Any) -> str:
    if placement.membership_id is not None:
        agent = conn.execute(
            select(t.membership.c.agent_id).where(t.membership.c.id == placement.membership_id)
        ).scalar()
        if agent is not None:
            return _handle(conn, agent)
    return str(placement.new_handle or placement.id)


def _chat_marks(conn: Connection, mine: Membership) -> dict[str, int]:
    return {
        row.conversation_id: int(row.last_seq)
        for row in conn.execute(
            select(t.conversation_read).where(t.conversation_read.c.reader == mine.id)
        ).all()
    }


def _url(where: Scope, route: str) -> str:
    return f"{where.public_url}{route}"


def _cut(text: str) -> str:
    """Text only, at most 200 characters (§18.2)."""
    flat = " ".join(text.split())
    return flat if len(flat) <= TITLE_MAX else flat[: TITLE_MAX - 1] + "…"
