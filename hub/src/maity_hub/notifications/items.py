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
from sqlalchemy.orm import aliased

from maity_hub import avatars, clock, events, inbox, namespace
from maity_hub import tables as t
from maity_hub.access import Membership
from maity_hub.notifications import records
from maity_hub.views import deleted, deleted_person, human_languages

WINDOW = timedelta(days=30)
KINDS = ("inbox", "chat", "mention", "security")
REQUEST_EVENTS = ("request_created", "request_forwarded", "request_answered", "request_withdrawn")
# The only event kinds that can make a notification; the derive reads no other row.
EVENT_KINDS = (
    *REQUEST_EVENTS,
    "message",
    "mentioned",
    "jour_fixe_skipped",
    "jour_fixe_reported",
)
ADDRESSED = ("request_created", "request_forwarded")  # one item per request, the latest
TITLE_MAX = 200

# The texts the hub itself composes for a human, in that human's language (§6.2, §18.4).
WORDS: dict[str, dict[str, str]] = {
    "en": {
        "asks": "{who} asks: {title}",
        "jf_no_moderator": "Jour fixe skipped, nobody to moderate: {topic}",
        "jf_reported": "Jour fixe report: {topic}",
        "answered": "{who} answered: {title}",
        "withdrew": "{who} withdrew: {title}",
        "asks_you": "{who} asks you: {title}",
        "chat": "{who} in {chat}",
        "mentioned": "{who} mentioned you in {chat}",
        "waits": "{handle} waits for approval",
        "reported": "Report: {reason} — {type}",
        "moderated": "Moderation: {action} — {type}",
        "sign_in": "New sign-in: {browser} on {os} ({method})",
        "a_browser": "a browser",
        "unknown_os": "an unknown system",
        "address_changed": "Sign-in address changed",
        "mail_disabled": "Mail to {address} disabled after 3 failures",
        "not_listening": "{n} of your agent instances are not listening",
        "tf_enrolled": "Two-factor sign-in turned on",
        "tf_disabled": "Two-factor sign-in turned off",
        "tf_recovery_codes": "New recovery codes",
        "tf_recovery_code_used": "Recovery code used",
        "tf_reset": "Two-factor sign-in reset by {by}",
        "tf_instance_off": "Two-factor sign-in turned off for this instance",
        "tf_changed": "Two-factor sign-in changed",
        "tf_failed": "Wrong second-factor codes after a sign-in: {browser} on {os}, {ip}",
        "forge_added": "Forge access added: {login} ({source})",
        "an_account": "an account",
    },
    "de": {
        "asks": "{who} fragt: {title}",
        "jf_no_moderator": "Jour fixe ausgefallen, niemand moderiert: {topic}",
        "jf_reported": "Jour-fixe-Bericht: {topic}",
        "answered": "{who} hat geantwortet: {title}",
        "withdrew": "{who} hat zurückgezogen: {title}",
        "asks_you": "{who} fragt dich: {title}",
        "chat": "{who} in {chat}",
        "mentioned": "{who} hat dich in {chat} erwähnt",
        "waits": "{handle} wartet auf Freigabe",
        "reported": "Meldung: {reason} — {type}",
        "moderated": "Moderation: {action} — {type}",
        "sign_in": "Neue Anmeldung: {browser} auf {os} ({method})",
        "a_browser": "ein Browser",
        "unknown_os": "einem unbekannten System",
        "address_changed": "Anmeldeadresse geändert",
        "mail_disabled": "Mail an {address} nach 3 Fehlern deaktiviert",
        "not_listening": "{n} deiner Agent-Instanzen hören nicht zu",
        "tf_enrolled": "Zwei-Faktor-Anmeldung eingeschaltet",
        "tf_disabled": "Zwei-Faktor-Anmeldung ausgeschaltet",
        "tf_recovery_codes": "Neue Wiederherstellungscodes",
        "tf_recovery_code_used": "Wiederherstellungscode benutzt",
        "tf_reset": "Zwei-Faktor-Anmeldung zurückgesetzt von {by}",
        "tf_instance_off": "Zwei-Faktor-Anmeldung für diese Instanz ausgeschaltet",
        "tf_changed": "Zwei-Faktor-Anmeldung geändert",
        "tf_failed": "Falsche Zwei-Faktor-Codes nach einer Anmeldung: {browser} auf {os}, {ip}",
        "forge_added": "Forge-Zugang hinzugefügt: {login} ({source})",
        "an_account": "ein Konto",
    },
}


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
    urgent: bool = False  # mailed at once whatever the kind's mode (§18.5)

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
    language: str = "en"  # the human's own, for the texts the hub composes (§6.2)

    def say(self, key: str, **values: object) -> str:
        return WORDS.get(self.language, WORDS["en"])[key].format(**values)

    def membership(self, project_id: str) -> Membership | None:
        return next((m for m in self.memberships if m.project.id == project_id), None)


def scope(conn: Connection, human_id: str, public_url: str) -> Scope:
    members = conn.execute(
        select(t.membership).where(
            t.membership.c.human_id == human_id, t.membership.c.active.is_(True)
        )
    ).all()
    found = Scope(human_id, public_url)
    found.language = human_languages(conn, {human_id}).get(human_id, "en")
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
    since: Any = None,
) -> list[Item]:
    """The items a page of `count` can reach: of each project's events, of its plain chat
    messages and of the account records, only the first `count` that `wanted` accepts,
    newest first or oldest first as the page is read. A page cut from it equals the one
    cut from `derive`, which holds every item of 30 days and costs that much per call;
    the counts read `count_items` instead.

    A message row whose payload text names the human may be a mention, so it is derived
    with the rest; the text test only selects (a false hit is classified like any row)."""
    now = clock.now()
    found: list[Item] = []
    for mine in where.memberships:
        window = _event_window(where, mine, now)
        if since is not None:
            # Read after a position (`after`, oldest first): start right behind it, so a held
            # poll looks at what came since, not at the window from its beginning (§18.2).
            start = where.joined_seq[mine.project.id]
            floor = max(since.projects.get(mine.project.id, start), start)
            window = (*window, t.event.c.seq > floor)
        # A personal request's events never make an item (`_classify`: it is one item,
        # from its record), so they are left out in SQL, not read and dropped one by one.
        personal = (
            select(t.request.c.id)
            .where(t.request.c.id == t.event.c.subject_id, t.request.c.personal.is_(True))
            .exists()
        )
        # One item per request, the latest addressed one (`ADDRESSED`): `_items_of` keeps
        # it only among the rows it is given, so a page read in chunks takes only the
        # newest such event of each request. Every one of them is classified alike, since
        # `_request_concerns` asks who holds the request now, not then.
        later = aliased(t.event)
        superseded = (
            select(later.c.seq)
            .where(
                later.c.project_id == t.event.c.project_id,
                later.c.subject_type == "request",
                later.c.subject_id == t.event.c.subject_id,
                later.c.kind.in_(ADDRESSED),
                later.c.seq > t.event.c.seq,
            )
            .exists()
        )
        others = (
            t.event.c.kind.in_(EVENT_KINDS),
            or_(t.event.c.kind != "message", _names(where.human_id)),
            or_(t.event.c.kind.notin_(REQUEST_EVENTS), ~personal),
            or_(t.event.c.kind.notin_(ADDRESSED), ~superseded),
        )
        # Every item of these rows may be on the page: no `keep` beyond `wanted`.
        # Its first chunk is a whole one: few of these rows are rejected, so one statement
        # covers a page whatever the history, as the load test keeps (test_load.py).
        found += _paged(
            conn, where, mine, window, others, lambda i: True, count, newest_first, wanted, CHUNK
        )
        found += _chats(conn, where, mine, window, count, newest_first, wanted)
    found += _records_paged(
        conn, where, now, count, newest_first, wanted, None if since is None else since.account
    )
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


def _paged(
    conn: Connection,
    where: Scope,
    mine: Membership,
    window: tuple[Any, ...],
    condition: tuple[Any, ...],
    keep: Callable[[Item], bool],
    count: int,
    newest_first: bool,
    wanted: Callable[[Item], bool],
    first: int | None = None,
) -> list[Item]:
    """The first `count` items of one project's rows under `condition` that `keep` and
    `wanted` accept, read in chunks of the order the listing uses (`at`, then `seq`) until
    they are found: a page costs the page, not every row of the window. `first` is the
    first chunk's size, by default as many as are wanted."""
    taken: list[Item] = []
    last: tuple[datetime, int] | None = None
    size = first or max(count, 1)  # then more while a filter rejects them
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
            select(t.event).where(*window, *condition, *beyond).order_by(*sort).limit(size)
        ).all()
        if not rows:
            break
        last = (rows[-1].at, rows[-1].seq)
        for item in _items_of(conn, where, mine, sorted(rows, key=lambda r: r.seq)):
            if keep(item) and wanted(item):
                taken.append(item)
        if len(rows) < size:
            break
        size = min(size * 4, CHUNK)
    taken.sort(key=lambda item: item.order, reverse=newest_first)
    return taken[:count]


def _chats(
    conn: Connection,
    where: Scope,
    mine: Membership,
    window: tuple[Any, ...],
    count: int,
    newest_first: bool,
    wanted: Callable[[Item], bool],
) -> list[Item]:
    """The first `count` plain chat items of one project that `wanted` accepts."""
    plain = (t.event.c.kind == "message", ~_names(where.human_id))
    return _paged(
        conn, where, mine, window, plain, lambda i: i.kind == "chat", count, newest_first, wanted
    )


def _records_paged(
    conn: Connection,
    where: Scope,
    now: datetime,
    count: int,
    newest_first: bool,
    wanted: Callable[[Item], bool],
    after_record: int | None = None,
) -> list[Item]:
    """The first `count` record items that `wanted` accepts, read as `_paged` reads rows;
    with `after_record`, only the records after a position's record number."""
    taken: list[Item] = []
    last: tuple[datetime, int] | None = None
    size = CHUNK  # a whole chunk first, as for the events: one statement for most pages
    c = t.account_record.c
    sort = (c.at.desc(), c.n.desc()) if newest_first else (c.at, c.n)
    while len(taken) < count:
        query = _record_rows(where, now)
        if after_record is not None:
            query = query.where(c.n > after_record)
        if last is not None:
            before = (c.at < last[0]) if newest_first else (c.at > last[0])
            tie = (c.n < last[1]) if newest_first else (c.n > last[1])
            query = query.where(or_(before, and_(c.at == last[0], tie)))
        rows = conn.execute(query.order_by(*sort).limit(size)).all()
        if not rows:
            break
        last = (rows[-1].at, rows[-1].n)
        taken += [item for item in _record_items(conn, where, now, rows) if wanted(item)]
        if len(rows) < size:
            break
        size = min(size * 4, CHUNK)
    taken.sort(key=lambda item: item.order, reverse=newest_first)
    return taken[:count]


def count_items(conn: Connection, where: Scope) -> list[Item]:
    """What the counts read of the items (§18.2): the mentions, and the security and the
    open inbox records. `inbox` counts open requests on its own, so the many request
    items never need deriving for a count. A message is a mention only when the
    classification says so (the payload text is a superset), so its candidates are
    classified, and only they."""
    now = clock.now()
    found: list[Item] = []
    for mine in where.memberships:
        window = _event_window(where, mine, now)
        rows = conn.execute(
            select(t.event)
            .where(
                *window,
                or_(
                    t.event.c.kind == "mentioned",
                    and_(t.event.c.kind == "message", _names(where.human_id)),
                ),
            )
            .order_by(t.event.c.seq)
        ).all()
        found += [i for i in _items_of(conn, where, mine, rows) if i.kind == "mention"]
    kept = (*records.SECURITY, *records.INBOX)
    found += _record_items(conn, where, now, conn.execute(_record_rows(where, now, kept)).all())
    return found


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
            title=_cut(where.say(verb, who=who, title=request.title)),
            target={"type": "request", "id": request.id},
            url=_url(where, f"{home}/inbox"),
            **base,
        )
    if row.kind == "message" and readable:
        mentioned = principal in [m.get("member_id") for m in payload.get("mentions") or []]
        writer = look.name(row.actor_membership)
        if row.conversation_id is not None and f"member:{principal}" in (row.audience or []):
            room = look.room(row.conversation_id)
            if room is not None and not look.inside(row):
                return None  # a group chat notifies its participants, from their stay on
            chat = room if room is not None else look.handle(row.conversation_id)
            title = where.say("chat", who=writer, chat=chat)
            if mentioned:
                title = where.say("mentioned", who=writer, chat=chat)
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
                title=(
                    None
                    if row.redacted
                    else _cut(where.say("mentioned", who=writer, chat=project.name))
                ),
                target={"type": "project", "id": project.id},
                url=_url(where, f"{home}/messages"),
                **base,
            )
        return None
    if (
        row.kind == "jour_fixe_skipped"
        and payload.get("skip_reason") == "no_moderator"
        and f"member:{principal}" in (row.audience or [])
    ):
        # Nobody holding the right was there, and only the keepers can grant it (§20.9);
        # dropped once the human can no longer see the series (§18.1).
        from maity_hub.jourfixe import series as series_mod

        found = look.conn.execute(
            select(t.jour_fixe_series).where(t.jour_fixe_series.c.id == payload.get("series_id"))
        ).first()
        if found is None or series_mod.sight(look.conn, found, mine) != "full":
            return None
        return Item(
            kind="inbox",
            title=_cut(where.say("jf_no_moderator", topic=found.topic)),
            target={"type": "jour_fixe_series", "id": str(payload.get("series_id"))},
            url=_url(where, f"{home}/jour-fixe"),
            **base,
        )
    if row.kind == "jour_fixe_reported" and f"member:{principal}" in (row.audience or []):
        # The report for its human recipients (§20.2), while they are on the list.
        from maity_hub.jourfixe import choices

        found = look.conn.execute(
            select(t.jour_fixe_series).where(t.jour_fixe_series.c.id == payload.get("series_id"))
        ).first()
        if found is None or not choices.receives(look.conn, found, mine.row):
            return None
        return Item(
            kind="inbox",
            title=_cut(where.say("jf_reported", topic=found.topic)),
            target={"type": "jour_fixe_round", "id": str(payload.get("round_id"))},
            url=_url(where, f"{home}/jour-fixe/{payload.get('round_id')}"),
            **base,
        )
    if row.kind == "mentioned" and readable and f"member:{principal}" in (row.audience or []):
        task = payload.get("task") or {}
        return Item(
            kind="mention",
            title=_cut(
                where.say(
                    "mentioned",
                    who=look.name(row.actor_membership),
                    chat=f"{task.get('id')} {task.get('title')}",
                )
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


def _two_factor_title(where: Scope, data: dict[str, Any]) -> str:
    """The bell's line for a change of the second factor (§18.1); a change this hub does
    not know says that the sign-in changed, never a guess."""
    change = f"tf_{data.get('change')}"
    if change not in WORDS["en"] or change in ("tf_changed", "tf_failed"):
        change = "tf_changed"
    return where.say(change, by=data.get("by"))


RECORD_TYPES = (*records.SECURITY, *records.INBOX, *records.NOTICES, "personal_request_created")


def _record_rows(where: Scope, now: datetime, types: Sequence[str] = RECORD_TYPES) -> Any:
    return select(t.account_record).where(
        t.account_record.c.human_id == where.human_id,
        t.account_record.c.at >= now - records.KEPT,
        t.account_record.c.type.in_(types),
    )


def _from_records(conn: Connection, where: Scope, now: datetime) -> list[Item]:
    return _record_items(conn, where, now, conn.execute(_record_rows(where, now)).all())


def _record_items(conn: Connection, where: Scope, now: datetime, rows: Sequence[Any]) -> list[Item]:
    """The items of these account records (§18.1)."""
    waiting = _waiting_registrations(conn, rows)
    open_reports = _open_reports(conn, rows)
    # Only the newest `agents_not_listening` record can be open; the older ones ended. Read
    # from the table, not from `rows`: a paged read hands over one chunk, which may hold an
    # older record without the newest (`_records_paged`).
    newest_away_record = (
        conn.execute(
            select(func.max(t.account_record.c.n)).where(
                t.account_record.c.human_id == where.human_id,
                t.account_record.c.type == "agents_not_listening",
            )
        ).scalar()
        if any(row.type == "agents_not_listening" for row in rows)
        else None
    )
    # The personal requests and their askers' names in a fixed number of statements, not
    # three per record: a human with many hub notices reads them all on every call.
    asked = {
        (row.data or {}).get("request_id")
        for row in rows
        if row.type == "personal_request_created" and row.at >= now - WINDOW
    }
    requests_by_id = _by_id(conn, t.request, {r for r in asked if r is not None})
    names = _member_names(conn, {r.asked_by for r in requests_by_id.values() if r.asked_by})
    inviters = _inviter_names(
        conn,
        {r.asked_by_human for r in requests_by_id.values() if not r.asked_by and r.asked_by_human},
    )
    items = []
    for row in rows:
        data = row.data or {}
        if row.type == "personal_request_created":
            if row.at < now - WINDOW:
                continue
            request = requests_by_id.get(str(data.get("request_id")))
            if request is None:
                continue
            asker = (
                names.get(request.asked_by, "someone")
                if request.asked_by
                else inviters.get(request.asked_by_human, "Maity")
            )
            items.append(
                Item(
                    kind="inbox",
                    at=row.at,
                    record=row.n,
                    project_id=request.project_id,
                    title=_cut(where.say("asks_you", who=asker, title=request.title)),
                    target={"type": "request", "id": request.id},
                    url=_url(where, f"/requests/{request.id}"),
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
                        where.say(
                            "sign_in",
                            browser=data.get("browser") or where.say("a_browser"),
                            os=data.get("os") or where.say("unknown_os"),
                            method=method,
                        )
                    ),
                    target={"type": "session", "id": str(data.get("session_id"))},
                    url=_url(where, "/account/sessions"),
                    read=row.read_at is not None,
                    record_type=row.type,
                    session_id=data.get("session_id"),
                )
            )
        elif row.type == "second_factor_changed":
            items.append(
                Item(
                    kind="security",
                    at=row.at,
                    record=row.n,
                    title=_cut(_two_factor_title(where, data)),
                    target={"type": "settings", "id": "security"},
                    url=_url(where, "/account/security"),
                    read=row.read_at is not None,
                    record_type=row.type,
                )
            )
        elif row.type == "second_factor_failed":
            items.append(
                Item(
                    kind="security",
                    at=row.at,
                    record=row.n,
                    title=_cut(
                        where.say(
                            "tf_failed",
                            browser=data.get("browser") or where.say("a_browser"),
                            os=data.get("os") or where.say("unknown_os"),
                            ip=data.get("ip") or "?",
                        )
                    ),
                    target={"type": "settings", "id": "security"},
                    url=_url(where, "/account/security"),
                    read=row.read_at is not None,
                    record_type=row.type,
                )
            )
        elif row.type == "email_address_changed":
            items.append(
                Item(
                    kind="security",
                    at=row.at,
                    record=row.n,
                    title=where.say("address_changed"),
                    target={"type": "settings", "id": "notifications"},
                    url=_url(where, "/account/notifications"),
                    read=row.read_at is not None,
                    record_type=row.type,
                )
            )
        elif row.type == "forge_access_changed":
            if data.get("change") not in records.FORGE_ADDED:
                continue  # a record, no notification (§18.1)
            items.append(
                Item(
                    kind="security",
                    at=row.at,
                    record=row.n,
                    title=_cut(
                        where.say(
                            "forge_added",
                            login=data.get("login") or where.say("an_account"),
                            source=data.get("source"),
                        )
                    ),
                    target={"type": "settings", "id": "forge"},
                    url=_url(where, "/settings/forge"),
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
                    title=_cut(where.say("waits", handle=data.get("handle"))),
                    target={"type": "registration", "id": str(data.get("human"))},
                    url=_url(where, "/admin/registration"),
                    read=not pending,
                    record_type=row.type,
                    open=pending,
                )
            )
        elif (
            row.type == "agents_not_listening"
            and row.n == newest_away_record
            and int(data.get("instances", 0)) > 0  # a closing record `{instances: 0}` lists nothing
        ):
            # Listed while any instance is away, with the count as it is now (§5.3,
            # §18.1): the record marks only when it began, the rest is read live.
            from maity_hub import not_listening_digest
            from maity_hub.notifications import preferences

            away = not_listening_digest.away_of(conn, where.human_id, now)
            if (
                away
                and preferences.preferences(conn, where.human_id)["not_listening"]["mode"] == "bell"
            ):
                items.append(
                    Item(
                        kind="inbox",
                        at=row.at,
                        record=row.n,
                        title=_cut(where.say("not_listening", n=len(away))),
                        target={"type": "agents"},
                        url=_url(where, "/agents"),
                        read=False,
                        record_type=row.type,
                        open=True,
                    )
                )
        elif row.type == "report_open":
            # Listed while the report is open, however old, and read once it is resolved or
            # expired (§16.8, §18.1); no read mark closes it.
            report = str(data.get("report"))
            pending = report in open_reports
            if not pending and row.at < now - WINDOW:
                continue
            items.append(
                Item(
                    kind="inbox",
                    at=row.at,
                    record=row.n,
                    title=_cut(
                        where.say("reported", reason=data.get("reason"), type=data.get("type"))
                    ),
                    target={"type": "report", "id": report},
                    url=_url(where, f"/admin/reports/{report}"),
                    read=not pending,
                    record_type=row.type,
                    open=pending,
                )
            )
        elif row.type == "moderation_applied" and row.at >= now - WINDOW:
            # The affected account's notice of an action on its content (§16.8): the
            # action and the note, never the reporter. Read by a read mark as any notice:
            # nothing in it is the human's to act on.
            title = where.say("moderated", action=data.get("action"), type=data.get("type"))
            if data.get("note"):
                title = f"{title}: {data['note']}"
            items.append(
                Item(
                    kind="inbox",
                    at=row.at,
                    record=row.n,
                    title=_cut(title),
                    target={"type": "moderation", "id": str(data.get("report"))},
                    url=_url(where, "/account"),
                    read=row.read_at is not None,
                    record_type=row.type,
                    urgent=data.get("action") == "suspend",
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
                    title=_cut(where.say("mail_disabled", address=data.get("address"))),
                    target={"type": "settings", "id": "notifications"},
                    url=_url(where, "/account/notifications"),
                    read=False,
                    record_type=row.type,
                    open=True,
                )
            )
    return items


def _open_reports(conn: Connection, rows: Sequence[Any]) -> set[str]:
    """The reports of these `report_open` records that are still open (§16.8)."""
    wanted = {str((row.data or {}).get("report")) for row in rows if row.type == "report_open"}
    if not wanted:
        return set()
    return set(
        conn.execute(
            select(t.abuse_report.c.id).where(
                t.abuse_report.c.id.in_(wanted), t.abuse_report.c.status == "open"
            )
        ).scalars()
    )


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


def _inviter_names(conn: Connection, human_ids: set[str]) -> dict[str, str]:
    """The display names of the humans who invite to an organisation, in one statement:
    "Deleted account" for one who deleted theirs (§2.9). A request the hub files on nobody's
    behalf has no inviter, its caller says "Maity"."""
    if not human_ids:
        return {}
    rows = conn.execute(
        select(t.human.c.id, t.human.c.display_name, t.human.c.deleted_at).where(
            t.human.c.id.in_(human_ids)
        )
    ).all()
    return {
        row.id: str(deleted_person()["display_name"]) if deleted(row) else str(row.display_name)
        for row in rows
    }


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
        self.mine = mine
        # The dashboard's address of the project is `/<owner>/<slug>` (§6.25, §16.11).
        self.home = f"/{namespace.full_name(conn, mine.project)}"
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
        self.conversation_ids = {r.conversation_id for r in rows if r.conversation_id is not None}
        self._rooms: dict[str, str] | None = None
        self._stays: dict[str, int] | None = None
        principals |= self.conversation_ids
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

    def _group_chats(self) -> None:
        """The batch's group chats, read once: their names, and the member's stays in them."""
        if self._rooms is not None:
            return
        ids = {c for c in self.conversation_ids if c.startswith("cnv-")}
        self._rooms, self._stays = {}, {}
        if not ids:
            return
        for found, title in self.conn.execute(
            select(t.conversation.c.id, t.conversation.c.title).where(t.conversation.c.id.in_(ids))
        ):
            self._rooms[found] = str(title or found)
        for found, window in self.conn.execute(
            select(
                t.conversation_participant.c.conversation_id,
                t.conversation_participant.c.window_after,
            ).where(
                t.conversation_participant.c.conversation_id.in_(ids),
                t.conversation_participant.c.membership_id == self.mine.id,
                t.conversation_participant.c.here.is_(True),
            )
        ):
            self._stays[found] = window

    def room(self, conversation_id: str) -> str | None:
        """A group chat's name (its title, else its id); None for a direct chat (§9.2)."""
        if not conversation_id.startswith("cnv-"):
            return None
        self._group_chats()
        assert self._rooms is not None
        return self._rooms.get(conversation_id, conversation_id)

    def inside(self, row: Any) -> bool:
        """The member is a participant of the group chat now, and the message falls into
        their current stay; an observer, who only reads along, never is (§9.2)."""
        self._group_chats()
        assert self._stays is not None
        window = self._stays.get(row.conversation_id)
        return window is not None and row.seq > window

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


def _member_names(conn: Connection, membership_ids: set[int]) -> dict[int, str]:
    """`_name` for many members in three statements; a member not found is left out, and
    its caller says "someone" as `_name` does."""
    if not membership_ids:
        return {}
    members = conn.execute(
        select(t.membership.c.id, t.membership.c.human_id, t.membership.c.agent_id).where(
            t.membership.c.id.in_(membership_ids)
        )
    ).all()
    humans = {m.human_id for m in members if m.human_id}
    agents = {m.agent_id for m in members if m.agent_id}
    human_names = dict(
        conn.execute(
            select(t.human.c.id, t.human.c.display_name).where(t.human.c.id.in_(humans))
        ).all()
        if humans
        else []
    )
    agent_handles = dict(
        conn.execute(
            select(t.agent_profile.c.id, t.agent_profile.c.handle).where(
                t.agent_profile.c.id.in_(agents)
            )
        ).all()
        if agents
        else []
    )
    found: dict[int, str] = {}
    for m in members:
        if m.human_id:
            found[m.id] = str(human_names.get(m.human_id) or m.human_id)
        elif m.agent_id:
            found[m.id] = f"{agent_handles.get(m.agent_id) or m.agent_id} (agent)"
        else:
            found[m.id] = "someone"
    return found


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
