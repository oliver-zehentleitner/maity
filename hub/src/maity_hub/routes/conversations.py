"""Conversations (docs/api.md §9): direct ones and group chats.

A direct conversation is a human's private chat with an agent it owns: `message`
events of type `chat` whose `conversation_id` is the agent's member id, between the
two of them, nobody else. A group chat (`group_chats`, §9.2) is a room of members whose
messages carry its `cnv-…` id. Both are read and written through the same endpoints;
the hub tells them apart by the id, a client by `kind`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection, func, select

from maity_hub import events, group_chats, idempotency, paging
from maity_hub import tables as t
from maity_hub.access import Membership, membership
from maity_hub.auth.caller import Caller
from maity_hub.deps import AnyCaller, engine_of
from maity_hub.errors import ApiError, forbidden, humans_only, invalid, not_found
from maity_hub.models import Strict, Written, markdown, title
from maity_hub.routes.events import MessageIn, chat_parties, post_message, remember_read
from maity_hub.views import principal_id, sees_chat_reasons, ts

router = APIRouter()

PAGE_DEFAULT, PAGE_MAX = 50, 200
SEQ_MAX = 2**63 - 1


class ChatIn(Written):
    """A chat message. A direct chat is never resolved for mentions, a group chat
    against its participants (§8.6); a client's `mentions` is `read_only` on both."""

    body: str = markdown(min_length=1)


class GroupIn(Strict):
    title: str | None = title(default=None)
    participants: list[str] = Field(max_length=200)


class GroupPatch(Strict):
    title: str | None = title()  # given, `null` clears it


class ParticipantIn(Strict):
    member_id: str


def _observer() -> ApiError:
    return ApiError(
        403, "forbidden", "an owner reads along and does not act", {"reason": "observer"}
    )


def _redaction(row: Any, reader: Any, group_readers: set[str] | None) -> dict[str, Any] | None:
    """`{at, by, reason}` of a redacted message; the reason by §8.5's chat rule: the
    direct chat's human party, a group chat's humans as `group_readers` says, and the
    redactor; an agent and an owner reading along get null."""
    if not row.redacted:
        return None
    tomb = row.payload or {}
    mine = reader is not None and tomb.get("by") == reader.principal_id
    shown = sees_chat_reasons(reader, group_readers) or mine
    return {
        "at": tomb.get("at"),
        "by": tomb.get("by"),
        "reason": tomb.get("reason") if shown else None,
    }


def message_views(conn: Connection, rows: list[Any], reader: Any = None) -> list[dict[str, Any]]:
    """Messages as §9.1 and §9.2 show them to `reader` (a `Membership`; None for its
    writer)."""
    readers = group_chats.reason_readers(
        conn, {r.conversation_id for r in rows if r.redacted and r.conversation_id}
    )
    delivered = (
        dict(
            conn.execute(
                select(t.message_delivery.c.seq, t.message_delivery.c.delivered_at).where(
                    t.message_delivery.c.seq.in_([r.seq for r in rows])
                )
            ).all()
        )
        if rows
        else {}
    )
    views = []
    for row in rows:
        payload = row.payload or {}
        group = group_chats.is_group(row.conversation_id)
        view: dict[str, Any] = {
            "id": f"evt-{row.seq}",
            "seq": row.seq,
            "conversation_id": row.conversation_id,
            "from": principal_id(conn, row.actor_membership),
            "to": payload.get("to"),
            "body": None if row.redacted else payload.get("body"),
            "sent_at": ts(row.at),
        }
        if not group:  # several recipients: no read receipt is modelled (§9.2)
            view["delivered_at"] = ts(delivered.get(row.seq))
        view |= {
            # A direct chat is never resolved; a group chat's resolved mentions (§8.6).
            "mentions": [] if row.redacted or not group else payload.get("mentions") or [],
            "attachments": [],  # the contract's shape before attachments land (§8.7)
            "redacted": bool(row.redacted),  # as in the list preview (§9.3)
            "redaction": _redaction(
                row, reader, readers.get(row.conversation_id) if group else None
            ),
        }
        views.append(view)
    return views


def message_view(conn: Connection, row: Any, reader: Any = None) -> dict[str, Any]:
    return message_views(conn, [row], reader)[0]


def _party(conn: Connection, mine: Membership, agent_id: str, *, hidden: bool) -> None:
    """The caller must be one of a direct conversation's two parties: anyone else gets
    `not_found` for the conversation itself (§9.1), `forbidden` on its messages."""
    try:
        agent, human = chat_parties(conn, mine, agent_id)
    except ApiError:
        raise not_found() from None
    if mine.id not in (agent.id, human.id):
        if hidden:
            raise not_found()
        raise forbidden(message="a conversation is its two parties' alone")


def _group(conn: Connection, mine: Membership, conversation_id: str) -> tuple[Any, str]:
    """The group chat and the caller's access to it; `not_found` without access."""
    group = group_chats.find(conn, mine.project.id, conversation_id)
    found = group_chats.access(conn, conversation_id, mine) if group is not None else None
    if found is None:
        raise not_found()
    return group, found


def _messages(project_id: str, conversation_id: str) -> Any:
    return select(t.event).where(
        t.event.c.project_id == project_id,
        t.event.c.kind == "message",
        t.event.c.conversation_id == conversation_id,
    )


PREVIEW = 200  # code points (§9)


def _preview(conn: Connection, row: Any) -> dict[str, Any] | None:
    """A message as a list preview: text for the list, never mentions (§9.1)."""
    if row is None:
        return None
    body = None if row.redacted else (row.payload or {}).get("body")
    return {
        "seq": row.seq,
        "from": principal_id(conn, row.actor_membership),
        "body": body[:PREVIEW] if isinstance(body, str) else None,
        "sent_at": ts(row.at),
        "redacted": bool(row.redacted),
    }


def _read_mark(conn: Connection, reader: int, conversation_id: str) -> int:
    found = conn.execute(
        select(t.conversation_read.c.last_seq).where(
            t.conversation_read.c.reader == reader,
            t.conversation_read.c.conversation_id == conversation_id,
        )
    ).scalar()
    return int(found or 0)


# --- the list (§9.3) ---------------------------------------------------------------------


def _short(person: dict[str, Any]) -> dict[str, Any]:
    return {k: person[k] for k in ("member_id", "kind", "handle")}


def _direct_item(
    conn: Connection, mine: Membership, caller: Caller, agent_id: str
) -> dict[str, Any]:
    agent, human = chat_parties(conn, mine, agent_id)
    query = _messages(mine.project.id, agent_id)
    last = conn.execute(query.order_by(t.event.c.seq.desc()).limit(1)).first()
    people = group_chats.people(conn, [human.id, agent.id])
    return {
        "id": agent_id,
        "kind": "direct",
        "agent_id": agent_id,
        "title": None,
        "participants": [_short(people[human.id]), _short(people[agent.id])],
        "access": "party",
        "closed_at": None,
        "last_message_at": ts(last.at) if last is not None else None,
        "unread": _direct_unread(conn, mine, caller, agent_id),
        "mentions_unread": 0,
        "last_message": _preview(conn, last),
        "_activity": last.at if last is not None else agent.joined_at,
    }


def _direct_unread(conn: Connection, mine: Membership, caller: Caller, agent_id: str) -> int:
    """The other party's messages after what this reader has seen (§9.1)."""
    if caller.kind == "human":
        seen = _read_mark(conn, mine.id, agent_id)
    else:  # the agent's side is its event cursor
        seen = (
            conn.execute(
                select(t.agent_session.c.acknowledged_seq).where(
                    t.agent_session.c.id == caller.session_id
                )
            ).scalar()
            or 0
        )
    count = conn.execute(
        select(func.count()).where(
            t.event.c.project_id == mine.project.id,
            t.event.c.kind == "message",
            t.event.c.conversation_id == agent_id,
            t.event.c.seq > seen,
            t.event.c.actor_membership != mine.id,
        )
    ).scalar_one()
    return int(count)


def _window(conn: Connection, group: Any, mine: Membership, found: str) -> int:
    """The seq after which the caller's window starts (§9.2): its latest join, for an
    observer the earliest join of its agents in the chat."""
    current = group_chats.stays(conn, group.id)
    if found == "participant":
        return int(next(s.window_after for s in current if s.membership_id == mine.id))
    owned = set(
        conn.execute(
            select(t.agent_profile.c.id).where(t.agent_profile.c.owner_id == mine.principal_id)
        ).scalars()
    )
    return int(min(s.window_after for s in current if s.agent_id in owned))


def _group_item(conn: Connection, mine: Membership, group: Any, found: str) -> dict[str, Any]:
    view = group_chats.view(conn, group, found)
    window = _window(conn, group, mine, found)
    in_window = _messages(mine.project.id, group.id).where(t.event.c.seq > window)
    last = conn.execute(in_window.order_by(t.event.c.seq.desc()).limit(1)).first()
    unread: int | None = None  # an observer reads along and is never behind
    mentioned: int | None = None
    if found == "participant":
        seen = max(window, _read_mark(conn, mine.id, group.id))
        rows = conn.execute(
            in_window.where(t.event.c.seq > seen, t.event.c.actor_membership != mine.id)
        ).all()
        unread = len(rows)
        mentioned = sum(
            1
            for r in rows
            if not r.redacted
            and any(
                m.get("member_id") == mine.principal_id
                for m in (r.payload or {}).get("mentions") or []
            )
        )
    return {
        "id": group.id,
        "kind": "group",
        "title": group.title,
        "participants": [_short(p) for p in view["participants"]],
        "observers": view["observers"],
        "access": found,
        "closed_at": view["closed_at"],
        "last_message_at": ts(last.at) if last is not None else None,
        "unread": unread,
        "mentions_unread": mentioned,
        "last_message": _preview(conn, last),
        "_activity": last.at if last is not None else group.created_at,
    }


def _my_groups(conn: Connection, mine: Membership, observed: bool) -> list[tuple[Any, str]]:
    """The group chats the caller takes part in, and with `observed` those it reads
    along in as an owner (§9.3)."""
    ids = set(
        conn.execute(
            select(t.conversation_participant.c.conversation_id).where(
                t.conversation_participant.c.membership_id == mine.id,
                t.conversation_participant.c.here.is_(True),
            )
        ).scalars()
    )
    if observed and mine.kind == "human":
        ids |= set(
            conn.execute(
                select(t.conversation_participant.c.conversation_id)
                .join(
                    t.membership,
                    t.membership.c.id == t.conversation_participant.c.membership_id,
                )
                .join(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
                .where(
                    t.conversation_participant.c.here.is_(True),
                    t.agent_profile.c.owner_id == mine.principal_id,
                    t.membership.c.project_id == mine.project.id,
                )
            ).scalars()
        )
    found = []
    for conversation_id in sorted(ids):
        group = group_chats.find(conn, mine.project.id, conversation_id)
        access = group_chats.access(conn, conversation_id, mine) if group is not None else None
        if access is not None:
            found.append((group, access))
    return found


def _owned_agents(conn: Connection, mine: Membership, caller: Caller) -> list[str]:
    if caller.kind == "agent":
        return [caller.agent_id] if caller.agent_id else []
    return list(
        conn.execute(
            select(t.membership.c.agent_id)
            .join(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
            .where(
                t.membership.c.project_id == mine.project.id,
                t.membership.c.active.is_(True),
                t.agent_profile.c.owner_id == caller.human_id,
            )
            .order_by(t.agent_profile.c.handle)
        ).scalars()
    )


@router.get("/projects/{slug}/conversations")
def list_conversations(
    slug: str,
    request: Request,
    caller: AnyCaller,
    observed: bool = False,
    limit: int = Query(default=PAGE_DEFAULT, ge=1, le=PAGE_MAX),
    cursor: str | None = None,
) -> JSONResponse:
    """Every conversation the caller is in, both kinds, newest activity first (§9.3)."""
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        items = [_direct_item(conn, mine, caller, a) for a in _owned_agents(conn, mine, caller)]
        items += [_group_item(conn, mine, g, a) for g, a in _my_groups(conn, mine, observed)]
        items.sort(key=lambda i: (i["_activity"], i["id"]), reverse=True)
        bound = paging.scope(observed=observed)
        if cursor is not None:
            at, after_id = paging.uncursor(cursor, bound)
            items = [i for i in items if (i["_activity"], i["id"]) < (at, after_id)]
        page = items[:limit]
        next_cursor = (
            paging.cursor(page[-1]["_activity"], page[-1]["id"], bound)
            if len(items) > limit
            else None
        )
        for item in page:
            del item["_activity"]
        return JSONResponse({"items": page, "next_cursor": next_cursor})


# --- group chats (§9.2) --------------------------------------------------------------------


@router.post("/projects/{slug}/conversations")
def create_group(slug: str, body: GroupIn, request: Request, caller: AnyCaller) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = _locked(conn, caller, slug)
        if mine.kind != "human":  # the hub's jour fixe thread is no route (§20.5)
            raise humans_only("only a human creates a group chat")
        conversation_id = group_chats.create(
            conn,
            mine.project,
            mine.row,
            body.title,
            body.participants,
            caller.actor(mine.id),
        )
        return idempotency.Outcome(
            201, "conversation", conversation_id, _load(conn, mine, conversation_id)
        )

    return idempotency.run(engine_of(request), request, caller, action)


def _locked(conn: Connection, caller: Caller, slug: str) -> Membership:
    """The caller's membership read after the project lock: a write to a chat decides on
    the membership, the chat, the caller's access and the audience as of the lock, so a
    leave, a close or a removal that commits first is never overtaken (§9.2)."""
    first = membership(conn, caller, slug)
    events.lock_project(conn, first.project.id)
    return membership(conn, caller, slug)


def _load(conn: Connection, mine: Membership, conversation_id: str) -> dict[str, Any]:
    group, found = _group(conn, mine, conversation_id)
    return group_chats.view(conn, group, found)


def _load_for_caller(conn: Connection, conversation_id: str, request: Request) -> dict[str, Any]:
    """A replay shows the chat to the caller as it is now."""
    row = conn.execute(select(t.conversation).where(t.conversation.c.id == conversation_id)).one()
    slug = conn.execute(select(t.project.c.slug).where(t.project.c.id == row.project_id)).scalar()
    mine = membership(conn, request.state.caller, str(slug))
    found = group_chats.access(conn, conversation_id, mine)
    if found is None:  # a replay shows nothing the caller may no longer read (as #271)
        raise not_found()
    return group_chats.view(conn, row, found)


idempotency.LOADERS["conversation"] = _load_for_caller


@router.get("/projects/{slug}/conversations/{conversation_id}")
def get_conversation(
    slug: str, conversation_id: str, request: Request, caller: AnyCaller
) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        if group_chats.is_group(conversation_id):
            return JSONResponse(_load(conn, mine, conversation_id))
        # A direct one answers its list item, so any item opens by its id (§9.1).
        _party(conn, mine, conversation_id, hidden=True)
        item = _direct_item(conn, mine, caller, conversation_id)
        del item["_activity"]
        return JSONResponse(item)


def _manager(conn: Connection, mine: Membership, conversation_id: str) -> Any:
    """The chat, for a caller who may rename it or change who is in it (§9.2): its
    creator while a participant, a human participant with `members:admin`."""
    if not group_chats.is_group(conversation_id):
        _party(conn, mine, conversation_id, hidden=True)
        raise invalid({"conversation": "direct"}, "a direct conversation does not change")
    group, found = _group(conn, mine, conversation_id)
    if found == "observer":
        raise _observer()
    creator = group.created_by == mine.id
    if mine.kind != "human" or not (creator or mine.may("members:admin")):
        raise forbidden(message="the creator or a human admin in the chat manages it")
    return group


@router.patch("/projects/{slug}/conversations/{conversation_id}")
def patch_conversation(
    slug: str, conversation_id: str, body: GroupPatch, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = _locked(conn, caller, slug)
        group = _manager(conn, mine, conversation_id)
        group_chats.rename(conn, group, body.title, caller.actor(mine.id))
        return idempotency.Outcome(
            200, "conversation", conversation_id, _load(conn, mine, conversation_id)
        )

    return idempotency.run(engine_of(request), request, caller, action)


@router.post("/projects/{slug}/conversations/{conversation_id}/participants")
def add_participant(
    slug: str, conversation_id: str, body: ParticipantIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = _locked(conn, caller, slug)
        group = _manager(conn, mine, conversation_id)
        group_chats.add(conn, group, body.member_id, mine.principal_id, caller.actor(mine.id))
        return idempotency.Outcome(
            200, "conversation", conversation_id, _load(conn, mine, conversation_id)
        )

    return idempotency.run(engine_of(request), request, caller, action)


@router.delete("/projects/{slug}/conversations/{conversation_id}/participants/{member_id}")
def remove_participant(
    slug: str, conversation_id: str, member_id: str, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = _locked(conn, caller, slug)
        leaving = member_id == mine.principal_id
        if leaving and group_chats.is_group(conversation_id):  # any participant leaves
            group, found = _group(conn, mine, conversation_id)
            if found == "observer":
                raise _observer()
        else:
            group = _manager(conn, mine, conversation_id)
        targets = conn.execute(
            select(t.membership.c.id)
            .where(
                t.membership.c.project_id == mine.project.id,
                (t.membership.c.agent_id == member_id) | (t.membership.c.human_id == member_id),
            )
            .order_by(t.membership.c.joined_at.desc())
        ).scalars()
        stays = [
            s for s in (group_chats.last_stay(conn, group.id, m) for m in targets) if s is not None
        ]
        if not stays:
            raise not_found()
        latest = max(stays, key=lambda s: s.id)
        if latest.here:
            latest = group_chats.remove(
                conn,
                group,
                latest.membership_id,
                mine.principal_id,
                "left" if leaving else "removed",
                caller.actor(mine.id),
            )
        # Not in the chat: its last stay as it is (§9.2).
        return idempotency.Outcome(
            200, "participation", str(latest.id), group_chats.participation(conn, latest)
        )

    return idempotency.run(engine_of(request), request, caller, action)


def _load_participation(conn: Connection, stay_id: str) -> dict[str, Any]:
    row = conn.execute(
        select(t.conversation_participant).where(t.conversation_participant.c.id == int(stay_id))
    ).one()
    return group_chats.participation(conn, row)


idempotency.LOADERS["participation"] = idempotency.plain(_load_participation)


# --- messages (§9.1, §9.2) ---------------------------------------------------------------


@router.get("/projects/{slug}/conversations/{conversation_id}/messages")
def read_messages(
    slug: str,
    conversation_id: str,
    request: Request,
    caller: AnyCaller,
    after: int | None = Query(default=None, ge=0, le=SEQ_MAX),
    before: int | None = Query(default=None, ge=1, le=SEQ_MAX),
    limit: int = Query(default=PAGE_DEFAULT, ge=1, le=PAGE_MAX),
) -> JSONResponse:
    if after is not None and before is not None:
        raise invalid({"before": "with_after"}, "after or before, not both")
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        group = None
        found = "party"
        window = 0
        if group_chats.is_group(conversation_id):
            group, found = _group(conn, mine, conversation_id)
            window = _window(conn, group, mine, found)
        else:
            _party(conn, mine, conversation_id, hidden=False)
        query = _messages(mine.project.id, conversation_id)
        if before is not None:
            # The history, back to the conversation's first message, whenever the reader
            # joined; it marks nothing read and wakes nobody (§9.2).
            rows = list(
                reversed(
                    conn.execute(
                        query.where(t.event.c.seq < before)
                        .order_by(t.event.c.seq.desc())
                        .limit(limit)
                    ).all()
                )
            )
            cursor = 0
        else:
            start = max(after or 0, window)
            rows = list(
                conn.execute(
                    query.where(t.event.c.seq > start).order_by(t.event.c.seq).limit(limit)
                ).all()
            )
            cursor = rows[-1].seq if rows else start
            if group is None:
                events.mark_delivered(conn, rows, mine.principal_id)
            # A direct chat's human party, a group chat's participant; never an observer.
            marks = found == "participant" if group is not None else mine.kind == "human"
            if rows and marks:
                remember_read(conn, mine.id, conversation_id, rows[-1].seq)
        earlier = None
        if rows:
            older = conn.execute(
                query.with_only_columns(t.event.c.seq).where(t.event.c.seq < rows[0].seq).limit(1)
            ).first()
            earlier = rows[0].seq if older is not None else None
        items = message_views(conn, rows, mine)
        return JSONResponse({"items": items, "cursor": cursor, "earlier": earlier})


def load_message(conn: Connection, seq: str) -> dict[str, Any]:
    row = conn.execute(select(t.event).where(t.event.c.seq == int(seq))).one()
    return message_view(conn, row)


idempotency.LOADERS["message"] = idempotency.plain(load_message)


@router.post("/projects/{slug}/conversations/{conversation_id}/messages")
def send_message(
    slug: str, conversation_id: str, body: ChatIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = _locked(conn, caller, slug)
        if group_chats.is_group(conversation_id):
            _group(conn, mine, conversation_id)  # not_found for anyone without access
        else:
            _party(conn, mine, conversation_id, hidden=False)
        view = post_message(
            conn,
            mine,
            caller,
            MessageIn(kind="message", type="chat", body=body.body, conversation_id=conversation_id),
        )
        return idempotency.Outcome(
            201, "message", str(view["seq"]), load_message(conn, str(view["seq"]))
        )

    return idempotency.run(engine_of(request), request, caller, action)
