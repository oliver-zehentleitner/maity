"""The items a human's bell shows (docs/api.md §18.1, §18.2), derived when they are read:
from the events of the projects the human is a member of, and from the human's own
account records. Nothing here is stored but the read marks; every item is checked
against what the human may read now.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, String, and_, cast, func, or_, select

from maity_hub import avatars, clock, events, inbox, namespace
from maity_hub import tables as t
from maity_hub.access import Membership
from maity_hub.notifications import records

WINDOW = timedelta(days=30)
KINDS = ("inbox", "chat", "mention", "security")
# The kinds the maintainer's decision of 2026-10-26 removed (§18.1): asked for, `invalid`.
REMOVED_KINDS = ("card", "ticker", "jour_fixe", "keep_the_why", "agent", "system", "registration")
REQUEST_EVENTS = ("request_created", "request_forwarded", "request_answered", "request_withdrawn")
# The only event kinds that can make a notification; the derive reads no other row.
EVENT_KINDS = (*REQUEST_EVENTS, "message", "mentioned")
ADDRESSED = ("request_created", "request_forwarded")  # one item per request, the latest
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
    redacted: bool = False
    read: bool = False
    member: bool = True  # False for a personal request of a project the human is not in
    record_type: str | None = None
    session_id: str | None = None  # a security item's session
    open: bool = False  # an inbox item from a record whose matter is not yet closed

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
    members = conn.execute(
        select(t.membership).where(
            t.membership.c.human_id == human_id, t.membership.c.active.is_(True)
        )
    ).all()
    found = Scope(human_id, public_url)
    if not members:
        return found
    projects = {
        row.id: row
        for row in conn.execute(
            select(t.project).where(t.project.c.id.in_({m.project_id for m in members}))
        )
    }
    # Joining never replays a project's history (§18.2): the highest seq at the join.
    joined = dict(
        conn.execute(
            select(t.membership.c.id, func.coalesce(func.max(t.event.c.seq), 0))
            .select_from(t.membership)
            .outerjoin(
                t.event,
                and_(
                    t.event.c.project_id == t.membership.c.project_id,
                    t.event.c.at <= t.membership.c.joined_at,
                ),
            )
            .where(t.membership.c.id.in_([m.id for m in members]))
            .group_by(t.membership.c.id)
        ).all()
    )
    for member in members:
        project = projects[member.project_id]
        found.memberships.append(Membership(project, member, "human"))
        found.joined_seq[project.id] = int(joined[member.id])
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
        .where(*_event_window(where, mine, now), t.event.c.kind.in_(EVENT_KINDS))
        .order_by(t.event.c.seq)
    ).all()
    return _items_of(conn, where, mine, rows)


def _event_window(where: Scope, mine: Membership, now: datetime) -> tuple[Any, ...]:
    return (
        t.event.c.project_id == mine.project.id,
        t.event.c.seq > where.joined_seq[mine.project.id],
        t.event.c.at >= now - WINDOW,
    )


def _items_of(conn: Connection, where: Scope, mine: Membership, rows: Sequence[Any]) -> list[Item]:
    """The items of one project's event rows, in the order of `rows`."""
    if not rows:
        return []
    marks_from, marks_to = min(r.seq for r in rows), max(r.seq for r in rows)
    hidden = events.hidden_redactions(conn, rows, mine.row)
    marks = set(  # by range, not a list of every seq: the rows bound it
        conn.execute(
            select(t.notification_read.c.seq).where(
                t.notification_read.c.human_id == where.human_id,
                t.notification_read.c.seq.between(marks_from, marks_to),
            )
        ).scalars()
    )
    chats = _chat_marks(conn, mine)
    look = Lookup(conn, mine, [r for r in rows if r.actor_membership != mine.id])
    items: list[Item] = []
    held: dict[str, Item] = {}  # request id → its addressed item
    for row in rows:
        if row.actor_membership == mine.id:
            continue  # a human's own actions never notify them
        item = _classify(look, where, mine, row, hidden)
        if item is None:
            continue
        if row.kind in ADDRESSED and item.target is not None:
            earlier = held.get(item.target["id"])
            if earlier is not None:  # a forward replaces what the request said before
                items.remove(earlier)
            held[item.target["id"]] = item
        if item.kind == "chat" or (item.kind == "mention" and row.conversation_id is not None):
            item.read = row.seq <= chats.get(row.conversation_id, 0) or row.seq in marks
        else:
            item.read = row.seq in marks
        items.append(item)
    return items


# --- the page of a listing, derived without every chat ---------------------------------

CHUNK = 200  # the most message rows read at a time while a page is filled


def derive_page(
    conn: Connection,
    where: Scope,
    *,
    count: int,
    newest_first: bool,
    wanted: Callable[[Item], bool],
) -> list[Item]:
    """What `derive` returns, less the chat items no page of `count` items can reach:
    every item that is not a plain chat message (they feed the counts and are few), and
    of the plain chat messages only the first `count` that `wanted` accepts per project,
    newest first or oldest first as the page is read. A page cut from it equals the one
    cut from `derive`, which holds every chat of 30 days and costs that much per call.

    A message row whose payload text names the human may be a mention, so it is derived
    with the rest; the text test only selects (a false hit is classified like any row)."""
    now = clock.now()
    found: list[Item] = []
    for mine in where.memberships:
        window = _event_window(where, mine, now)
        named = _names(where.human_id)
        rows = conn.execute(
            select(t.event)
            .where(
                *window,
                t.event.c.kind.in_(EVENT_KINDS),
                or_(t.event.c.kind != "message", named),
            )
            .order_by(t.event.c.seq)
        ).all()
        found += _items_of(conn, where, mine, rows)
        found += _chats(conn, where, mine, window, count, newest_first, wanted)
    found += _from_records(conn, where, now)
    found.sort(key=lambda item: item.order, reverse=True)
    return found


def _names(human_id: str) -> Any:
    """A message row whose payload text has a `member_id` and the human's id: a superset
    of the rows that mention them (the exact test is `_classify`). The id alone would not
    do, a chat message names its addressee in `to`."""
    text = cast(t.event.c.payload, String)
    return and_(
        text.contains("member_id", autoescape=True), text.contains(human_id, autoescape=True)
    )


def _chats(
    conn: Connection,
    where: Scope,
    mine: Membership,
    window: tuple[Any, ...],
    count: int,
    newest_first: bool,
    wanted: Callable[[Item], bool],
) -> list[Item]:
    """The first `count` plain chat items of one project that `wanted` accepts, read in
    chunks of the order the listing uses (`at`, then `seq`) until they are found."""
    taken: list[Item] = []
    last: tuple[datetime, int] | None = None
    size = max(count, 1)  # as many as are wanted, then more while a filter rejects them
    sort = (
        (t.event.c.at.desc(), t.event.c.seq.desc())
        if newest_first
        else (t.event.c.at, t.event.c.seq)
    )
    while len(taken) < count:
        beyond: tuple[Any, ...] = ()
        if last is not None:
            before = (t.event.c.at < last[0]) if newest_first else (t.event.c.at > last[0])
            tie = (t.event.c.seq < last[1]) if newest_first else (t.event.c.seq > last[1])
            beyond = (or_(before, and_(t.event.c.at == last[0], tie)),)
        rows = conn.execute(
            select(t.event)
            .where(*window, t.event.c.kind == "message", ~_names(where.human_id), *beyond)
            .order_by(*sort)
            .limit(size)
        ).all()
        if not rows:
            break
        last = (rows[-1].at, rows[-1].seq)
        for item in _items_of(conn, where, mine, sorted(rows, key=lambda r: r.seq)):
            if item.kind == "chat" and wanted(item):
                taken.append(item)
        if len(rows) < size:
            break
        size = min(size * 4, CHUNK)
    taken.sort(key=lambda item: item.order, reverse=newest_first)
    return taken[:count]


def _classify(
    look: Lookup, where: Scope, mine: Membership, row: Any, hidden: frozenset[str]
) -> Item | None:
    """The one item an event gives this human, or None: `inbox` wins over `mention`,
    `mention` over `chat` (§18.1)."""
    principal = where.human_id
    readable = events.readable_by(row, mine.row, principal, hidden)
    payload = row.payload or {}
    project = mine.project
    home = look.home
    base: dict[str, Any] = {
        "at": row.at,
        "seq": row.seq,
        "project_id": project.id,
        "actor_membership": row.actor_membership,
        "redacted": bool(row.redacted),
    }
    if row.kind in REQUEST_EVENTS and readable:
        request = look.request(row.subject_id)
        if request is None or request.personal:
            return None  # a personal request is one item, from its record
        if not _request_concerns(look, request, mine, row):
            return None
        verb = {"request_answered": "answered", "request_withdrawn": "withdrew"}.get(
            row.kind, "asks"
        )
        who = look.name(row.actor_membership) if row.actor_membership else "Maity"
        return Item(
            kind="inbox",
            title=_cut(f"{who} {verb}: {request.title}"),
            target={"type": "request", "id": request.id},
            url=_url(where, f"{home}/inbox"),
            **base,
        )
    if row.kind == "message" and readable:
        mentioned = principal in [m.get("member_id") for m in payload.get("mentions") or []]
        writer = look.name(row.actor_membership)
        if row.conversation_id is not None and f"member:{principal}" in (row.audience or []):
            title = f"{writer} in {look.handle(row.conversation_id)}"
            if mentioned:
                title = f"{writer} mentioned you in {look.handle(row.conversation_id)}"
            return Item(
                kind="mention" if mentioned else "chat",
                title=None if row.redacted else _cut(title),
                target={"type": "conversation", "id": row.conversation_id},
                url=_url(where, f"{home}/chat/{row.conversation_id}"),
                **base,
            )
        if mentioned and payload.get("type") != "chat":
            return Item(
                kind="mention",
                title=None if row.redacted else _cut(f"{writer} mentioned you in {project.name}"),
                target={"type": "project", "id": project.id},
                url=_url(where, f"{home}/messages"),
                **base,
            )
        return None
    if row.kind == "mentioned" and readable and f"member:{principal}" in (row.audience or []):
        task = payload.get("task") or {}
        return Item(
            kind="mention",
            title=_cut(
                f"{look.name(row.actor_membership)} mentioned you in "
                f"{task.get('id')} {task.get('title')}"
            ),
            target={"type": "task", "id": str(task.get("id"))},
            url=_url(where, f"{home}/board?task={task.get('id')}"),
            **base,
        )
    return None


def _request_concerns(look: Lookup, request: Any, mine: Membership, row: Any) -> bool:
    """§18.1: a new or forwarded request the human holds now — an earlier holder, or an
    admin after another admin claimed it, no longer; an answer or a withdrawal of a
    request they asked."""
    if row.kind in ADDRESSED:
        return inbox.addressed_to(look.conn, request, mine)
    return inbox.is_asker(request, mine)


# --- account records -----------------------------------------------------------------


def _from_records(conn: Connection, where: Scope, now: datetime) -> list[Item]:
    rows = conn.execute(
        select(t.account_record).where(
            t.account_record.c.human_id == where.human_id,
            t.account_record.c.at >= now - records.KEPT,
            t.account_record.c.type.in_(
                (*records.SECURITY, *records.INBOX, "personal_request_created")
            ),
        )
    ).all()
    waiting = _waiting_registrations(conn, rows)
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
        elif row.type == "registration_pending":
            # Listed while the registration waits, however old, and read once decided
            # (§18.1, §18.3); no read mark closes it.
            pending = data.get("human") in waiting
            if not pending and row.at < now - WINDOW:
                continue
            items.append(
                Item(
                    kind="inbox",
                    at=row.at,
                    record=row.n,
                    title=_cut(f"{data.get('handle')} waits for approval"),
                    target={"type": "registration", "id": str(data.get("human"))},
                    url=_url(where, "/#/admin/registration"),
                    read=not pending,
                    record_type=row.type,
                    open=pending,
                )
            )
        elif row.type == "mail_disabled" and row.at >= now - WINDOW:
            # TODO(#280): listed and counted while the address stays disabled, however old,
            # and read once it is set again (§18.1, §18.7); the address state comes with
            # the notification settings. Until then it is open for the 30-day window: no
            # read mark closes it (§18.3).
            items.append(
                Item(
                    kind="inbox",
                    at=row.at,
                    record=row.n,
                    title=_cut(f"Mail to {data.get('address')} disabled after 3 failures"),
                    target={"type": "settings", "id": "notifications"},
                    url=_url(where, "/#/account/notifications"),
                    read=False,
                    record_type=row.type,
                    open=True,
                )
            )
    return items


def _waiting_registrations(conn: Connection, rows: Sequence[Any]) -> set[str]:
    """The humans of these `registration_pending` records whose registration still
    waits for the instance admin's decision (§16.4)."""
    humans = {
        str((row.data or {}).get("human")) for row in rows if row.type == "registration_pending"
    }
    if not humans:
        return set()
    return set(
        conn.execute(
            select(t.account_registration.c.human_id).where(
                t.account_registration.c.human_id.in_(humans),
                t.account_registration.c.status == "pending",
            )
        ).scalars()
    )


# --- views ---------------------------------------------------------------------------


def view(
    conn: Connection, where: Scope, item: Item, seen: dict[Any, Any] | None = None
) -> dict[str, Any]:
    """`seen` holds what the items of one answer share, the project and the actor, so a
    page of twenty reads each once."""
    seen = {} if seen is None else seen
    project = None
    if item.project_id is not None:
        if ("project", item.project_id) not in seen:
            row = conn.execute(
                select(t.project.c.slug, t.project.c.name).where(t.project.c.id == item.project_id)
            ).one()
            full_name = namespace.name_of(conn, item.project_id)
            seen["project", item.project_id] = {
                "slug": row.slug,
                "full_name": full_name,
                "name": row.name,
            }
        project = dict(seen["project", item.project_id])
        if item.record_type == "personal_request_created":
            project["member"] = item.member
    answer: dict[str, Any] = {
        "id": item.id,
        **({"seq": item.seq} if item.seq is not None else {"record": f"acr-{item.record}"}),
        "kind": item.kind,
        "at": clock.rfc3339(item.at),
        "project": project,
        "actor": _shared_actor(conn, item.actor_membership, seen),
        "title": None if item.redacted else item.title,
        "target": item.target,
        "url": item.url,
        "read": item.read,
        "redacted": item.redacted,
    }
    return answer


def _shared_actor(
    conn: Connection, membership_id: int | None, seen: dict[Any, Any]
) -> dict[str, Any] | None:
    if ("actor", membership_id) not in seen:
        seen["actor", membership_id] = _actor(conn, membership_id)
    found: dict[str, Any] | None = seen["actor", membership_id]
    return None if found is None else dict(found)


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


class Lookup:
    """What classifying a batch of one project's event rows reads, each kind in one query
    for the whole batch instead of one per row: the requests the rows name, the
    memberships behind the actors, and the profiles and humans behind them. Every answer
    equals the single lookup's below; an id the batch did not name falls back to it."""

    def __init__(self, conn: Connection, mine: Membership, rows: list[Any]) -> None:
        self.conn = conn
        # The dashboard's address of the project is `#/<owner>/<slug>` (§6.25).
        self.home = f"/#/{namespace.full_name(conn, mine.project)}"
        self.request_ids = {r.subject_id for r in rows if r.kind in REQUEST_EVENTS and r.subject_id}
        self.requests = _by_id(conn, t.request, self.request_ids)
        self.member_ids = {r.actor_membership for r in rows if r.actor_membership is not None}
        self.members = {
            row.id: (row.human_id, row.agent_id)
            for row in (
                conn.execute(
                    select(
                        t.membership.c.id, t.membership.c.human_id, t.membership.c.agent_id
                    ).where(t.membership.c.id.in_(self.member_ids))
                ).all()
                if self.member_ids
                else []
            )
        }
        principals = {h or a for h, a in self.members.values() if h or a}
        principals |= {r.conversation_id for r in rows if r.conversation_id is not None}
        self.human_ids = {p for p in principals if p.startswith("hum-")}
        self.agent_ids = principals - self.human_ids
        self.humans = dict(
            conn.execute(
                select(t.human.c.id, t.human.c.display_name).where(t.human.c.id.in_(self.human_ids))
            ).all()
            if self.human_ids
            else []
        )
        self.handles = dict(
            conn.execute(
                select(t.agent_profile.c.id, t.agent_profile.c.handle).where(
                    t.agent_profile.c.id.in_(self.agent_ids)
                )
            ).all()
            if self.agent_ids
            else []
        )

    def request(self, request_id: str | None) -> Any:
        if request_id is None or request_id not in self.request_ids:
            return _request(self.conn, request_id)
        return self.requests.get(request_id)

    def name(self, membership_id: int | None) -> str:
        if membership_id not in self.member_ids:
            return _name(self.conn, membership_id)
        found = self.members.get(membership_id)
        if found is None:
            return "someone"
        human_id, agent_id = found
        return self.principal_name(human_id or agent_id)

    def principal_name(self, principal: str | None) -> str:
        if principal is None:
            return "someone"
        if principal.startswith("hum-"):
            if principal not in self.human_ids:
                return _principal_name(self.conn, principal)
            return str(self.humans.get(principal) or principal)
        if principal not in self.agent_ids:
            return _principal_name(self.conn, principal)
        return f"{self.handles.get(principal) or principal} (agent)"

    def handle(self, agent_id: str) -> str:
        if agent_id not in self.agent_ids:
            return _handle(self.conn, agent_id)
        return str(self.handles.get(agent_id) or agent_id)


def _by_id(conn: Connection, table: Any, ids: set[str]) -> dict[str, Any]:
    if not ids:
        return {}
    return {row.id: row for row in conn.execute(select(table).where(table.c.id.in_(ids))).all()}


# --- small lookups -------------------------------------------------------------------


def _request(conn: Connection, request_id: str | None) -> Any:
    if request_id is None:
        return None
    return conn.execute(select(t.request).where(t.request.c.id == request_id)).first()


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
