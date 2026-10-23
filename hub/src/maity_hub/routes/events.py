"""Reading events, the long-poll, posting messages, redaction (docs/api.md §8)."""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, select, update
from starlette.concurrency import run_in_threadpool

from maity_hub import clock, events, idempotency, longpoll, mentions
from maity_hub import tables as t
from maity_hub.access import Membership, member_row, membership
from maity_hub.auth.caller import Caller
from maity_hub.deps import AnyCaller, EventsCaller, engine_of, wait_of
from maity_hub.errors import ApiError, forbidden, invalid, not_found
from maity_hub.models import Strict, Written, markdown
from maity_hub.views import event_views

router = APIRouter()

FALLBACK_SECONDS = 2.0
PAGE_DEFAULT, PAGE_MAX = 50, 200
MESSAGE_TYPES = (
    "interface_change",
    "blocker",
    "go_request",
    "review_result",
    "handover",
    "notice",
    "chat",
)


class MessageIn(Written):
    kind: Literal["message"]
    type: str
    to: str | None = None
    body: str = markdown(min_length=1)
    task_id: str | None = None
    conversation_id: str | None = None


class RedactIn(Strict):
    reason: str = markdown(min_length=1)
    # What the caller means to redact (§8.5); the hub redacts nothing else. Checked by
    # hand, so that any other value, `null` included, is `unknown` and not a type error.
    expect: Any = None


def _closed_group_chat_message(row: Any) -> bool:
    """A message of a closed group chat (§9). The hub has no group chats yet, so no
    event is one, and `expect: closed_chat_message` refuses everything until it has."""
    del row
    return False


def load_event(conn: Connection, seq: str, reader: Any = None) -> dict[str, Any]:
    row = conn.execute(select(t.event).where(t.event.c.seq == int(seq))).one()
    return event_views(conn, [row], reader)[0]


def _load_for_caller(conn: Connection, seq: str, request: Request) -> dict[str, Any]:
    """A replay shows the event as the caller saw it the first time: the caller's
    membership in the event's project is the reader (§8.5)."""
    row = conn.execute(select(t.event).where(t.event.c.seq == int(seq))).one()
    slug = conn.execute(select(t.project.c.slug).where(t.project.c.id == row.project_id)).scalar()
    try:
        reader = membership(conn, request.state.caller, slug) if slug else None
    except ApiError:
        reader = None
    return event_views(conn, [row], reader)[0]


idempotency.LOADERS["event"] = _load_for_caller


# --- reading and waiting -------------------------------------------------------------------


SEQ_MAX = 2**63 - 1  # BIGINT


def parse_after(raw: str | None) -> int | Literal["latest"]:
    if raw is None:
        return 0
    if raw == "latest":
        return "latest"
    if not raw.isascii() or not raw.isdigit() or int(raw) > SEQ_MAX:
        raise invalid({"after": "not_a_seq"})
    return int(raw)


def parse_limit(request: Request) -> int:
    raw_limit = request.query_params.get("limit", str(PAGE_DEFAULT))
    if not raw_limit.isdigit() or not 1 <= int(raw_limit) <= PAGE_MAX:
        raise invalid({"limit": "out_of_range"})
    return int(raw_limit)


@router.get("/projects/{slug}/events")
async def read_events(slug: str, request: Request, caller: EventsCaller) -> JSONResponse:
    wait = wait_of(request)
    after_param = parse_after(request.query_params.get("after"))
    limit = parse_limit(request)
    engine = engine_of(request)

    def start() -> tuple[Membership, int, bool]:
        with engine.begin() as conn:
            mine = membership(conn, caller, slug)
            mine.require("project:read")
            supervised = (
                caller.kind == "agent"
                and conn.execute(
                    select(t.agent_session.c.supervisor).where(
                        t.agent_session.c.id == caller.session_id
                    )
                ).scalar()
                is not None
            )
            if after_param == "latest":
                after = events.highest_readable(conn, mine.project.id, mine.row, mine.principal_id)
            else:
                after = after_param
                _acknowledge(conn, caller, after)
            return mine, after, supervised

    mine, after, supervised = await run_in_threadpool(start)
    if after_param == "latest" and wait == 0:
        # From now on, without the history; acknowledges nothing (§8.3).
        return answer([], after, superseded=False)

    def read(waking: bool, since: int) -> tuple[list[dict[str, Any]], int]:
        with engine.begin() as conn:
            if waking:
                rows, examined = events.read_waking(
                    conn, mine.project.id, mine.row, mine.principal_id, since, limit, supervised
                )
            else:
                rows, examined, _ = events.read(
                    conn, mine.project.id, mine.row, mine.principal_id, since, limit
                )
            if caller.kind == "agent":  # a human's side is the conversation endpoint (§9)
                events.mark_delivered(conn, rows, mine.principal_id)
            cursor = rows[-1].seq if rows else max(examined, since)
            return event_views(conn, rows, mine), cursor

    if wait == 0:
        items, cursor = await run_in_threadpool(read, False, after)
        return answer(items, cursor, superseded=False)

    waiter = longpoll.Waiter(
        key=caller.credential_id or f"session:{caller.human_session}",
        project_id=mine.project.id,
        session_id=caller.session_id,
        loop=asyncio.get_running_loop(),
    )
    longpoll.registry.enter(waiter)
    try:
        deadline = time.monotonic() + wait
        since = after
        while True:
            if waiter.superseded:
                # Nothing read, nothing delivered, the cursor where it was: the wait that
                # took over owns what came in (§8.3).
                return answer([], after, superseded=True)
            if await request.is_disconnected():
                return answer([], since, superseded=False)
            waiter.event.clear()  # an event after this read wakes the next pass
            items, cursor = await run_in_threadpool(read, True, since)
            if waiter.superseded:
                return answer([], after, superseded=True)
            if items:
                return answer(items, cursor, superseded=False)
            since = cursor  # nothing there wakes us: the next pass starts behind it
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return answer([], cursor, superseded=False)
            with contextlib.suppress(TimeoutError):  # the fallback re-read
                await asyncio.wait_for(waiter.event.wait(), min(remaining, FALLBACK_SECONDS))
    finally:
        longpoll.registry.leave(waiter)


def answer(items: list[dict[str, Any]], cursor: int, superseded: bool) -> JSONResponse:
    return JSONResponse(
        {
            "items": items,
            "cursor": cursor,
            "server_time": clock.rfc3339(clock.now()),
            "superseded": superseded,
        }
    )


def _acknowledge(conn: Connection, caller: Caller, after: int) -> None:
    """`after=N` acknowledges everything up to N for this session (§8.3)."""
    if caller.session_id is None or after <= 0:
        return
    conn.execute(
        update(t.agent_session)
        .where(
            t.agent_session.c.id == caller.session_id,
            t.agent_session.c.acknowledged_seq < after,
        )
        .values(acknowledged_seq=after)
    )


# --- posting messages ------------------------------------------------------------------


def chat_parties(conn: Connection, mine: Membership, agent_id: str) -> tuple[Any, Any]:
    """The agent's membership and its owning human's; both must be members (§9)."""
    agent = member_row(conn, mine.project.id, agent_id)
    if agent.agent_id is None:
        raise not_found()
    owner_id = conn.execute(
        select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == agent.agent_id)
    ).scalar_one()
    try:
        human = member_row(conn, mine.project.id, owner_id)
    except ApiError:
        raise not_found() from None
    return agent, human


def post_message(
    conn: Connection, mine: Membership, caller: Caller, body: MessageIn
) -> dict[str, Any]:
    """Validate and emit one `message` event; returns its view."""
    if body.type not in MESSAGE_TYPES:
        raise invalid({"type": "unknown"})
    me = mine.principal_id
    if body.type == "chat":
        if body.conversation_id is None:
            raise invalid({"conversation_id": "required_for_chat"})
        if body.to is not None:
            raise invalid(
                {"to": "not_for_chat"}, "a chat goes to the other party of its conversation"
            )
        try:
            agent, human = chat_parties(conn, mine, body.conversation_id)
        except ApiError:
            raise invalid({"conversation_id": "not_a_conversation"}) from None
        parties = [agent.agent_id, human.human_id]
        if me not in parties:
            raise forbidden(message="only the two parties write in a conversation")
        to = parties[1] if me == parties[0] else parties[0]
        audience = [f"member:{p}" for p in parties]
    else:
        if body.conversation_id is not None:
            raise invalid({"conversation_id": "chat_only"})
        if body.to is None:
            raise invalid({"to": "required"})
        to = body.to
        if to == "all":
            target = "all"
        elif to.startswith("role:"):
            from maity_hub.scopes import ROLES

            if to.removeprefix("role:") not in ROLES:
                raise invalid({"to": "unknown_role"})
            target = to
        else:
            try:
                member_row(conn, mine.project.id, to)
            except ApiError:
                raise invalid({"to": "not_a_member"}) from None
            target = f"member:{to}"
        audience = list(dict.fromkeys([target, f"member:{me}"]))
    if body.task_id is not None:
        found = conn.execute(
            select(t.card.c.id).where(
                t.card.c.id == body.task_id, t.card.c.project_id == mine.project.id
            )
        ).first()
        if found is None:
            raise invalid({"task_id": "unknown_task"})
    mentioned: list[dict[str, Any]] = []
    if body.type != "chat":  # a chat stays between its two parties (§8.6)
        mentioned = mentions.resolve(conn, mine.project.id, body.body, "body")
        named = mentions.members(mentioned)
        roles = _roles(conn, mine.project.id, named)
        pinged = [
            m
            for m in named
            if not (
                "all" in audience or f"member:{m}" in audience or f"role:{roles[m]}" in audience
            )
        ]
        mentions.charge(conn, mine.id, len(pinged))
        # Only those `to` does not reach already: a member that `all`, its role or its
        # own `member:` covers is not woken a second way (§8.2); the mention stays.
        audience = list(dict.fromkeys([*audience, *(f"member:{m}" for m in pinged)]))
    payload = {
        "type": body.type,
        "to": to,
        "body": body.body,
        "conversation_id": body.conversation_id,
        "task_id": body.task_id,
        "mentions": mentioned,
    }
    seq = events.emit(
        conn,
        mine.project.id,
        "message",
        audience,
        payload,
        actor=caller.actor(mine.id),
        subject=("task", body.task_id) if body.task_id else None,
        conversation_id=body.conversation_id,
    )
    return load_event(conn, str(seq))


def _roles(conn: Connection, project_id: str, principals: list[str]) -> dict[str, str]:
    """The role of each mentioned member, to tell who `to` already reaches."""
    if not principals:
        return {}
    rows = conn.execute(
        select(t.membership.c.agent_id, t.membership.c.human_id, t.membership.c.role).where(
            t.membership.c.project_id == project_id,
            t.membership.c.active.is_(True),
            t.membership.c.agent_id.in_(principals) | t.membership.c.human_id.in_(principals),
        )
    ).all()
    return {(r.agent_id or r.human_id): r.role for r in rows}


@router.post("/projects/{slug}/events")
def post_event(slug: str, body: MessageIn, request: Request, caller: AnyCaller) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine.require("events:post")
        view = post_message(conn, mine, caller, body)
        return idempotency.Outcome(201, "event", str(view["seq"]), view)

    return idempotency.run(engine_of(request), request, caller, action)


# --- redaction --------------------------------------------------------------------------------


@router.post("/projects/{slug}/events/{seq}/redact")
def redact(
    slug: str,
    seq: Annotated[int, Path(ge=1, le=SEQ_MAX)],
    body: RedactIn,
    request: Request,
    caller: AnyCaller,
) -> JSONResponse:
    if "expect" in body.model_fields_set and body.expect != "closed_chat_message":
        raise invalid({"expect": "unknown"}, "expect names closed_chat_message or is left out")

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine.require("events:admin")
        row = conn.execute(
            select(t.event).where(t.event.c.seq == seq, t.event.c.project_id == mine.project.id)
        ).first()
        if row is None:
            raise not_found()
        # What the caller cannot read does not exist for it; no later refusal may say
        # otherwise (§8.5).
        if not events.readable_by(
            row, mine.row, mine.principal_id, events.hidden_redactions(conn, [row], mine.row)
        ):
            raise not_found()
        # The tombstone's event reaches whoever could read the event, never more (§8.5).
        audience = list(row.audience or [])
        if row.conversation_id is not None:
            # A chat is redacted only by its human party; to anyone else it does not
            # exist, and the tombstone's event goes to the two parties (§8.5). Checked
            # first: no later refusal may tell anyone else that the event exists.
            _, human = chat_parties(conn, mine, row.conversation_id)
            if mine.id != human.id:
                raise not_found()
            audience = [f"member:{row.conversation_id}", f"member:{human.human_id}"]
        if row.kind == "event_redacted":  # a tombstone's record is not itself redacted
            raise ApiError(
                400, "invalid", "a redaction cannot be redacted", {"reason": "already_redacted"}
            )
        # Compared only for an event the caller could redact without it (§8.5): `expect`
        # never tells anyone else what a `seq` is.
        if "expect" in body.model_fields_set and not _closed_group_chat_message(row):
            raise invalid({"expect": "mismatch"}, "the event is not a closed group chat's message")
        if not row.redacted:
            # The one mutation the log allows, itself on record (§8.5).
            tombstone = {
                "redacted": True,
                "reason": body.reason,
                "by": mine.principal_id,
                "at": clock.rfc3339(clock.now()),
            }
            conn.execute(
                update(t.event).where(t.event.c.seq == seq).values(payload=tombstone, redacted=True)
            )
            events.emit(
                conn,
                mine.project.id,
                "event_redacted",
                audience,
                {"seq": seq, "reason": body.reason},
                actor=caller.actor(mine.id),
                subject=("event", str(seq)),
                # A chat's notice is the chat's, as the message was: no see-all reaches it.
                conversation_id=row.conversation_id,
            )
        return idempotency.Outcome(200, "event", str(seq), load_event(conn, str(seq), mine))

    return idempotency.run(engine_of(request), request, caller, action)
