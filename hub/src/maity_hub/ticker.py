"""The change ticker (docs/api.md §17): an item is an event of kind `ticker`.

Writing an item computes its audience once (§17.3), applies the members' follow and
mute (§17.8), checks its dedupe key (§17.7) and emits it. Reading shapes it per
reader (§17.5): a `decision` only to who may read its request now, `detail` added,
`reasons` and `audience` reduced for everyone but the human owners and admins. The
listing (§17.9) is the compact form of the same events.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Connection, insert, select

from maity_hub import events
from maity_hub import tables as t
from maity_hub.inbox import replies
from maity_hub.scopes import has_scope

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
    """An area is a path prefix (§6.2); `/` contains every path."""
    if area == "/":
        return True
    prefix = area if area.endswith("/") else area + "/"
    return path == area or path.startswith(prefix)


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
        for why in follows:
            audience.add(m.principal, why)
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
    tokens = ["all"] if broadcast else []
    for principal, entry in audience.entries.items():
        if entry.wake or not broadcast:
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


def may_read_request(request: Any, member: Any) -> bool:
    """§7's readers of a request, from a membership row or a `Member`: the asker and the
    member asked for, the addressee (a member, the owner, every holder of the role), and
    whoever holds `requests:answer`."""
    membership_id = getattr(member, "membership_id", None) or member.id
    role = member.role
    kind = getattr(member, "kind", None)
    if kind not in ("human", "agent"):
        kind = "agent" if member.agent_id else "human"
    if membership_id in (request.asked_by, request.on_behalf_of):
        return True
    if request.to_kind == "member" and request.to_member == membership_id:
        return True
    if request.to_kind == "owner" and role == "owner":
        return True
    if request.to_kind == "role" and request.to_role == role:
        return True
    return has_scope(role, kind, "requests:answer")


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
        if holder in may:
            audience.add(holder, f"card_holder:{card.id}")
        elif holder is None and assignee in may:
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
    version = card.release_version or ""
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


# --- reading -----------------------------------------------------------------------------


def withheld(conn: Connection, rows: Sequence[Any], membership: Any) -> frozenset[int]:
    """The `seq`s of the decision items among `rows` that `membership` may not read now:
    the request's readers are checked again at read time (§17.5)."""
    decisions = [
        r
        for r in rows
        if r.kind == "ticker"
        and not r.redacted
        and isinstance(r.payload, dict)
        and r.payload.get("type") == "decision"
    ]
    if not decisions or membership is None:
        return frozenset()
    ids = {(r.payload.get("request") or {}).get("id") for r in decisions}
    requests = {
        r.id: r for r in conn.execute(select(t.request).where(t.request.c.id.in_(ids))).all()
    }
    hidden = set()
    for row in decisions:
        request = requests.get((row.payload.get("request") or {}).get("id"))
        if request is None or not may_read_request(request, membership):
            hidden.add(row.seq)
    return frozenset(hidden)


def sees_everyones(reader: Any) -> bool:
    """Human owners and admins see every member's reasons and subscription (§17.5, §17.8)."""
    return reader is not None and reader.kind == "human" and reader.role in ("owner", "admin")


def details(conn: Connection, rows: Sequence[Any]) -> dict[int, dict[str, Any]]:
    """`detail` of the decision items among `rows`, read now: the request's title and the
    label of the chosen reply, `null` for an answer in words (§17.5)."""
    wanted = {
        r.seq: (r.payload.get("request") or {}).get("id")
        for r in rows
        if r.kind == "ticker"
        and not r.redacted
        and isinstance(r.payload, dict)
        and r.payload.get("type") == "decision"
    }
    if not wanted:
        return {}
    requests = {
        r.id: r
        for r in conn.execute(
            select(t.request).where(t.request.c.id.in_(set(wanted.values())))
        ).all()
    }
    found: dict[int, dict[str, Any]] = {}
    for seq, request_id in wanted.items():
        request = requests.get(request_id)
        if request is None:
            continue
        chosen = (request.answer or {}).get("reply_id")
        label = next(
            (
                o["label"]
                for o in replies(getattr(request, "class"), request.options or [])
                if o["id"] == chosen
            ),
            None,
        )
        found[seq] = {"request_title": request.title, "reply_label": label}
    return found


def shaped(
    payload: dict[str, Any], audience: list[str], reader: Any, detail: Any
) -> tuple[dict[str, Any], list[str]]:
    """A ticker item's payload and audience as `reader` sees them (§17.5)."""
    out = {**payload, "detail": detail if payload.get("type") == "decision" else None}
    if sees_everyones(reader):
        return out, audience
    principal = reader.principal_id if reader is not None else None
    out["reasons"] = [r for r in payload.get("reasons", []) if r.get("member_id") == principal]
    return out, [a for a in audience if a == "all" or a == f"member:{principal}"]


def reason_of(payload: dict[str, Any], principal: str) -> dict[str, Any] | None:
    return next((r for r in payload.get("reasons", []) if r.get("member_id") == principal), None)


def wakes(row: Any, principal: str) -> bool:
    """§17.5: `all` never wakes; a member is woken only by a reason with `wake: true`."""
    entry = reason_of(row.payload or {}, principal)
    return bool(entry and entry.get("wake"))
