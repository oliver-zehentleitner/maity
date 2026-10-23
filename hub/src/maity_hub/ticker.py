"""The change ticker (docs/api.md §17): an item is an event of kind `ticker`.

Writing an item computes its audience once (§17.3), applies the members' follow and
mute (§17.8), checks its dedupe key (§17.7) and emits it. Reading shapes it per
reader (§17.5): a `decision` only to who may read its request now, `detail` added,
`reasons` and `audience` reduced for everyone but the human owners and admins. The
listing (§17.9) is the compact form of the same events.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, insert, select, update

from maity_hub import events
from maity_hub import tables as t
from maity_hub.ticker_read import may_read_request, reason_of
from maity_hub.views import event_views

TYPES = ("merge", "decision", "deploy", "release", "note")
# `contract` is a merge with `contract` set, as a filter and in a subscription (§17.8).
FILTER_TYPES = ("merge", "contract", "decision", "deploy", "release", "note")
TEXT_MAX = 280
DECISION_CLASSES = ("decision", "consent", "contract")


def settings(project: Any) -> dict[str, Any]:
    """`settings.ticker` with its defaults (§17.3): off until a human switches it on."""
    given = (project.settings or {}).get("ticker") or {}
    return {
        "enabled": bool(given.get("enabled", False)),
        "contract_files": list(given.get("contract_files", [])),
        "contract_implementers": dict(given.get("contract_implementers", {})),
    }


def cut(text: str) -> str:
    """At most 280 code points, a composed text cut with `…` (§17.2)."""
    points = list(text)
    return text if len(points) <= TEXT_MAX else "".join(points[: TEXT_MAX - 1]) + "…"


# --- who is in a project --------------------------------------------------------------


@dataclass(frozen=True)
class Member:
    membership_id: int
    principal: str
    role: str
    kind: str  # human, agent
    areas: tuple[str, ...]


def members(conn: Connection, project_id: str) -> list[Member]:
    rows = conn.execute(
        select(t.membership)
        .where(t.membership.c.project_id == project_id, t.membership.c.active.is_(True))
        .order_by(t.membership.c.id)
    ).all()
    return [
        Member(
            r.id,
            r.agent_id or r.human_id,
            r.role,
            "agent" if r.agent_id else "human",
            tuple(r.areas or ()),
        )
        for r in rows
    ]


def contains(area: str, path: str) -> bool:
    """An area is a path prefix (§6.2); `/` contains every path. `hub` and `hub/` name the
    same directory."""
    if area == "/":
        return True
    bare = area.rstrip("/")
    return path == bare or path.rstrip("/") == bare or path.startswith(bare + "/")


def area_owner(people: Sequence[Member], path: str) -> tuple[Member, str] | None:
    """The member owning the narrowest area that contains `path`, `/` last (§6.2)."""
    best: tuple[Member, str] | None = None
    for m in people:
        for area in m.areas:
            if not contains(area, path):
                continue
            depth = -1 if area == "/" else len(area)
            if best is None or depth > (-1 if best[1] == "/" else len(best[1])):
                best = (m, area)
    return best


def resolve(people: Sequence[Member], token: str) -> list[Member]:
    """`member:<id>`, `role:<role>`, `area:<path>` (§17.6); nobody for what names nobody."""
    kind, _, value = token.partition(":")
    if kind == "member":
        return [m for m in people if m.principal == value]
    if kind == "role":
        return [m for m in people if m.role == value]
    if kind == "area":
        owner = area_owner(people, value)
        return [owner[0]] if owner else []
    return []


# --- the audience -----------------------------------------------------------------------


@dataclass
class Entry:
    why: list[str] = field(default_factory=list)
    wake: bool = True
    muted: bool = False


class Audience:
    """Members by principal, each with its reasons, in the order they were added."""

    def __init__(self) -> None:
        self.entries: dict[str, Entry] = {}

    def add(self, principal: str, why: str) -> None:
        entry = self.entries.setdefault(principal, Entry())
        if why not in entry.why:
            entry.why.append(why)

    def __contains__(self, principal: object) -> bool:
        return principal in self.entries


EMPTY_LISTS: dict[str, list[str]] = {"areas": [], "types": []}


def subscription_of(conn: Connection, membership_id: int) -> dict[str, Any]:
    row = conn.execute(
        select(t.ticker_subscription).where(t.ticker_subscription.c.membership_id == membership_id)
    ).first()
    if row is None:
        return {"follow": dict(EMPTY_LISTS), "mute": dict(EMPTY_LISTS), "updated_at": None}
    return {"follow": row.follow, "mute": row.mute, "updated_at": row.updated_at}


def _subscriptions(conn: Connection, ids: Iterable[int]) -> dict[int, Any]:
    wanted = list(ids)
    if not wanted:
        return {}
    rows = conn.execute(
        select(t.ticker_subscription).where(t.ticker_subscription.c.membership_id.in_(wanted))
    ).all()
    return {r.membership_id: r for r in rows}


def _matches(
    lists: dict[str, list[str]], kind: str, contract: bool, places: Sequence[str]
) -> list[str]:
    """The follow or mute values an item matches: by type (`contract` for a merge with
    `contract`) and by area (an item's paths or areas under the value, §17.8)."""
    found = []
    for value in lists.get("types", []):
        if value == kind or (value == "contract" and kind == "merge" and contract):
            found.append(f"follow:type:{value}")
    for value in lists.get("areas", []):
        if any(contains(value, p) for p in places):
            found.append(f"follow:{value}")
    return found


def apply_subscriptions(
    conn: Connection,
    people: Sequence[Member],
    audience: Audience,
    kind: str,
    contract: bool,
    places: Sequence[str],
    *,
    protected: frozenset[str] = frozenset(),
    may_read: Callable[[Member], bool] | None = None,
) -> None:
    """§17.3 then §17.8: followers are added (`follow:<area>`, `follow:type:<type>`); a mute
    removes a member, or, where a follow also matched, leaves it listed with `muted` and no
    wake. A decision is followed only by who may read its request, and its asker, the
    member asked for and the card's holder cannot mute it away (`protected`)."""
    subs = _subscriptions(conn, (m.membership_id for m in people))
    for m in people:
        sub = subs.get(m.membership_id)
        if sub is None:
            continue
        follows = _matches(sub.follow, kind, contract, places)
        if kind == "decision" and may_read is not None and not may_read(m):
            follows = []
        computed = m.principal in audience
        for why in follows:
            audience.add(m.principal, why)
        if follows and kind == "decision" and not computed:
            # A decision wakes only its computed audience; its followers list it (§17.5).
            audience.entries[m.principal].wake = False
        mutes = _matches(sub.mute, kind, contract, places)
        if not mutes or m.principal not in audience or m.principal in protected:
            continue
        if follows:
            entry = audience.entries[m.principal]
            entry.muted, entry.wake = True, False
        else:
            del audience.entries[m.principal]


# --- writing -----------------------------------------------------------------------------


def existing(conn: Connection, project_id: str, key: str) -> int | None:
    seq = conn.execute(
        select(t.ticker_dedupe.c.seq).where(
            t.ticker_dedupe.c.project_id == project_id, t.ticker_dedupe.c.dedupe_key == key
        )
    ).scalar()
    return int(seq) if seq is not None else None


def write(
    conn: Connection,
    project_id: str,
    *,
    kind: str,
    text: str,
    url: str | None,
    audience: Audience,
    origin: str,
    actor: events.Actor | None = None,
    actor_principal: str | None = None,
    subject: tuple[str, str] | None = None,
    dedupe_key: str | None = None,
    readers: Sequence[str] = (),
    broadcast: bool = True,
    facts: dict[str, Any] | None = None,
) -> int | None:
    """Emit one item; `None` when its dedupe key is taken (the first item stands, §17.7).

    `broadcast` puts `all` in the audience (every type but a decision, §17.12);
    `readers` are further members who may read it without a reason (a decision's
    request readers). Only members with a waking reason get a `member:` token beside
    `all`; the actor is never woken by its own item."""
    events.lock_project(conn, project_id)
    if dedupe_key is not None and existing(conn, project_id, dedupe_key) is not None:
        return None
    # The hub wakes no human (§17.10): for a human the item is "for me", never a wake.
    humans = {m.principal for m in members(conn, project_id) if m.kind == "human"}
    for principal, entry in audience.entries.items():
        if principal in humans:
            entry.wake = False
    tokens = ["all"] if broadcast else []
    for principal, entry in audience.entries.items():
        # Every unmuted entry is a token, woken or not: it is what names a human for
        # its notification (§18.1); a followed-and-muted member gets none (§17.8).
        if not entry.muted or not broadcast:
            tokens.append(f"member:{principal}")
    for principal in readers:
        if f"member:{principal}" not in tokens:
            tokens.append(f"member:{principal}")
    base: dict[str, Any] = {
        "merge": None,
        "request": None,
        "release": None,
        "deploy": None,
        "paths": [],
        "paths_total": 0,
        "paths_truncated": False,
        "areas": [],
        "contract": None,
        "tasks": [],
    }
    payload = {
        "type": kind,
        "text": cut(text),
        "url": url,
        "dedupe_key": dedupe_key,
        "origin": {"via": origin, "delivery": None},
        **base,
        **(facts or {}),
        "reasons": [
            {
                "member_id": principal,
                "why": entry.why,
                "wake": entry.wake and principal != actor_principal,
                "muted": entry.muted,
            }
            for principal, entry in audience.entries.items()
        ],
    }
    seq = events.emit(conn, project_id, "ticker", tokens, payload, actor=actor, subject=subject)
    if dedupe_key is not None:
        conn.execute(
            insert(t.ticker_dedupe).values(project_id=project_id, dedupe_key=dedupe_key, seq=seq)
        )
    return seq


# --- the hub's own sources: decisions and releases (§17.2) --------------------------------


def _card(conn: Connection, card_id: str | None) -> Any:
    if card_id is None:
        return None
    return conn.execute(select(t.card).where(t.card.c.id == card_id)).first()


def _principal_of(conn: Connection, membership_id: int | None) -> str | None:
    if membership_id is None:
        return None
    row = conn.execute(
        select(t.membership.c.agent_id, t.membership.c.human_id).where(
            t.membership.c.id == membership_id
        )
    ).first()
    return (row.agent_id or row.human_id) if row else None


def on_request_answered(
    conn: Connection, project: Any, request: Any, actor: events.Actor | None
) -> None:
    """A `decision`, `consent` or `contract` answered with a reply or a text, not `talk`
    (§17.2); nothing while the ticker is off."""
    answer = request.answer or {}
    if not settings(project)["enabled"] or getattr(request, "class") not in DECISION_CLASSES:
        return
    if answer.get("talk") or not (answer.get("reply_id") or answer.get("text")):
        return
    people = members(conn, project.id)
    readable = [m for m in people if may_read_request(request, m)]
    may = {m.principal for m in readable}
    audience = Audience()
    asker = _principal_of(conn, request.asked_by)
    on_behalf = _principal_of(conn, request.on_behalf_of)
    card = _card(conn, request.task_id)
    holder = _principal_of(conn, card.claim_holder) if card is not None else None
    assignee = _principal_of(conn, card.assigned_to) if card is not None else None
    if asker in may:
        audience.add(asker, "decision_asker")
    if on_behalf and on_behalf in may:
        audience.add(on_behalf, "decision_on_behalf_of")
    if card is not None:
        # The card's holder and its assignee, both (§17.3); "the assignee while nobody holds
        # it" is the merge rule.
        if holder in may:
            audience.add(holder, f"card_holder:{card.id}")
        if assignee in may:
            audience.add(assignee, f"card_assignee:{card.id}")
        if getattr(request, "class") == "contract":
            for watcher in (card.contract or {}).get("watchers", []):
                if watcher in may:
                    audience.add(watcher, "contract_watcher")
    protected = frozenset(p for p in (asker, on_behalf, holder) if p)
    apply_subscriptions(
        conn,
        people,
        audience,
        "decision",
        False,
        (),
        protected=protected,
        may_read=lambda m: m.principal in may,
    )
    text = (
        f"Decided: {card.id} {card.title} ({request.id})"
        if card is not None
        else f"Decided: {request.id}"
    )
    write(
        conn,
        project.id,
        kind="decision",
        text=text,
        url=None,
        audience=audience,
        origin="hub",
        actor=actor,
        actor_principal=answer.get("by"),
        subject=("request", request.id),
        dedupe_key=f"decision:{request.id}",
        readers=[m.principal for m in readable],
        broadcast=False,
        facts={
            "request": {
                "id": request.id,
                "class": getattr(request, "class"),
                "task_id": request.task_id,
            },
            "tasks": [request.task_id] if request.task_id else [],
        },
    )


def on_release_done(
    conn: Connection, project: Any, card: Any, actor: events.Actor | None, by: str | None
) -> None:
    """A release card moved to `done` (§17.2): every active member; nothing while off."""
    if not settings(project)["enabled"] or card.kind != "release":
        return
    version = (card.release_data or {}).get("version") or card.release_version or ""
    people = members(conn, project.id)
    audience = Audience()
    for m in people:
        audience.add(m.principal, "all_members")
    apply_subscriptions(conn, people, audience, "release", False, ())
    write(
        conn,
        project.id,
        kind="release",
        text=f"Released {version}: {card.title}",
        url=None,
        audience=audience,
        origin="hub",
        actor=actor,
        actor_principal=by,
        subject=("task", card.id),
        dedupe_key=f"release:{version}",
        facts={"release": {"task_id": card.id, "version": version}, "tasks": [card.id]},
    )


# --- the manual post's audience (§17.6) --------------------------------------------------


def manual_audience(
    conn: Connection, people: Sequence[Member], kind: str, to: Any, areas: Sequence[str]
) -> Audience:
    """`to: all` every member; a token list the members it resolves to; `computed` the
    owners of a note's areas, every member for a release (`all_members`) or a deploy;
    then the subscriptions."""
    audience = Audience()
    if to == "all":
        for m in people:
            audience.add(m.principal, "posted_to_all")
    elif isinstance(to, list):
        for token in to:
            for m in resolve(people, token):
                audience.add(m.principal, "addressed")
    elif kind == "note":
        for area in areas:
            owner = area_owner(people, area)
            if owner:
                audience.add(owner[0].principal, f"area_owner:{owner[1]}")
    elif kind == "release":
        for m in people:
            audience.add(m.principal, "all_members")
    else:  # a deploy to whom it concerns: every member (§17.6)
        for m in people:
            audience.add(m.principal, "addressed")
    apply_subscriptions(conn, people, audience, kind, False, areas)
    return audience


# --- the listing and the resume packet (§17.9) -----------------------------------------


def compact(view: dict[str, Any], principal: str) -> dict[str, Any]:
    """An item in the listing's form, with the caller's own `why` and `muted`."""
    p = view["payload"] or {}
    mine = reason_of(p, principal)
    return {
        "id": f"tck-{view['seq']}",
        "seq": view["seq"],
        "at": view["at"],
        "type": p.get("type"),
        "text": p.get("text"),
        "url": p.get("url"),
        "actor": view["actor"],
        "subject": view["subject"],
        "areas": p.get("areas", []),
        "contract": p.get("contract"),
        "tasks": p.get("tasks", []),
        "for_me": mine is not None,
        "why": mine["why"] if mine else [],
        "muted": bool(mine and mine.get("muted")),
        "detail": p.get("detail"),
        "redacted": view["redacted"],
    }


def _keep(
    row: Any,
    principal: str,
    types: list[str] | None,
    area: str | None,
    for_me: bool,
    since: datetime | None,
) -> bool:
    """The filters, on the stored row (the reader's own reason is in it either way)."""
    p = row.payload or {}
    if types is not None:
        kind = p.get("type")
        if not (kind in types or ("contract" in types and kind == "merge" and p.get("contract"))):
            return False
    if area is not None:
        places = list(p.get("areas", [])) + list(p.get("paths", []))
        if not any(contains(area, x) for x in places):
            return False
    if for_me and reason_of(p, principal) is None:
        return False
    return since is None or row.at >= since


def _readable(
    conn: Connection, mine: Any, *, before: int | None, after: int | None
) -> Iterator[Any]:
    """The project's ticker events the caller may read, newest first below `before`, or
    oldest first above `after`, in batches."""
    edge = before if after is None else after
    while True:
        query = select(t.event).where(
            t.event.c.project_id == mine.project.id, t.event.c.kind == "ticker"
        )
        if after is not None:
            query = query.where(t.event.c.seq > edge).order_by(t.event.c.seq)
        else:
            if edge is not None:
                query = query.where(t.event.c.seq < edge)
            query = query.order_by(t.event.c.seq.desc())
        batch = conn.execute(query.limit(200)).all()
        hidden = events.hidden_redactions(conn, batch, mine.row)
        for row in batch:
            if events.readable_by(row, mine.row, mine.principal_id, hidden):
                yield row
        if len(batch) < 200:
            return
        edge = batch[-1].seq


def listing(
    conn: Connection,
    mine: Any,
    *,
    types: list[str] | None = None,
    area: str | None = None,
    for_me: bool = False,
    since: datetime | None = None,
    before: int | None = None,
    after: int | None = None,
    limit: int = 50,
) -> tuple[list[dict[str, Any]], bool]:
    """One page of the readable items matching the filters, in the listing's form, and
    whether more follow. Every filter but the reader's shape works on the stored row, so
    only the page itself is turned into views. `for=me`, `area` and `since` still scan the
    project's ticker events (hub/context/ticker.md)."""
    rows: list[Any] = []
    more = False
    for row in _readable(conn, mine, before=before, after=after):
        if _keep(row, mine.principal_id, types, area, for_me, since):
            if len(rows) == limit:
                more = True
                break
            rows.append(row)
    views = event_views(conn, rows, mine)
    return [compact(v, mine.principal_id) for v in views], more


PACKET_ITEMS = 20


def packet(conn: Connection, mine: Any, cursor: int) -> dict[str, Any]:
    """The resume packet's `ticker`: the items after the cursor the member may read, at most
    20, those for it first, then the newest; `for_me` and `others` count every one of them."""
    mine_rows: list[Any] = []
    other_rows: list[Any] = []
    for row in _readable(conn, mine, before=None, after=cursor):
        (mine_rows if reason_of(row.payload or {}, mine.principal_id) else other_rows).append(row)
    chosen = [*reversed(mine_rows), *reversed(other_rows)][:PACKET_ITEMS]
    return {
        "items": [compact(v, mine.principal_id) for v in event_views(conn, chosen, mine)],
        "for_me": len(mine_rows),
        "others": len(other_rows),
        "truncated": len(mine_rows) + len(other_rows) > PACKET_ITEMS,
    }


# --- the subscription (§17.8) ----------------------------------------------------------


def lock_subscription(conn: Connection, project_id: str, membership_id: int) -> dict[str, Any]:
    """The member's subscription, read under the project lock: two changes of the same
    member at once both land, one after the other (§17.8)."""
    events.lock_project(conn, project_id)
    return subscription_of(conn, membership_id)


def store_subscription(conn: Connection, membership_id: int, lists: dict[str, Any]) -> None:
    """Insert or update, under the lock `lock_subscription` took."""
    values = {"follow": lists["follow"], "mute": lists["mute"], "updated_at": lists["updated_at"]}
    done = conn.execute(
        update(t.ticker_subscription)
        .where(t.ticker_subscription.c.membership_id == membership_id)
        .values(**values)
    ).rowcount
    if not done:
        conn.execute(insert(t.ticker_subscription).values(membership_id=membership_id, **values))
