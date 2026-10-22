"""Requests to humans: the inbox, answers, withdrawal, blocked cards (docs/api.md §7)."""

from __future__ import annotations

import base64
import json
from typing import Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection, insert, select, update

from maity_hub import clock, idempotency, inbox
from maity_hub import tables as t
from maity_hub.access import Membership, member_row, membership
from maity_hub.auth.caller import Caller
from maity_hub.deps import AnyCaller, HumanCaller, engine_of
from maity_hub.errors import ApiError, forbidden, invalid, not_found
from maity_hub.events import emit, lock_project
from maity_hub.ids import new_id
from maity_hub.models import Strict, markdown, title
from maity_hub.views import principal_id, ts

router = APIRouter()

PAGE_DEFAULT, PAGE_MAX = 50, 200
SORTS = ("priority", "date", "agent")


class OptionIn(Strict):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    label: str = title()
    detail: str | None = markdown(default=None)


class NeedsInSessionIn(Strict):
    reason: str = markdown(min_length=1)
    member_id: str
    session_id: str | None = None


class RequestCreate(Strict):
    class_: str = Field(alias="class")
    title: str = title()
    summary: str | None = markdown(default=None)
    tried: str | None = markdown(default=None)
    options: list[OptionIn] = Field(default_factory=list, max_length=inbox.MAX_OPTIONS)
    priority: str = "normal"
    to: str | None = None
    task_id: str | None = None
    while_open: str = "wait"
    needs_in_session: NeedsInSessionIn | None = None
    on_behalf_of: str | None = None
    ktw_ref: str | None = Field(default=None, max_length=255)


class AnswerIn(Strict):
    reply_id: str | None = Field(default=None, max_length=64)
    text: str | None = markdown(default=None, min_length=1)
    talk: Literal[True] | None = None


class WithdrawIn(Strict):
    reason: str | None = markdown(default=None)


def klass(row: Any) -> str:
    value: str = row._mapping["class"]
    return value


# --- views -------------------------------------------------------------------------


def _person(conn: Connection, membership_id: int | None, session_id: str | None) -> Any:
    if membership_id is None:
        return None
    row = conn.execute(select(t.membership).where(t.membership.c.id == membership_id)).one()
    if row.agent_id:
        name = conn.execute(
            select(t.agent_profile.c.display_name).where(t.agent_profile.c.id == row.agent_id)
        ).scalar()
    else:
        name = conn.execute(
            select(t.human.c.display_name).where(t.human.c.id == row.human_id)
        ).scalar()
    return {
        "member_id": row.agent_id or row.human_id,
        "display_name": name,
        "role": row.role,
        "session_id": session_id,
    }


def request_view(conn: Connection, row: Any) -> dict[str, Any]:
    """A request as §7 shows it; also the payload of its events."""
    task = None
    if row.task_id is not None:
        card = conn.execute(
            select(t.card.c.id, t.card.c.title, t.card.c.status).where(t.card.c.id == row.task_id)
        ).one()
        task = {"id": card.id, "title": card.title, "status": card.status}
    return {
        "id": row.id,
        "class": klass(row),
        "title": row.title,
        "summary": row.summary,
        "tried": row.tried,
        "options": row.options,
        "replies": inbox.replies(klass(row), row.options),
        "priority": row.priority,
        "to": inbox.addressee_of(row).text(conn),
        "asked_by": _person(conn, row.asked_by, row.asked_session_id),
        "on_behalf_of": _person(conn, row.on_behalf_of, None),
        "task_id": row.task_id,
        "task": task,
        "while_open": row.while_open,
        "needs_in_session": row.needs_in_session,
        "ktw_ref": row.ktw_ref,
        "status": row.status,
        "answer": row.answer,
        "created_at": ts(row.created_at),
        "answered_at": ts(row.answered_at),
    }


def load_request(conn: Connection, request_id: str) -> dict[str, Any]:
    return request_view(conn, _row(conn, request_id))


idempotency.LOADERS["request"] = idempotency.plain(load_request)


def _row(conn: Connection, request_id: str) -> Any:
    return conn.execute(select(t.request).where(t.request.c.id == request_id)).one()


def _project_request(conn: Connection, mine: Membership, request_id: str) -> Any:
    row = conn.execute(
        select(t.request).where(
            t.request.c.id == request_id, t.request.c.project_id == mine.project.id
        )
    ).first()
    if row is None:
        raise not_found()
    return row


# --- creating ----------------------------------------------------------------------


def _member_id(conn: Connection, mine: Membership, principal: str, field: str) -> int:
    try:
        membership_id: int = member_row(conn, mine.project.id, principal).id
    except ApiError:
        raise invalid({field: "not_a_member"}) from None
    return membership_id


def _resolve_to(
    conn: Connection, mine: Membership, body: RequestCreate, asker: int
) -> inbox.Addressee:
    """`to` as written, or its default (§7)."""
    if body.to is None:
        if body.class_ == "contract":
            arbiter = mine.project.contract_arbiter  # contract requests go to the arbiter
            return _parse_to(conn, mine, arbiter)
        row = conn.execute(select(t.membership).where(t.membership.c.id == asker)).one()
        if row.agent_id is None:
            return inbox.Addressee("owner")
        owner_id = conn.execute(
            select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == row.agent_id)
        ).scalar_one()
        try:
            return inbox.Addressee("member", member=member_row(conn, mine.project.id, owner_id).id)
        except ApiError:  # the agent's human is not in this project: the owner then
            return inbox.Addressee("owner")
    return _parse_to(conn, mine, body.to)


def _parse_to(conn: Connection, mine: Membership, to: str) -> inbox.Addressee:
    if to == "owner":
        return inbox.Addressee("owner")
    if to.startswith("role:"):
        role = to.removeprefix("role:")
        if not inbox.valid_role(role):
            raise invalid({"to": "unknown_role"})
        return inbox.Addressee("role", role=role)
    return inbox.Addressee("member", member=_member_id(conn, mine, to, "to"))


def _needs_in_session(
    conn: Connection, mine: Membership, needs: NeedsInSessionIn | None
) -> dict[str, Any] | None:
    if needs is None:
        return None
    member = conn.execute(
        select(t.membership).where(
            t.membership.c.id
            == _member_id(conn, mine, needs.member_id, "needs_in_session.member_id")
        )
    ).one()
    person = _person(conn, member.id, None)
    sessions = select(t.agent_session.c.id, t.agent_session.c.harness).where(
        t.agent_session.c.membership_id == member.id
    )
    if needs.session_id is not None:
        session = conn.execute(sessions.where(t.agent_session.c.id == needs.session_id)).first()
        if session is None:
            raise invalid({"needs_in_session.session_id": "not_the_members"})
    else:
        session = conn.execute(sessions.where(t.agent_session.c.live.is_(True))).first()
    return {
        "reason": needs.reason,
        "member_id": needs.member_id,
        "display_name": person["display_name"],
        "session_id": session.id if session else None,
        "harness": session.harness if session else None,
    }


def _validate(body: RequestCreate, mine: Membership) -> None:
    errors: dict[str, str] = {}
    if body.class_ not in inbox.CLASSES:
        errors["class"] = "unknown"
    if body.priority not in inbox.PRIORITIES:
        errors["priority"] = "unknown"
    elif body.priority == "urgent" and not mine.may("requests:answer"):
        errors["priority"] = "urgent_needs_requests_answer"
    if body.while_open not in inbox.WHILE_OPEN:
        errors["while_open"] = "unknown"
    elif body.class_ == "consent" and body.while_open != "wait":
        errors["while_open"] = "consent_waits"
    if body.class_ in ("decision", "consent") and len(body.options) == 1:
        errors["options"] = "none_or_two_or_more"
    ids = [o.id for o in body.options]
    if len(set(ids)) != len(ids):
        errors["options"] = "duplicate_id"
    if errors:
        raise invalid(errors)


@router.post("/projects/{slug}/requests")
def create_request(
    slug: str, body: RequestCreate, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine.require("requests:ask")
        _validate(body, mine)
        mine = _locked(conn, mine)
        on_behalf = None
        if body.on_behalf_of is not None and body.on_behalf_of != mine.principal_id:
            mine.require("requests:answer")
            on_behalf = _member_id(conn, mine, body.on_behalf_of, "on_behalf_of")
        to = _resolve_to(conn, mine, body, on_behalf or mine.id)
        if on_behalf is not None and _is_addressee(conn, mine, to, on_behalf):
            # They could never answer it (self_answer): the request would be dead on arrival.
            raise invalid({"on_behalf_of": "is_the_addressee"})
        if body.class_ == "consent" and not inbox.consent_target_ok(conn, mine.project.id, to):
            raise invalid(
                {"to": "cannot_answer_consent"}, "a consent goes to a role that may answer it"
            )
        card = None
        if body.task_id is not None:
            card = conn.execute(
                select(t.card).where(
                    t.card.c.id == body.task_id, t.card.c.project_id == mine.project.id
                )
            ).first()
            if card is None:
                raise invalid({"task_id": "unknown_task"})
        now = clock.now()
        request_id = new_id("request")
        conn.execute(
            insert(t.request).values(
                {
                    "id": request_id,
                    "project_id": mine.project.id,
                    "class": body.class_,
                    "title": body.title,
                    "summary": body.summary,
                    "tried": body.tried,
                    "options": [o.model_dump() for o in body.options],
                    "priority": body.priority,
                    "to_kind": to.kind,
                    "to_member": to.member,
                    "to_role": to.role,
                    "asked_by": mine.id,
                    "asked_session_id": caller.session_id,
                    "on_behalf_of": on_behalf,
                    "task_id": body.task_id,
                    "while_open": body.while_open,
                    "needs_in_session": _needs_in_session(conn, mine, body.needs_in_session),
                    "ktw_ref": body.ktw_ref,
                    "status": "open",
                    "changed_by_credential": caller.credential_id,
                    "changed_via": caller.via,
                    "created_at": now,
                }
            )
        )
        holder = card.claim_holder if card is not None else None
        if (
            card is not None
            and body.while_open == "wait"
            and holder is not None  # an unheld card is nobody's to block
            and holder in (mine.id, on_behalf)
            and card.status not in ("blocked", "done", "cancelled")
        ):
            # The asker waits: the card shows it, and remembers where it was (§6.4).
            conn.execute(
                update(t.card)
                .where(t.card.c.id == card.id)
                .values(
                    status="blocked",
                    status_before_block=card.status,
                    blocked_by_request=request_id,
                    updated_at=now,
                )
            )
        view = request_view(conn, _row(conn, request_id))
        emit(
            conn,
            mine.project.id,
            "request_created",
            _addressee_audience(conn, mine, to),
            view,
            actor=caller.actor(mine.id),
            subject=("request", request_id),
        )
        return idempotency.Outcome(201, "request", request_id, view)

    return idempotency.run(engine_of(request), request, caller, action)


def _is_addressee(conn: Connection, mine: Membership, to: inbox.Addressee, member: int) -> bool:
    if to.kind == "member":
        return to.member == member
    if to.kind == "owner":
        owner = inbox.owner_membership(conn, mine.project.id)
        return owner is not None and owner.id == member
    return False


def _locked(conn: Connection, mine: Membership) -> Membership:
    from dataclasses import replace

    return replace(mine, project=lock_project(conn, mine.project.id))


def _addressee_audience(conn: Connection, mine: Membership, to: inbox.Addressee) -> list[str]:
    """`to` resolved to `member:` or `role:` (§8.2); `owner` is the owner's member id."""
    if to.kind == "role":
        return [f"role:{to.role}"]
    if to.kind == "owner":
        owner = inbox.owner_membership(conn, mine.project.id)
        return [f"member:{owner.human_id}"] if owner else ["role:owner"]
    return [f"member:{principal_id(conn, to.member)}"]


def _asker_audience(conn: Connection, row: Any) -> list[str]:
    members = [principal_id(conn, row.asked_by), principal_id(conn, row.on_behalf_of)]
    return list(dict.fromkeys(f"member:{m}" for m in members if m))


# --- reading -------------------------------------------------------------------------


def _filtered(
    conn: Connection,
    mine: Membership,
    *,
    status: str,
    class_: str | None,
    asked_by: str | None,
    to: str,
) -> list[Any]:
    query = select(t.request).where(t.request.c.project_id == mine.project.id)
    if status != "all":
        wanted = [s for s in status.split(",") if s]
        if any(s not in inbox.STATUSES for s in wanted):
            raise invalid({"status": "unknown"})
        query = query.where(t.request.c.status.in_(wanted))
    if class_ is not None:
        query = query.where(t.request.c["class"] == class_)
    if asked_by is not None:
        if asked_by == "me":
            query = query.where(t.request.c.asked_by == mine.id)
        else:
            try:
                query = query.where(
                    t.request.c.asked_by == member_row(conn, mine.project.id, asked_by).id
                )
            except ApiError:
                return []
    rows = conn.execute(query).all()
    if to == "me":
        return [r for r in rows if inbox.addressed_to(conn, r, mine)]
    if to == "all":
        if mine.may("requests:answer"):
            return list(rows)
        return [r for r in rows if inbox.is_asker(r, mine) or inbox.addressed_to(conn, r, mine)]
    target = _parse_to(conn, mine, to)
    return [r for r in rows if inbox.addressee_of(r) == target and inbox.may_read(conn, r, mine)]


def _sorted(views: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    # `_created` is the stored timestamp: the view's second precision would tie.
    if sort == "date":
        return sorted(views, key=lambda v: (v["_created"], v["id"]), reverse=True)
    if sort == "agent":
        return sorted(views, key=lambda v: (_handle(v), v["_created"], v["id"]))
    return sorted(views, key=lambda v: (inbox.PRIORITY_RANK[v["priority"]], v["_created"], v["id"]))


def _handle(view: dict[str, Any]) -> str:
    handle: str = view.get("_asker_handle", "")
    return handle


def _key(view: dict[str, Any], sort: str) -> list[Any]:
    """The position of an entry in `sort`, as a cursor can carry it."""
    created = view["_created"].isoformat()
    if sort == "date":
        return [created, view["id"]]
    if sort == "agent":
        return [_handle(view), created, view["id"]]
    return [inbox.PRIORITY_RANK[view["priority"]], created, view["id"]]


def _page(views: list[dict[str, Any]], sort: str, limit: int, cursor: str | None) -> dict[str, Any]:
    """Keyset paging: the cursor carries the last entry's position, so an entry that
    left the list (answered) shifts nothing behind it."""
    if cursor is not None:
        try:
            raw = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
            after_sort, after_key = raw["s"], raw["k"]
        except (ValueError, KeyError, TypeError):
            raise invalid({"cursor": "invalid"}) from None
        if after_sort != sort:
            raise invalid({"cursor": "other_sort"}, "this cursor belongs to another sort")
        if sort == "date":  # newest first
            views = [v for v in views if _key(v, sort) < after_key]
        else:
            views = [v for v in views if _key(v, sort) > after_key]
    page = views[:limit]
    next_cursor = None
    if len(views) > limit:
        token = json.dumps({"s": sort, "k": _key(page[-1], sort)})
        next_cursor = base64.urlsafe_b64encode(token.encode()).decode().rstrip("=")
    for view in page:
        view.pop("_asker_handle", None)
        view.pop("_created", None)
    return {"items": page, "next_cursor": next_cursor}


def _with_handle(conn: Connection, row: Any, view: dict[str, Any]) -> dict[str, Any]:
    member = conn.execute(select(t.membership).where(t.membership.c.id == row.asked_by)).one()
    if member.agent_id:
        handle = conn.execute(
            select(t.agent_profile.c.handle).where(t.agent_profile.c.id == member.agent_id)
        ).scalar()
    else:
        handle = conn.execute(
            select(t.human.c.handle).where(t.human.c.id == member.human_id)
        ).scalar()
    view["_asker_handle"] = handle or ""
    view["_created"] = row.created_at
    return view


def _check_sort(sort: str) -> None:
    if sort not in SORTS:
        raise invalid({"sort": "unknown"})


@router.get("/projects/{slug}/requests")
def list_requests(
    slug: str,
    request: Request,
    caller: AnyCaller,
    status: str = "open",
    class_: str | None = Query(default=None, alias="class"),
    asked_by: str | None = None,
    to: str = "me",
    sort: str = "priority",
    limit: int = Query(default=PAGE_DEFAULT, ge=1, le=PAGE_MAX),
    cursor: str | None = None,
) -> JSONResponse:
    _check_sort(sort)
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        rows = _filtered(conn, mine, status=status, class_=class_, asked_by=asked_by, to=to)
        views = [_with_handle(conn, r, request_view(conn, r)) for r in rows]
        return JSONResponse(_page(_sorted(views, sort), sort, limit, cursor))


@router.get("/requests")
def list_all_requests(
    request: Request,
    caller: HumanCaller,
    status: str = "open",
    class_: str | None = Query(default=None, alias="class"),
    asked_by: str | None = None,
    to: str = "me",
    sort: str = "priority",
    scope: Literal["all"] | None = None,
    limit: int = Query(default=PAGE_DEFAULT, ge=1, le=PAGE_MAX),
    cursor: str | None = None,
) -> JSONResponse:
    """The cross-project inbox (§7): every membership of the human, `project` inline."""
    _check_sort(sort)
    with engine_of(request).begin() as conn:
        projects = conn.execute(
            select(t.project)
            .join(t.membership, t.membership.c.project_id == t.project.c.id)
            .where(t.membership.c.human_id == caller.human_id, t.membership.c.active.is_(True))
        ).all()
        views: list[dict[str, Any]] = []
        for project in projects:
            mine = membership(conn, caller, project.slug)
            if not mine.may("project:read"):
                continue
            try:
                rows = _filtered(conn, mine, status=status, class_=class_, asked_by=asked_by, to=to)
            except ApiError as error:
                if error.code == "invalid" and "to" in error.details.get("fields", {}):
                    continue  # that member is not in this project
                raise
            inline = {"slug": project.slug, "name": project.name, "state": project.state}
            views += [
                {**_with_handle(conn, r, request_view(conn, r)), "project": inline} for r in rows
            ]
        return JSONResponse(_page(_sorted(views, sort), sort, limit, cursor))


@router.get("/projects/{slug}/requests/{request_id}")
def get_request(slug: str, request_id: str, request: Request, caller: AnyCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        row = _project_request(conn, mine, request_id)
        if not inbox.may_read(conn, row, mine):
            raise forbidden(
                "requests:answer", "only the asker, the addressee or an answerer reads this"
            )
        return JSONResponse(request_view(conn, row))


# --- answering and withdrawing --------------------------------------------------------------


def _unblock(conn: Connection, row: Any) -> None:
    """After `row` was answered or withdrawn: the card stays blocked while any other
    waiting request of its holder on it is open, naming the oldest; when none is
    left, the remembered status comes back (§7)."""
    if row.task_id is None:
        return
    card = conn.execute(select(t.card).where(t.card.c.id == row.task_id)).one()
    if card.status != "blocked":
        return
    holder = card.claim_holder
    still_waiting = conn.execute(
        select(t.request.c.id)
        .where(
            t.request.c.task_id == card.id,
            t.request.c.status == "open",
            t.request.c.while_open == "wait",
            t.request.c.id != row.id,
            (t.request.c.asked_by == holder) | (t.request.c.on_behalf_of == holder),
        )
        .order_by(t.request.c.created_at, t.request.c.id)
    ).first()
    if still_waiting is not None:
        values: dict[str, Any] = {"blocked_by_request": still_waiting.id}
    else:
        values = {
            "status": card.status_before_block or "in_progress",
            "status_before_block": None,
            "blocked_by_request": None,
        }
    conn.execute(
        update(t.card).where(t.card.c.id == card.id).values(**values, updated_at=clock.now())
    )


def _refuse_unless_open(row: Any) -> None:
    if row.status != "open":
        raise ApiError(
            409, "request_not_open", f"the request is {row.status}", {"status": row.status}
        )


@router.post("/projects/{slug}/requests/{request_id}/answer")
def answer(
    slug: str, request_id: str, body: AnswerIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = _locked(conn, membership(conn, caller, slug))
        row = _project_request(conn, mine, request_id)
        _refuse_unless_open(row)
        if not inbox.may_answer(conn, row, mine):
            raise forbidden("requests:answer")
        if inbox.is_asker(row, mine):
            raise ApiError(
                409, "self_answer", "nobody answers a request it asked or that was filed for it"
            )
        given = {k for k in ("reply_id", "text", "talk") if getattr(body, k) is not None}
        if not given or ("talk" in given and len(given) > 1):
            raise invalid({"answer": "reply_id_or_text_or_talk"})
        replies = {r["id"] for r in inbox.replies(klass(row), row.options)}
        if body.reply_id is not None and body.reply_id not in replies:
            raise invalid({"reply_id": "not_a_reply"})
        conversation_id = None
        if body.talk:
            conversation_id = _talk_allowed(conn, row, caller)
        addressee = inbox.addressee_of(row)
        in_own_right = inbox.answered_in_own_right(conn, row, mine)
        on_behalf = None
        if not in_own_right and addressee.kind != "role":
            on_behalf = (
                inbox.owner_membership(conn, mine.project.id).human_id
                if addressee.kind == "owner"
                else principal_id(conn, addressee.member)
            )
        now = clock.now()
        stored = {
            "reply_id": body.reply_id,
            "text": body.text,
            "talk": bool(body.talk),
            "by": mine.principal_id,
            "on_behalf_of": on_behalf,
            "at": clock.rfc3339(now),
            "conversation_id": conversation_id,
        }
        done = conn.execute(
            update(t.request)
            .where(t.request.c.id == row.id, t.request.c.status == "open")
            .values(
                status="answered",
                answer=stored,
                answered_by=mine.id,
                answered_at=now,
                changed_by_credential=caller.credential_id,
                changed_via=caller.via,
            )
        ).rowcount
        if done != 1:
            _refuse_unless_open(_row(conn, row.id))
        _unblock(conn, row)
        view = request_view(conn, _row(conn, row.id))
        emit(
            conn,
            mine.project.id,
            "request_answered",
            _asker_audience(conn, row),
            view,
            actor=caller.actor(mine.id),
            subject=("request", row.id),
        )
        return idempotency.Outcome(200, "request", row.id, view)

    return idempotency.run(engine_of(request), request, caller, action)


def _talk_allowed(conn: Connection, row: Any, caller: Caller) -> str:
    """`talk` only from the human who owns the asking agent; the conversation is that agent."""
    asker = conn.execute(select(t.membership).where(t.membership.c.id == row.asked_by)).one()
    if caller.kind == "human" and asker.agent_id is not None:
        owner = conn.execute(
            select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == asker.agent_id)
        ).scalar()
        if owner == caller.human_id:
            agent_id: str = asker.agent_id
            return agent_id
    raise invalid({"talk": "only_the_owner_of_the_agent"}, "only the agent's own human can talk")


@router.post("/projects/{slug}/requests/{request_id}/withdraw")
def withdraw(
    slug: str, request_id: str, body: WithdrawIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = _locked(conn, membership(conn, caller, slug))
        row = _project_request(conn, mine, request_id)
        if not (inbox.is_asker(row, mine) or mine.may("requests:answer")):
            raise forbidden("requests:answer")
        _refuse_unless_open(row)
        now = clock.now()
        conn.execute(
            update(t.request)
            .where(t.request.c.id == row.id)
            .values(
                status="withdrawn",
                withdrawn_at=now,
                withdraw_reason=body.reason,
                changed_by_credential=caller.credential_id,
                changed_via=caller.via,
            )
        )
        _unblock(conn, row)
        view = request_view(conn, _row(conn, row.id))
        emit(
            conn,
            mine.project.id,
            "request_withdrawn",
            _asker_audience(conn, row),
            {**view, "reason": body.reason},
            actor=caller.actor(mine.id),
            subject=("request", row.id),
        )
        return idempotency.Outcome(200, "request", row.id, view)

    return idempotency.run(engine_of(request), request, caller, action)
