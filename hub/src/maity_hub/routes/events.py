"""Reading events, the long-poll, posting messages, redaction (docs/api.md §8)."""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse
from pydantic import Field, ValidationInfo, field_validator
from pydantic_core import PydanticCustomError
from sqlalchemy import Connection, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from maity_hub import (
    CLI_VERSION,
    attachment_store,
    attachments,
    chat_gate,
    chat_request,
    clock,
    events,
    group_chats,
    idempotency,
    instances,
    longpoll,
    mentions,
    namespace,
    not_listening,
    project_roles,
    review_delivery,
    reviews,
    wakeups,
)
from maity_hub import tables as t
from maity_hub.access import Membership, member_row, membership
from maity_hub.auth.caller import Caller
from maity_hub.config import Settings
from maity_hub.deps import AnyCaller, EventsCaller, engine_of, settings_of, wait_of
from maity_hub.errors import ApiError, forbidden, humans_only, invalid, not_found
from maity_hub.models import Strict, Written, markdown
from maity_hub.namespace import ProjectRoute
from maity_hub.views import event_views

router = APIRouter(route_class=ProjectRoute)

FALLBACK_SECONDS = 2.0
PAGE_DEFAULT, PAGE_MAX = 50, 200
MESSAGE_TYPES = (
    "interface_change",
    "blocker",
    "go_request",
    "review_result",
    "handover",
    "notice",
    "update",
    "chat",
)


class MessageIn(Written):
    kind: Literal["message"]
    type: str
    to: str | None = None
    attachments: list[str] = Field(default_factory=list)
    body: str = markdown()
    task_id: str | None = None
    conversation_id: str | None = None
    to_instance: str | None = None  # a direct chat message to one instance of the agent (§9.1)
    review: Any = None  # a `review_result`'s object (§8.4), checked in `post_message`

    @field_validator("body")
    @classmethod
    def _text_or_attachments(cls, value: str, info: ValidationInfo) -> str:
        """A message has text, or names attachments and may then have none (§8.7)."""
        if not value and not info.data.get("attachments"):
            raise PydanticCustomError(
                "string_too_short", "String should have at least 1 character", {"min_length": 1}
            )
        return value


class RedactIn(Strict):
    reason: str = markdown(min_length=1)
    # What the caller means to redact (§8.5); the hub redacts nothing else. Checked by
    # hand, so that any other value, `null` included, is `unknown` and not a type error.
    expect: Any = None


def load_event(conn: Connection, seq: str, reader: Any = None) -> dict[str, Any]:
    row = conn.execute(select(t.event).where(t.event.c.seq == int(seq))).one()
    return event_views(conn, [row], reader)[0]


def _load_for_caller(conn: Connection, seq: str, request: Request) -> dict[str, Any]:
    """A replay shows the event as the caller saw it the first time: the caller's
    membership in the event's project is the reader (§8.5)."""
    row = conn.execute(select(t.event).where(t.event.c.seq == int(seq))).one()
    slug = namespace.name_of(conn, row.project_id)
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


@router.get("/projects/{owner}/{slug}/events")
async def read_events(slug: str, request: Request, caller: EventsCaller) -> JSONResponse:
    wait = wait_of(request)
    after_param = parse_after(request.query_params.get("after"))
    limit = parse_limit(request)
    engine = engine_of(request)

    served_param = request.query_params.get("for")
    if after_param == "latest" and wait == 0 and served_param is None:
        # From now on, without the history; acknowledges nothing (§8.3). The same code builds
        # the `head` part of `GET /bootstrap` (§5.4).
        def head() -> dict[str, Any]:
            with engine.begin() as conn:
                return head_body(conn, caller, slug)

        return JSONResponse(await run_in_threadpool(head))

    def start() -> tuple[Caller, Membership, int, bool]:
        with engine.begin() as conn:
            reader = _reader(conn, caller, served_param, request, slug, waiting=wait > 0)
            mine = membership(conn, reader, slug)
            mine.require("project:read")
            # A runner supervises the bridge's session, not the agent it reads for (§15.11).
            supervised = (
                caller.kind == "agent"
                and reader.bridge is None
                and conn.execute(
                    select(t.agent_session.c.supervisor).where(
                        t.agent_session.c.id == caller.session_id
                    )
                ).scalar()
                is not None
            )
            if after_param == "latest":
                after = events.highest_readable(
                    conn,
                    mine.project.id,
                    mine.row,
                    mine.principal_id,
                    carried=reader.bridge is not None,
                )
            else:
                after = after_param
                if reader.bridge is None:  # a bridge's read for an agent moves no cursor (§2.3)
                    _acknowledge(conn, caller, after)
            not_listening.called(conn, caller.session_id)
            return reader, mine, after, supervised

    reader, mine, after, supervised = await run_in_threadpool(start)
    carried = reader.bridge is not None
    if after_param == "latest" and wait == 0:
        # A bridge's read for an agent (`for`); without it, `head_body` above (§8.3).
        return answer([], after, superseded=False)

    def read(waking: bool, since: int) -> tuple[list[dict[str, Any]], int] | None:
        """The events after `since` and the new cursor; None when a bridge's connection
        ended or the bridge was isolated or removed since the call began (§2.3)."""
        with engine.begin() as conn:
            if carried and not _still_carried(conn, reader):
                return None
            row = mine.row
            if caller.kind == "agent":
                # As of now, not as of the call's start: an isolation that committed since
                # reads nothing more (§6.2, "Isolation").
                row = conn.execute(select(t.membership).where(t.membership.c.id == mine.id)).one()
                if waking and events.is_isolated(row):
                    # Ended here too, not only by the process that isolated it: that one's
                    # registry holds only its own waits (hub/context/replicas.md).
                    return None
            if waking:
                rows, examined = events.read_waking(
                    conn,
                    mine.project.id,
                    row,
                    mine.principal_id,
                    since,
                    limit,
                    instance=mine.instance,
                    # The bridge's own credential is not the served agent's (dormancy, §6.17).
                    credential_id=None if carried else caller.credential_id,
                    supervised=supervised,
                    carried=carried,
                )
            else:
                rows, examined, _ = events.read(
                    conn, mine.project.id, row, mine.principal_id, since, limit, carried=carried
                )
            # A human's side is the conversation endpoint (§9); a bridge reading for an agent
            # delivers nothing to it (§2.3).
            if caller.kind == "agent" and not carried:
                events.mark_delivered(conn, rows, mine.principal_id)
            cursor = rows[-1].seq if rows else max(examined, since)
            return event_views(conn, rows, mine), cursor

    def quiet(since: int) -> bool:
        """Whether a later pass of the wait may skip its read (tsk-x1rsd4r6htcv): no event of
        the project past `since`, and the reader as the read would find it, an agent's row
        present and not isolated, a bridge's connection still carrying it. One statement
        (two with the bridge's check) where the read costs four for an agent or a bridge and
        two for a human, without `BEGIN IMMEDIATE` and the `long_poll` row. Under the project's lock
        `seq` follows commit order (`events.emit`), and the read reads only `seq > since`,
        so it could only answer nothing. Anything else is not quiet and reads in full,
        which ends the wait or delivers exactly as it does without this check."""
        with engine.begin() as conn:
            if carried and not _still_carried(conn, reader):
                return False
            head = (
                select(func.max(t.event.c.seq))
                .where(t.event.c.project_id == mine.project.id)
                .scalar_subquery()
            )
            if caller.kind == "agent":
                found = conn.execute(
                    select(t.membership, head.label("head")).where(t.membership.c.id == mine.id)
                ).first()
                if found is None or events.is_isolated(found):
                    return False
                top = found.head
            else:
                top = conn.execute(select(head)).scalar()
            return top is None or top <= since

    if wait == 0:
        found = await run_in_threadpool(read, False, after)
        if found is None:
            return answer([], after, superseded=False)
        return answer(*found, superseded=False)

    key = caller.credential_id or f"session:{caller.human_session}"
    waiter = longpoll.Waiter(
        # One wait per served agent beside the bridge's own: none supersedes another (§2.3).
        key=f"{key}|for:{reader.agent_id}" if carried else key,
        project_id=mine.project.id,
        session_id=caller.session_id,
        loop=asyncio.get_running_loop(),
        membership_id=reader.membership_id,
        bridge_id=reader.bridge.bridge_id if reader.bridge else None,
        bridge_membership_id=reader.bridge.membership_id if reader.bridge else None,
    )
    closed = await wakeups.opened(
        engine,
        "events",
        waiter.key,
        lambda: longpoll.registry.supersede(waiter),
        waiter.started_at,
    )
    longpoll.registry.enter(waiter)
    try:
        deadline = time.monotonic() + wait
        since = after
        passes = 0
        while True:
            if waiter.superseded:
                # Nothing read, nothing delivered, the cursor where it was: the wait that
                # took over owns what came in (§8.3).
                return answer([], after, superseded=True)
            if await request.is_disconnected() or waiter.ended:
                return answer([], since, superseded=False)
            waiter.event.clear()  # an event after this read wakes the next pass
            # The first pass reads; a later one first looks whether anything moved, after the
            # clear above, so an event committed after the look still wakes the pause below.
            if passes and await run_in_threadpool(quiet, since):
                found = ([], since)
            else:
                found = await run_in_threadpool(read, True, since)
            passes += 1
            if found is None:
                return answer([], since, superseded=False)
            items, cursor = found
            if waiter.superseded:
                return answer([], after, superseded=True)
            if items:
                return answer(items, cursor, superseded=False)
            since = cursor  # nothing there wakes us: the next pass starts behind it
            remaining = deadline - time.monotonic()
            if remaining <= 0 or longpoll.stopping.is_set():
                # Also when the process stops: the client simply waits again (§8.3).
                return answer([], cursor, superseded=False)
            with contextlib.suppress(TimeoutError):  # the fallback re-read
                await asyncio.wait_for(waiter.event.wait(), min(remaining, FALLBACK_SECONDS))
    finally:
        closed()
        longpoll.registry.leave(waiter)


SEQ_DIGITS = len(str(SEQ_MAX))


def parse_seq(raw: str) -> int:
    """One event's `seq` from the path, before anything is read (§8.9): `0` or ASCII digits
    without a leading zero, at most 2⁶³ − 1. `068216` is invalid, not 68216."""
    if (
        not raw.isascii()
        or not raw.isdigit()
        or len(raw) > SEQ_DIGITS
        or (len(raw) > 1 and raw[0] == "0")
        or int(raw) > SEQ_MAX
    ):
        raise invalid({"seq": "not_a_seq"})
    return int(raw)


@router.get("/projects/{owner}/{slug}/events/{seq}")
def read_event(slug: str, seq: str, request: Request, caller: AnyCaller) -> JSONResponse:
    """One event by its `seq` (§8.9): exactly what `GET /events?after=<seq − 1>` would serve
    this caller now, plus `conversation_id` for a caller who reads that conversation now. It
    is the event list's own read, bounded to this one `seq`, so the rule is the list's and not
    a copy of it (hub/context/events.md). Whoever may not read the event gets the `not_found`
    of a `seq` nobody has. Reading acknowledges nothing, delivers nothing, wakes nobody and
    does not count as listening (§5.3): it writes nothing.

    A bridge reads for an agent with `Maity-For` only, which the caller already resolved
    (§2.3). §8.9 gives this route the list's `Maity-For` rule and no `for` query, so a `for`
    is refused rather than ignored: ignored, the bridge would get its own answer for the
    agent's, a silent `404` or the bridge's view where it asked for the agent's."""
    if "for" in request.query_params:  # before the seq: both come from the request alone
        raise invalid({"for": "not_allowed"}, "this route reads no for; send Maity-For")
    number = parse_seq(seq)
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)  # not a member here: `not_found`, as for any seq
        mine.require("project:read")
        rows, _, _ = events.read(
            conn,
            mine.project.id,
            mine.row,
            mine.principal_id,
            number - 1,
            1,
            until=number,
            carried=getattr(caller, "bridge", None) is not None,  # `Maity-For` (§2.3)
        )
        if not rows:
            raise not_found()
        view = event_views(conn, rows, mine)[0]
        from maity_hub.routes import conversations  # it imports this module

        conversation = rows[0].conversation_id
        view["conversation_id"] = (
            conversation
            if conversation is not None and conversations.reads_messages(conn, mine, conversation)
            else None
        )
        return JSONResponse(view)


def _reader(
    conn: Connection,
    caller: Caller,
    served: str | None,
    request: Request,
    slug: str,
    waiting: bool,
) -> Caller:
    """Who reads: the caller, or with `for` the agent its bridge reads for, as its
    `member:` token would (§2.3). `Maity-For` already made the caller that agent; a `for`
    beside it must name the same one."""
    if served is None:
        return caller
    if caller.bridge is not None:
        if served != caller.agent_id:
            raise invalid({"for": "not_maity_for"}, "for names another agent than Maity-For")
        return caller
    from maity_hub import bridges

    return bridges.carry(conn, caller, served, request.url.path, slug, renew_leases=not waiting)


def _still_carried(conn: Connection, reader: Caller) -> bool:
    """The connection a bridge reads through is live and the bridge an active agent that is
    not isolated, as of now: a long-poll outlives the check at its start (§2.3)."""
    assert reader.bridge is not None
    return (
        conn.execute(
            select(t.bridge.c.id)
            .join(t.membership, t.membership.c.id == t.bridge.c.bridge)
            .where(
                t.bridge.c.id == reader.bridge.bridge_id,
                t.bridge.c.live.is_(True),
                t.membership.c.active.is_(True),
                t.membership.c.isolated_since.is_(None),
            )
        ).first()
        is not None
    )


def answer(items: list[dict[str, Any]], cursor: int, superseded: bool) -> JSONResponse:
    return JSONResponse(answer_body(items, cursor, superseded))


def answer_body(items: list[dict[str, Any]], cursor: int, superseded: bool) -> dict[str, Any]:
    return {
        "items": items,
        "cursor": cursor,
        "server_time": clock.rfc3339(clock.now()),
        "superseded": superseded,
        "cli_version": CLI_VERSION,
    }


def head_body(conn: Connection, caller: Caller, slug: str) -> dict[str, Any]:
    """`?after=latest&wait=0` without `for` (§8.3): the head, no history, nothing
    acknowledged. `read_events` answers that query with it, and it is the `head` part of
    `GET /bootstrap` (§5.4)."""
    mine = membership(conn, caller, slug)
    mine.require("project:read")
    after = events.highest_readable(
        conn,
        mine.project.id,
        mine.row,
        mine.principal_id,
        carried=getattr(caller, "bridge", None) is not None,  # `Maity-For` (§2.3)
    )
    not_listening.called(conn, caller.session_id)
    return answer_body([], after, superseded=False)


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
    conn: Connection,
    mine: Membership,
    caller: Caller,
    body: MessageIn,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Validate and emit one `message` event; returns its view. The attachments it names
    are bound to it in the same transaction (§8.7)."""
    if body.type not in MESSAGE_TYPES:
        raise invalid({"type": "unknown"})
    if body.type == "update" and body.task_id is None:
        raise invalid({"task_id": "required_for_update"}, "an update is news on a card")
    me = mine.principal_id
    group: Any = None
    sides: list[str] = []  # a chat's sides as it is written (§9.6)
    review: dict[str, Any] | None = None
    if body.type == "review_result":
        review, problems = reviews.check(body.review)
        if problems:
            raise invalid(problems)
    elif body.review is not None:
        raise invalid({"review": "not_allowed"})
    if body.to_instance is not None and (
        body.type != "chat"
        or (body.conversation_id is not None and group_chats.is_group(body.conversation_id))
    ):
        raise invalid({"to_instance": "direct_chat_only"}, "an instance is named in a direct chat")
    if body.type == "chat":
        if body.conversation_id is None:
            raise invalid({"conversation_id": "required_for_chat"})
        if body.to is not None:
            raise invalid(
                {"to": "not_for_chat"}, "a chat goes to the other party of its conversation"
            )
    if body.type == "chat" and group_chats.is_group(body.conversation_id):
        assert body.conversation_id is not None
        group = _group_for_posting(conn, mine, body.conversation_id)
        to = group.id
        current = group_chats.stays(conn, group.id)
        audience = group_chats.audience(current)
        sides = chat_gate.sides_of(conn, current)
    elif body.type == "chat":
        assert body.conversation_id is not None
        if caller.bridge is not None:
            # A bridge reads the direct conversation as an observer, on either route (§2.3).
            raise ApiError(
                403,
                "forbidden",
                "a bridge does not write in the direct conversation",
                {"reason": "bridge_observer"},
            )
        try:
            agent, human = chat_parties(conn, mine, body.conversation_id)
        except ApiError:
            raise invalid({"conversation_id": "not_a_conversation"}) from None
        parties = [agent.agent_id, human.human_id]
        if me not in parties:
            raise forbidden(message="only the two parties write in a conversation")
        to = parties[1] if me == parties[0] else parties[0]
        if agent.isolated_since is not None:  # nothing reaches an isolated agent (§6.2)
            raise invalid({"to": "isolated"}, "the agent is isolated")
        audience = [f"member:{p}" for p in parties]
        sides = [human.human_id]  # the agent's owner: one side
        if body.to_instance is not None:
            # The human's message wakes exactly one instance of the agent, resolved as an
            # address in a message's `to` is; the whole team still reads it (§9.1, §8.2).
            if me != parties[1]:
                raise invalid({"to_instance": "human_only"}, "only the human names an instance")
            if not instances.INSTANCE_PATTERN.fullmatch(body.to_instance):
                raise invalid({"to_instance": "not_an_instance"})
            target = instances.addressed(
                conn, agent.id, parties[0], body.to_instance, "to_instance"
            )
            audience = [target, f"member:{parties[1]}"]
    else:
        if body.conversation_id is not None:
            raise invalid({"conversation_id": "chat_only"})
        if body.to is None and body.type not in ("update", "review_result"):
            raise invalid({"to": "required"})
        to = body.to
        if to is None:
            # An update reaches the card's watchers, which `emit` adds (§6.4); a review result
            # its author and both leads, added below (§8.4).
            target = f"member:{me}"
        elif to == "all":
            target = "all"
        elif to.startswith(("role:", "trust:")):
            from maity_hub.scopes import token_known

            if not token_known(to, project_roles.names(mine.project)):
                raise invalid({"to": "unknown_role"})
            target = to
        else:
            principal, instance = instances.split_address(to)
            try:
                addressee = member_row(conn, mine.project.id, principal)
            except ApiError:
                raise invalid({"to": "not_a_member"}) from None
            if addressee.isolated_since is not None:
                raise invalid({"to": "isolated"}, "the agent is isolated")
            # One instance of a team: its token wakes only it, the team reads it; a replaced
            # instance's address reaches its successor (§8.2).
            target = (
                instances.token(principal, None)
                if instance is None
                else instances.addressed(conn, addressee.id, principal, instance, "to")
            )
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
    if group is not None:
        # Against the chat's participants only; anyone else's handle stays text, and
        # each participant mentioned but the writer counts one ping (§8.6).
        inside = {group_chats.principal(s) for s in current if not s.waiting}  # §9.6
        mentioned = mentions.resolve(conn, mine.project.id, body.body, "body", among=inside)
        mentions.charge(conn, mine.id, len([m for m in mentions.members(mentioned) if m != me]))
        # An instance mention wakes the instance it comes down to, a successor when the one
        # named was replaced (§8.2, §8.6): `events.wakes` reads that token, not the written id.
        audience = list(
            dict.fromkeys(
                [
                    *audience,
                    *(
                        mentions.instance_token(
                            conn, mine.project.id, m["member_id"], m["instance"]
                        )
                        for m in mentioned
                        if m["instance"] is not None
                    ),
                ]
            )
        )
    elif body.type != "chat":  # a direct chat stays between its two parties (§8.6)
        mentioned = mentions.resolve(conn, mine.project.id, body.body, "body")
        roles = _roles(conn, mine.project.id, mentions.members(mentioned))
        # Only what `to` does not reach already, judged per token (§8.2): a team mention
        # is reached by `all`, its role or its own `member:`; an instance mention only by
        # `all`, its role or its own `instance:` token — `to` naming the team wakes the
        # instances its wake rule chooses, not necessarily the one named (§8.6); a dormant
        # instance only by its own token (§6.17). The mention stays either way.
        pinged: dict[str, str] = {}  # token -> member
        for m in mentioned:
            token = mentions.instance_token(conn, mine.project.id, m["member_id"], m["instance"])
            reached = (
                "all" in audience
                or token in audience
                or bool(roles[m["member_id"]] & set(audience))
            )
            if m["instance"] is not None and instances.token_is_dormant(
                conn, mine.project.id, token
            ):
                reached = token in audience  # a dormant instance is reached by its token alone
            if not reached:
                pinged[token] = m["member_id"]
        mentions.charge(conn, mine.id, len({m for m in pinged.values() if m != me}))
        audience = list(dict.fromkeys([*audience, *pinged]))
    if review is not None:
        audience = _deliver_review(conn, mine, body.task_id, review, audience)
    if body.type == "chat":  # where a chat text may cross the owner boundary (§9.6)
        chat_gate.boundary(conn, mine.project.id, me, body.body, sides)
    # A free work message from another side reaches an agent only on its owner's yes (§9.6).
    audience, held = chat_gate.hold(conn, mine.project.id, mine, body.type, audience)
    named = attachments.bind(conn, mine, body.attachments, settings)
    payload = {
        "type": body.type,
        "to": to,
        "body": body.body,
        "conversation_id": body.conversation_id,
        "task_id": body.task_id,
        "mentions": mentioned,
        "attachments": [attachments.meta(r) for r in named],
        "held": held,
    }
    if group is not None:  # where an agent that lost the chat answers (§9.4)
        payload["conversation"] = {"id": group.id, "kind": "group", "title": group.title}
    if body.type == "chat":  # the instance a direct chat message names, as written (§9.1)
        payload["to_instance"] = body.to_instance
    if review is not None:  # what a review result judged and read (§8.4)
        payload["review"] = review
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
    attachments.attach(conn, named, seq)
    if held:  # the owner of each agent it was held for is asked (§9.6, "The request")
        author = (me, "agent" if mine.row.agent_id else "human")
        side = chat_gate.owners_of(conn, [me]).get(me, me) if mine.row.agent_id else me
        chat_request.note_held(conn, mine.project.id, seq, body.type, author, side, held)
    if group is not None:  # whoever speaks has read up to there (§9.2)
        remember_read(conn, mine.id, group.id, seq)
    return load_event(conn, str(seq), mine)


def _deliver_review(
    conn: Connection,
    mine: Membership,
    task_id: str | None,
    review: dict[str, Any],
    audience: list[str],
) -> list[str]:
    """A review result's author and both leads (§8.4). The author's instance takes the place
    of the author's `member:` token that `to` or a mention put in the audience, and is added
    unless the audience holds that same instance token. A member token (a lead, or an author whose
    card was claimed for the team) is added unless `to` or a mention reaches the member
    already: one of its role or trust tokens, or a token of its own. `all` counts for
    neither: it does not wake a supervised member, and beside it an added token wakes
    only such a one. One that then reaches nobody but its sender is `invalid`."""
    sender = conn.execute(select(t.membership).where(t.membership.c.id == mine.id)).one()
    found = review_delivery.recipients(conn, mine.project.id, sender, task_id, review)
    for r in found:
        if r.token.startswith("instance:"):
            # The reviewer means the author: the member id would wake other instances by the
            # agent's `wake` rule (§6.18). The payload's `to` stays as written.
            member = f"member:{r.member_id}"
            audience = [r.token if token == member else token for token in audience]
    roles = _roles(conn, mine.project.id, [r.member_id for r in found])
    reached_members = {
        token.split(":", 1)[1].split("#", 1)[0]
        for token in audience
        if token.startswith(("member:", "instance:"))
    }
    added = [
        r.token
        for r in found
        if (
            r.token not in audience
            if r.token.startswith("instance:")
            else not (
                r.member_id in reached_members
                or bool(roles.get(r.member_id, set()) & set(audience))
            )
        )
    ]
    audience = list(dict.fromkeys([*audience, *added]))
    if set(audience) <= {f"member:{mine.principal_id}"}:
        raise invalid({"to": "required"}, "a review result that reaches nobody but its sender")
    return audience


def _group_for_posting(conn: Connection, mine: Membership, conversation_id: str) -> Any:
    """The open group chat the caller takes part in (§9.2), read under the project lock:
    a leave or a close that commits first is seen, so no stale post gets through and
    the audience is the participants as of the write."""
    events.lock_project(conn, mine.project.id)
    group = group_chats.find(conn, mine.project.id, conversation_id)
    found = group_chats.access(conn, conversation_id, mine) if group is not None else None
    if found is None and group is not None and chat_gate.waiting(conn, group.id, mine.id):
        raise chat_gate.refuse_waiting()  # it does not post before its owner's yes (§9.6)
    if found is None:
        raise invalid({"conversation_id": "not_a_conversation"})
    if found == "observer":
        raise ApiError(
            403, "forbidden", "an owner reads along and does not post", {"reason": "observer"}
        )
    if group.hub_thread:
        raise group_chats.round_thread()
    group_chats.refuse_closed(group)
    return group


def remember_read(conn: Connection, reader: int, conversation_id: str, seq: int) -> None:
    """Move the reader's read mark in a conversation up to `seq`, never down."""
    if conn.dialect.name == "postgresql":  # a human reader's held bells look again
        human_id = conn.execute(
            select(t.membership.c.human_id).where(t.membership.c.id == reader)
        ).scalar()
        if human_id is not None:
            wakeups.ring(conn, "bell", human_id)
    updated = conn.execute(
        update(t.conversation_read)
        .where(
            t.conversation_read.c.reader == reader,
            t.conversation_read.c.conversation_id == conversation_id,
            t.conversation_read.c.last_seq < seq,
        )
        .values(last_seq=seq)
    ).rowcount
    if updated:
        return
    exists = conn.execute(
        select(t.conversation_read.c.last_seq).where(
            t.conversation_read.c.reader == reader,
            t.conversation_read.c.conversation_id == conversation_id,
        )
    ).first()
    if exists is None:
        try:
            with conn.begin_nested():
                conn.execute(
                    insert(t.conversation_read).values(
                        reader=reader, conversation_id=conversation_id, last_seq=seq
                    )
                )
        except IntegrityError:  # another tab read first; the larger seq wins next time
            pass


def _roles(conn: Connection, project_id: str, principals: list[str]) -> dict[str, set[str]]:
    """The tokens of each mentioned member, to tell who `to` already reaches."""
    from maity_hub.scopes import tokens_of

    if not principals:
        return {}
    rows = conn.execute(
        select(
            t.membership.c.agent_id,
            t.membership.c.human_id,
            t.membership.c.trust,
            t.membership.c.role,
            t.membership.c.role_base,
        ).where(
            t.membership.c.project_id == project_id,
            t.membership.c.active.is_(True),
            t.membership.c.agent_id.in_(principals) | t.membership.c.human_id.in_(principals),
        )
    ).all()
    return {(r.agent_id or r.human_id): tokens_of(r.trust, r.role, r.role_base) for r in rows}


def writer(
    conn: Connection,
    caller: Caller,
    slug: str,
    *,
    conversation_id: str | None = None,
    seq: int | None = None,
) -> Membership:
    """The caller's membership for a write in a chat (a post, a change to the chat, a
    redaction). An owner outside the project gets `forbidden` with `reason: observer` only
    for a chat it reads along: the chat named by `conversation_id`, or the one the event
    `seq` belongs to. For anything else, a chat it does not read, a project event, an
    unknown id, it gets `not_found` like every other write and read (§9.2)."""
    try:
        return membership(conn, caller, slug)
    except ApiError:
        from maity_hub.routes.conversations import outsider

        found = outsider(conn, caller, slug)
        if found is None:
            raise
        if seq is not None:
            conversation_id = conn.execute(
                select(t.event.c.conversation_id).where(
                    t.event.c.seq == seq,
                    t.event.c.project_id == found.project.id,
                    t.event.c.kind == "message",
                )
            ).scalar()
        if (
            group_chats.is_group(conversation_id)
            and group_chats.find(conn, found.project.id, conversation_id or "") is not None
            and group_chats.access(conn, conversation_id or "", found) == "observer"
        ):
            raise ApiError(
                403, "forbidden", "an owner outside reads along only", {"reason": "observer"}
            ) from None
        raise


@router.post("/projects/{owner}/{slug}/events")
def post_event(slug: str, body: MessageIn, request: Request, caller: AnyCaller) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        # A chat post is a write in a chat an owner outside may read along; any other
        # message is not, and stays `not_found` for it (§9.2).
        mine = (
            writer(conn, caller, slug, conversation_id=body.conversation_id)
            if body.type == "chat"
            else membership(conn, caller, slug)
        )
        if not (body.type == "chat" and mine.trust == "guest"):
            mine.require("events:post")  # a guest chats in its conversations only (§2.3)
        view = post_message(conn, mine, caller, body, settings_of(request))
        return idempotency.Outcome(201, "event", str(view["seq"]), view)

    return idempotency.run(engine_of(request), request, caller, action)


# --- redaction --------------------------------------------------------------------------------


@router.post("/projects/{owner}/{slug}/events/{seq}/redact")
def redact(
    slug: str,
    seq: Annotated[int, Path(ge=1, le=SEQ_MAX)],
    body: RedactIn,
    request: Request,
    caller: AnyCaller,
) -> JSONResponse:
    if "expect" in body.model_fields_set and body.expect != "closed_chat_message":
        raise invalid({"expect": "unknown"}, "expect names closed_chat_message or is left out")

    store = attachment_store.optional_store(settings_of(request))

    def action(conn: Connection) -> idempotency.Outcome:
        mine = writer(conn, caller, slug, seq=seq)
        row = conn.execute(
            select(t.event).where(t.event.c.seq == seq, t.event.c.project_id == mine.project.id)
        ).first()
        if row is not None and group_chats.is_group(row.conversation_id):
            # A group chat's own rule: a place in the chat, no scope (§8.5).
            return _redact_in_group(conn, mine, caller, row, body, store)
        mine.require("events:admin")
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
        # never tells anyone else what a `seq` is. No group chat's message comes here.
        if "expect" in body.model_fields_set:
            raise invalid({"expect": "mismatch"}, "the event is not a closed group chat's message")
        _tombstone(conn, mine, caller, row, body.reason, audience, store)
        return idempotency.Outcome(200, "event", str(seq), load_event(conn, str(seq), mine))

    return idempotency.run(engine_of(request), request, caller, action)


def _tombstone(
    conn: Connection,
    mine: Membership,
    caller: Caller,
    row: Any,
    reason: str,
    audience: list[str],
    store: attachment_store.BlobStore | None = None,
) -> None:
    """The one mutation the log allows, itself on record (§8.5); a second redaction of
    the same event changes nothing."""
    tombstone(
        conn,
        mine.project.id,
        row,
        reason,
        audience,
        mine.principal_id,
        caller.actor(mine.id),
        store,
    )


def tombstone(
    conn: Connection,
    project_id: str,
    row: Any,
    reason: str,
    audience: list[str],
    by: str | None,
    actor: events.Actor,
    store: attachment_store.BlobStore | None = None,
) -> None:
    """`_tombstone` by any actor: moderation redacts as the hub, `by` null (§16.8)."""
    if row.redacted:
        return
    stone = {
        "redacted": True,
        "reason": reason,
        "by": by,
        "at": clock.rfc3339(clock.now()),
    }
    # Only the first of two concurrent redactions writes and is announced; the other
    # answers with the tombstone that stands, as a repeat does.
    won = conn.execute(
        update(t.event)
        .where(t.event.c.seq == row.seq, t.event.c.redacted.is_(False))
        .values(payload=stone, redacted=True)
    ).rowcount
    if won != 1:
        return
    if row.kind == "message":
        attachments.redact_message(conn, row.seq, by, store)
    marker = (row.payload or {}).get("jour_fixe") if row.kind == "message" else None
    if marker:  # a round's statement or post: its copy in the round goes with it (§20.8)
        from maity_hub.jourfixe import exchange

        exchange.redact_copy(
            conn,
            marker,
            {k: v for k, v in stone.items() if k != "redacted"},
            actor,
        )
    events.emit(
        conn,
        project_id,
        "event_redacted",
        audience,
        {"seq": row.seq, "reason": reason},
        actor=actor,
        subject=("event", str(row.seq)),
        # A chat's notice is the chat's, as the message was: no see-all reaches it.
        conversation_id=row.conversation_id,
    )


def _not_a_participant() -> ApiError:
    return ApiError(
        403, "forbidden", "only a human in the chat redacts here", {"reason": "not_a_participant"}
    )


def _redact_in_group(
    conn: Connection,
    mine: Membership,
    caller: Caller,
    row: Any,
    body: RedactIn,
    store: attachment_store.BlobStore | None = None,
) -> idempotency.Outcome:
    """§8.5 in a group chat: any human participant now, no agent; once the chat closed,
    its former human participants, and a human with `members:admin` blind, by `seq`."""
    events.lock_project(conn, mine.project.id)
    # The caller's membership and role, the event, the chat and who is in it, all as of
    # the lock: a demotion or a removal that commits first is never overtaken.
    mine = membership(conn, caller, namespace.full_name(conn, mine.project))
    row = conn.execute(select(t.event).where(t.event.c.seq == row.seq)).one()
    group = group_chats.find(conn, mine.project.id, row.conversation_id)
    closed = group.closed_at is not None
    hidden = events.hidden_redactions(conn, [row], mine.row)
    blind = False
    # Readable through the log, or through the chat's history (`before`, §9.2): someone
    # added later reads the earlier messages there, so may take a secret out of them.
    readable = events.readable_by(row, mine.row, mine.principal_id, hidden) or (
        group_chats.access(conn, group.id, mine) is not None
    )
    if not readable:
        if not (closed and mine.kind == "human" and mine.may("members:admin")):
            raise not_found()
        if row.kind != "message":  # only a message is redacted blind
            raise not_found()
        blind = True
    if row.kind == "event_redacted":
        raise ApiError(
            400, "invalid", "a redaction cannot be redacted", {"reason": "already_redacted"}
        )
    if row.kind != "message":  # a chat's own record (created, updated) holds no text
        raise ApiError(400, "invalid", "only a message is redacted", {"reason": "not_a_message"})
    if not blind:
        if mine.kind != "human":
            raise humans_only("an agent never redacts; it asks a human in the chat")
        if not closed and group_chats.stay(conn, group.id, mine.id) is None:
            raise _not_a_participant()  # an owner reading through its agent, a former one
        former = group_chats.last_stay(conn, group.id, mine.id) is not None
        if closed and not former and not mine.may("members:admin"):
            raise _not_a_participant()
    if "expect" in body.model_fields_set and not (closed and row.kind == "message"):
        raise invalid({"expect": "mismatch"}, "the event is not a closed group chat's message")
    current = group_chats.stays(conn, group.id)
    audience = group_chats.audience(current)
    if closed:
        everyone = group_chats.stays(conn, group.id, current=False)
        audience += [f"member:{s.human_id}" for s in everyone if s.human_id]
        audience.append(f"member:{mine.principal_id}")
    _tombstone(conn, mine, caller, row, body.reason, list(dict.fromkeys(audience)), store)
    if blind:  # never the event: its actor and audience are not the admin's to read
        return idempotency.Outcome(200, "blind_redaction", str(row.seq), _blind(row.seq))
    return idempotency.Outcome(200, "event", str(row.seq), load_event(conn, str(row.seq), mine))


def _blind(seq: int) -> dict[str, Any]:
    return {"seq": seq, "redacted": True}


idempotency.LOADERS["blind_redaction"] = idempotency.plain(lambda _conn, seq: _blind(int(seq)))
