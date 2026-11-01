"""Requests to humans: the inbox, answers, withdrawal, blocked cards (docs/api.md §7)."""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import Callable
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, Literal, cast

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection, and_, insert, or_, select, update

from maity_hub import (
    avatars,
    bridges,
    clock,
    cover,
    cross_owner,
    events,
    foreign_agent,
    idempotency,
    inbox,
    instances,
    mentions,
    namespace,
    orgs,
    placements,
    proposals,
    seats,
    ticker,
)
from maity_hub import tables as t
from maity_hub.access import Membership, member_row, membership
from maity_hub.auth import second_factor
from maity_hub.auth.caller import Caller
from maity_hub.deps import AnyCaller, HumanCaller, engine_of, reader_of, settings_of
from maity_hub.errors import ApiError, forbidden, humans_only, invalid, not_found
from maity_hub.events import Actor, emit, lock_project
from maity_hub.ids import new_id
from maity_hub.jourfixe import triage as jour_fixe_triage
from maity_hub.models import Strict, Written, markdown, title
from maity_hub.namespace import ProjectRoute
from maity_hub.notifications import records
from maity_hub.replies import replies
from maity_hub.scopes import tokens_of
from maity_hub.views import deleted, deleted_person, principal_id, shape_deleted, ts

log = logging.getLogger(__name__)
router = APIRouter(route_class=ProjectRoute)

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


class RequestCreate(Written):
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
    humans_only: bool = False


class ForwardIn(Strict):
    to: str
    reason: str | None = markdown(default=None)


class AnswerIn(Written):
    reply_id: str | None = Field(default=None, max_length=64)
    text: str | None = markdown(default=None, min_length=1)
    talk: Literal[True] | None = None
    # A human's edit of a preference proposal, with the version it was made on (§19.4).
    markdown: str | None = Field(default=None, max_length=16384)
    base_version: int | None = Field(default=None, ge=0)


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
        human = conn.execute(
            select(t.human.c.display_name, t.human.c.deleted_at).where(t.human.c.id == row.human_id)
        ).one()
        if deleted(human):  # §2.9: the field's shape, without the person
            return {
                "member_id": row.human_id,
                **deleted_person(),
                "trust": row.trust,
                "role": row.role,
                "session_id": session_id,
            }
        name = human.display_name
    member_id = row.agent_id or row.human_id
    return {
        "member_id": member_id,
        "display_name": name,
        "avatar_url": avatars.urls(conn, [member_id])[member_id],
        "trust": row.trust,
        "role": row.role,
        "session_id": session_id,
    }


def _inviter(conn: Connection, human_id: str) -> dict[str, Any]:
    """A human who asks without a membership: the one who invites to an organisation. The
    shape of a member's, without a trust or a role: there is no project."""
    human = conn.execute(
        select(t.human.c.display_name, t.human.c.deleted_at).where(t.human.c.id == human_id)
    ).one()
    shown = (
        deleted_person()
        if deleted(human)
        else {
            "display_name": human.display_name,
            "avatar_url": avatars.urls(conn, [human_id])[human_id],
        }
    )
    return {
        "member_id": human_id,
        **shown,
        "trust": None,
        "role": None,
        "session_id": None,
        "instance": None,
    }


def _asker(conn: Connection, row: Any) -> Any:
    """`asked_by` with the agent instance that asked (§7, §6.17): the instance of the
    credential whose session filed it; `null` for a human, and for a request the hub
    files on an agent's behalf, which has no session. The owner's digest (§5.3) has no
    asker at all: `null`."""
    if row.asked_by is None and row.asked_by_human is not None:
        return _inviter(conn, row.asked_by_human)  # an organisation's invitation (§6.26)
    if row.asked_by is None:
        return None
    person = _person(conn, row.asked_by, row.asked_session_id)
    return {**person, "instance": _asking_instance(conn, row)}


def _with_avatar(conn: Connection, needs: dict[str, Any] | None) -> dict[str, Any] | None:
    """The stored `needs_in_session` with the member's current `avatar_url` (§6.10)."""
    if needs is None:
        return None
    member_id = needs["member_id"]
    [shaped] = shape_deleted(conn, [needs])  # a deleted account as one (§2.9)
    if shaped.get("deleted"):
        return dict(shaped)
    return {**needs, "avatar_url": avatars.urls(conn, [member_id])[member_id]}


def _task(conn: Connection, task_id: str | None) -> dict[str, Any] | None:
    if task_id is None:
        return None
    card = conn.execute(
        select(t.card.c.id, t.card.c.title, t.card.c.status).where(t.card.c.id == task_id)
    ).one()
    return {"id": card.id, "title": card.title, "status": card.status}


def request_view(conn: Connection, row: Any, *, with_proposal: bool = False) -> dict[str, Any]:
    """A request as §7 shows it; also the payload of its events (a personal request's
    events excepted: `_payload`). `with_proposal` adds the fields a proposal's kind shows
    (`proposals.view`): only `GET …/requests/{id}` asks for them, never an event, a list
    or a resume packet (§19.1, §19.3)."""
    task = _task(conn, row.task_id)
    if row.personal and row.status != "open" and row.task_snapshot is not None:
        task = row.task_snapshot  # the card as it was when the request closed (§7)
    view = {
        "id": row.id,
        "class": klass(row),
        "title": row.title,
        "summary": row.summary,
        "tried": row.tried,
        "mentions": row.mentions or [],
        "options": row.options,
        "replies": replies(klass(row), row.options),
        "priority": row.priority,
        "to": inbox.addressee_of(row).text(conn),
        "asked_by": _asker(conn, row),
        "on_behalf_of": _person(conn, row.on_behalf_of, None),
        "task_id": row.task_id,
        "task": task,
        "while_open": row.while_open,
        "needs_in_session": _with_avatar(conn, row.needs_in_session),
        "ktw_ref": row.ktw_ref,
        "jour_fixe": row.jour_fixe,
        "status": row.status,
        "answer": row.answer,
        "created_at": ts(row.created_at),
        "answered_at": ts(row.answered_at),
        "placement": placements.request_summary(conn, row.placement_id),
        "personal": bool(row.personal),
        "filed_by": row.filed_by,
        "holder": _holder(conn, row),
        "forwarding": row.forwarding or [],
        "humans_only": inbox.humans_only(row),
        "takeover_id": row.takeover_id,  # set by the hub only (§6.19)
        "cover": cover.view(row.cover),  # a substitute answers it as the addressee (§6.12)
    }
    shown = proposals.view(conn, row) if with_proposal else {}
    if shown.keys() & view.keys():  # a kind adds its own fields, it never replaces one
        raise ValueError(f"a proposal view repeats {sorted(shown.keys() & view.keys())}")
    # A deleted account in the stored mentions or answer is shown as one (§2.9).
    [shaped] = shape_deleted(conn, [view | shown])
    return dict(shaped)


def _holder(conn: Connection, row: Any) -> str:
    """Who holds the request now (§7): `to` until its first forward, then a member id, or
    `trust:admin` while it is open to the admins and nobody has claimed it."""
    if row.holder_member is not None:
        found = principal_id(conn, row.holder_member)
        assert found is not None
        return found
    if row.holder_pool:
        return "trust:admin"
    return inbox.addressee_of(row).text(conn)


def _is_agent(conn: Connection, membership_id: int | None) -> bool:
    agent = conn.execute(
        select(t.membership.c.agent_id).where(t.membership.c.id == membership_id)
    ).scalar()
    return agent is not None


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
    if inbox.owners_alone(conn, [row]) and not inbox.may_read(conn, row, mine):
        raise not_found()  # the project route never tells anyone else it exists (§20.7)
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
            arbiter = seats.routed_arbiter(conn, mine.project)  # contract requests go to it
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
    if to.startswith(("profile_owner:", "human:")):  # the hub's own personal addressing
        raise invalid({"to": "hub_only"}, "personal requests are filed by the hub")
    if to == "owner":
        return inbox.Addressee("owner")
    if to.startswith(("role:", "trust:")):
        if not inbox.valid_token(to, mine.project):
            raise invalid({"to": "unknown_role"})
        return inbox.Addressee("role", role=to)
    principal, instance = instances.split_address(to)
    addressee = _member_id(conn, mine, principal, "to")
    trust, isolated_since = conn.execute(
        select(t.membership.c.trust, t.membership.c.isolated_since).where(
            t.membership.c.id == addressee
        )
    ).one()
    if trust == "guest":  # a guest answers nothing, so nothing is asked of it (§2.3)
        raise invalid({"to": "guest"}, "a guest is never asked")
    if isolated_since is not None:  # nothing reaches an isolated agent (§6.2)
        raise invalid({"to": "isolated"}, "the agent is isolated")
    if instance is not None:
        instances.addressed(conn, addressee, principal, instance, "to")  # `not_an_instance`
    return inbox.Addressee("member", member=addressee, instance=instance)


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


@router.post("/projects/{owner}/{slug}/requests")
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
        if body.humans_only and to.kind == "member" and _is_agent(conn, to.member):
            raise invalid({"to": "humans_only"}, "only a human holds a humans_only request")
        card = None
        if body.task_id is not None:
            card = conn.execute(
                select(t.card).where(
                    t.card.c.id == body.task_id, t.card.c.project_id == mine.project.id
                )
            ).first()
            if card is None:
                raise invalid({"task_id": "unknown_task"})
        # Links only: a mention in a request pings nobody (§8.6).
        found = mentions.resolve(conn, mine.project.id, body.summary, "summary") + (
            mentions.resolve(conn, mine.project.id, body.tried, "tried")
        )
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
                    "mentions": found,
                    "options": [o.model_dump() for o in body.options],
                    "priority": body.priority,
                    "to_kind": to.kind,
                    "to_member": to.member,
                    "to_instance": to.instance,
                    "to_role": to.role,
                    "asked_by": mine.id,
                    "asked_session_id": caller.session_id,
                    "on_behalf_of": on_behalf,
                    "task_id": body.task_id,
                    "while_open": body.while_open,
                    "needs_in_session": _needs_in_session(conn, mine, body.needs_in_session),
                    "ktw_ref": body.ktw_ref,
                    "humans_only": body.humans_only,
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
    return replace(mine, project=lock_project(conn, mine.project.id))


def _locked_member(conn: Connection, caller: Caller, slug: str) -> Membership:
    """The caller's membership read again after the project lock: a demotion or a removal
    that commits first is never overtaken (as #271 and #283)."""
    lock_project(conn, membership(conn, caller, slug).project.id)
    return membership(conn, caller, slug)


def _addressee_audience(conn: Connection, mine: Membership, to: inbox.Addressee) -> list[str]:
    """`to` resolved to `member:` or `role:` (§8.2); `owner` is the owner's member id."""
    return _audience_of(conn, mine.project.id, to)


def _audience_of(conn: Connection, project_id: str, to: inbox.Addressee) -> list[str]:
    if to.kind == "role":
        return [str(to.role)]
    if to.kind == "owner":
        owner = inbox.owner_membership(conn, project_id)
        return [f"member:{owner.human_id}"] if owner else ["trust:owner"]
    principal = principal_id(conn, to.member)
    if to.instance is None or to.member is None:
        return [f"member:{principal}"]
    # One instance: its token wakes only it, the team reads it (§7, §8.2).
    return [instances.addressed(conn, to.member, str(principal), to.instance, "to")]


def _asking_instance(conn: Connection, row: Any) -> str | None:
    """The instance of the credential whose session filed the request; `None` for a
    human, for a request the hub filed, which has no session (§7), and for one a bridge
    filed for the asker, whose session is the bridge's own membership's (§2.3)."""
    if row.asked_session_id is None:
        return None
    instance: str | None = conn.execute(
        select(t.credential.c.instance)
        .join(t.agent_session, t.agent_session.c.credential_id == t.credential.c.id)
        .where(
            t.agent_session.c.id == row.asked_session_id,
            t.credential.c.membership_id == row.asked_by,
        )
    ).scalar()
    return instance


def _asker_audience(conn: Connection, row: Any) -> list[str]:
    # A notice the hub files has no asker who reads it: never the agent it names (§7).
    # The asking instance is woken alone, its team reads along (§8.2); a human asker, and
    # an asker with no session, are `member:`.
    audience: list[str] = []
    if row.filed_by != "hub":
        asker = principal_id(conn, row.asked_by)
        if asker:
            audience.append(instances.token(asker, _asking_instance(conn, row)))
        behalf = principal_id(conn, row.on_behalf_of)
        if behalf:
            audience.append(f"member:{behalf}")
    audience = list(dict.fromkeys(audience))
    if row.personal and _member_of(conn, row.project_id, row.to_human) is not None:
        audience.append(f"member:{row.to_human}")  # the owner, when a member (§7)
    return audience


def _member_of(conn: Connection, project_id: str | None, human_id: str | None) -> Any:
    if human_id is None or project_id is None:
        return None
    return conn.execute(
        select(t.membership).where(
            t.membership.c.project_id == project_id,
            t.membership.c.human_id == human_id,
            t.membership.c.active.is_(True),
        )
    ).first()


def _payload(row: Any, view: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """An event's payload: the request as `GET` shows it, or for a personal request its
    id and status only — owners and admins read every event and must not learn what it
    says (§7, §8.2)."""
    if row.personal:
        return {"id": view["id"], "personal": True, "status": view["status"]}
    return {**view, **extra}


def _snapshot(conn: Connection, row: Any) -> dict[str, Any]:
    """What a personal request keeps when it closes: its card as it was (§7)."""
    return {"task_snapshot": _task(conn, row.task_id)} if row.personal else {}


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
    query = select(t.request).where(
        t.request.c.project_id == mine.project.id, t.request.c.personal.is_(False)
    )
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
    if mine.role_base == "proxy":
        # The project's consent to a bridge across owners is a human's own answer: a proxy
        # neither lists nor relays it (§2.3, §7).
        rows = [r for r in rows if (r.proposal or {}).get("kind") != bridges.PROJECT_KIND]
    if to == "me":
        return [r for r in rows if inbox.addressed_to(conn, r, mine)]
    if to == "all":
        if mine.may("requests:answer"):
            alone = inbox.owners_alone(conn, rows)
            return [r for r in rows if r.id not in alone or inbox.may_read(conn, r, mine)]
        return [r for r in rows if inbox.is_asker(r, mine) or inbox.addressed_to(conn, r, mine)]
    target = _parse_to(conn, mine, to)
    # A member id alone also names the instance addresses of its team: the team reads them.
    whole_team = target.kind == "member" and target.instance is None
    return [
        r
        for r in rows
        if (replace(inbox.addressee_of(r), instance=None) if whole_team else inbox.addressee_of(r))
        == target
        and inbox.may_read(conn, r, mine)
    ]


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


def _page(
    views: list[dict[str, Any]],
    sort: str,
    limit: int,
    cursor: str | None,
    render: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Keyset paging: the cursor carries the last entry's position, so an entry that
    left the list (answered) shifts nothing behind it. With `render`, the entries are
    light (`_entries`) and only the page is turned into full views: a listing costs the
    page, not every request it filters."""
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
    if render is not None:
        page = [render(entry) for entry in page]
    for view in page:
        view.pop("_asker_handle", None)
        view.pop("_created", None)
    return {"items": page, "next_cursor": next_cursor}


def _asker_handles(conn: Connection, rows: list[Any]) -> dict[str, str]:
    """The asker's handle for every row (by the request's id), in a few queries: what the
    `agent` sort orders by. An organisation's invitation has no asking membership, its asker
    is the human who invites (`asked_by_human`)."""
    ids = {r.asked_by for r in rows if r.asked_by is not None}
    humans = {r.asked_by_human for r in rows if r.asked_by is None and r.asked_by_human}
    if not ids and not humans:
        return {}
    found: dict[int, str] = {}
    for member_id, handle in conn.execute(
        select(t.membership.c.id, t.agent_profile.c.handle)
        .join(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
        .where(t.membership.c.id.in_(ids))
    ):
        found[member_id] = handle or ""
    for member_id, handle in conn.execute(
        select(t.membership.c.id, t.human.c.handle)
        .join(t.human, t.human.c.id == t.membership.c.human_id)
        .where(t.membership.c.id.in_(ids))
    ):
        found[member_id] = handle or ""
    inviters: dict[str, str] = {}
    if humans:
        for human_id, handle in conn.execute(
            select(t.human.c.id, t.human.c.handle).where(t.human.c.id.in_(humans))
        ):
            inviters[human_id] = handle or ""
    return {
        r.id: (
            found.get(r.asked_by, "")
            if r.asked_by is not None
            else inviters.get(r.asked_by_human, "")
        )
        for r in rows
    }


def _entries(
    conn: Connection,
    rows: list[Any],
    extra: Callable[[Any], dict[str, Any]] = lambda _row: {},
) -> list[dict[str, Any]]:
    """What sorting and paging need of each row, without its view (`_page`'s `render`);
    `extra` adds the row's inline fields (`project`)."""
    handles = _asker_handles(conn, rows)
    return [
        {
            "id": r.id,
            "priority": r.priority,
            "_created": r.created_at,
            "_asker_handle": handles.get(r.id, ""),
            "_row": r,
            **extra(r),
        }
        for r in rows
    ]


def _in_project(inline: dict[str, Any]) -> Callable[[Any], dict[str, Any]]:
    """`_entries`' extra for rows of one project: the same inline `project` on each."""
    return lambda _row: {"project": inline}


def _render(conn: Connection) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """An entry of `_entries` as its full view, the inline `project` kept."""

    def render(entry: dict[str, Any]) -> dict[str, Any]:
        view = request_view(conn, entry.pop("_row"))
        if "project" in entry:
            view["project"] = entry["project"]
        if "org" in entry:  # a personal request's organisation, or null (§7, §6.26)
            view["org"] = entry["org"]
        view["_asker_handle"] = entry["_asker_handle"]
        view["_created"] = entry["_created"]
        return view

    return render


def _check_status(status: str) -> None:
    """Checked before any project is read: a caller without memberships gets the same
    answer for a bad filter as a member does."""
    if status != "all" and any(s not in inbox.STATUSES for s in status.split(",") if s):
        raise invalid({"status": "unknown"})


def _check_sort(sort: str) -> None:
    if sort not in SORTS:
        raise invalid({"sort": "unknown"})


@router.get("/projects/{owner}/{slug}/requests")
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
        entries = _sorted(_entries(conn, rows), sort)
        return JSONResponse(_page(entries, sort, limit, cursor, _render(conn)))


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
    _check_status(status)
    with engine_of(request).begin() as conn:
        projects = conn.execute(
            select(t.project)
            .join(t.membership, t.membership.c.project_id == t.project.c.id)
            .where(t.membership.c.human_id == caller.human_id, t.membership.c.active.is_(True))
        ).all()
        views: list[dict[str, Any]] = []
        for project in projects:
            mine = membership(conn, caller, namespace.full_name(conn, project))
            if not mine.may("project:read"):
                continue
            try:
                rows = _filtered(conn, mine, status=status, class_=class_, asked_by=asked_by, to=to)
            except ApiError as error:
                if error.code == "invalid" and "to" in error.details.get("fields", {}):
                    continue  # that member is not in this project
                raise
            inline = {
                "slug": project.slug,
                "full_name": namespace.full_name(conn, project),
                "name": project.name,
                "state": project.state,
            }
            views += _entries(conn, rows, _in_project(inline))
        # Personal requests, member of their project or not (§7). The project listings
        # above never contain them.
        views += _personal_inbox(
            conn, caller, status=status, class_=class_, asked_by=asked_by, to=to
        )
        return JSONResponse(_page(_sorted(views, sort), sort, limit, cursor, _render(conn)))


@router.get("/projects/{owner}/{slug}/requests/{request_id}")
def get_request(slug: str, request_id: str, request: Request, caller: AnyCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        row = _project_request(conn, mine, request_id)
        if row.personal and (row.filed_by == "hub" or not inbox.is_asker(row, mine)):
            raise not_found()  # the project route never tells anyone else it exists (§7)
        if not inbox.may_read(conn, row, mine):
            raise forbidden(
                "requests:answer", "only the asker, the addressee or an answerer reads this"
            )
        return JSONResponse(request_view(conn, row, with_proposal=True))


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
            t.request.c.personal.is_(False),  # never a card's blocker: its id stays hidden (§7)
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
    if values.get("status") == "review":
        from maity_hub import merged

        merged.returned_to_review(conn, card.id)  # a merge remembered is told now (§6.6)


def _self_answer() -> ApiError:
    return ApiError(
        409, "self_answer", "nobody answers a request it asked or that was filed for it"
    )


def _check_answer(row: Any, body: AnswerIn) -> None:
    """One of reply_id, text, talk; text may go with reply_id or with talk, and talk is never
    with reply_id (§7); a reply it offers."""
    given = {k for k in ("reply_id", "text", "talk") if getattr(body, k) is not None}
    if not given or {"talk", "reply_id"} <= given:
        raise invalid({"answer": "reply_id_or_text_or_talk"})
    reply_ids = {r["id"] for r in replies(klass(row), row.options)}
    if body.reply_id is not None and body.reply_id not in reply_ids:
        raise invalid({"reply_id": "not_a_reply"})
    rule = proposals.answerer(row)
    if rule is not None and rule.reply_required and body.reply_id is None:
        raise invalid({"reply_id": "required"}, "this request is answered with one of its replies")
    edits = body.markdown is not None or body.base_version is not None
    if edits and (row.proposal or {}).get("kind") != "preferences":
        raise invalid({"markdown": "not_a_preference_proposal"})
    if edits and (body.reply_id != "go" or body.markdown is None or body.base_version is None):
        raise invalid({"markdown": "go_with_markdown_and_base_version"})


def _refuse_by_kind(conn: Connection, row: Any, who: Any) -> None:
    """The proposal kind's own rule on who answers (`proposals.refusal`), for the one who
    answers, claims or is forwarded the request: `forbidden` with its reason."""
    reason = proposals.refusal(conn, row, who)
    if reason is not None:
        raise ApiError(403, "forbidden", "this request is not theirs to answer", {"reason": reason})


def _refuse_unless_open(row: Any) -> None:
    if row.status != "open":
        raise ApiError(
            409, "request_not_open", f"the request is {row.status}", {"status": row.status}
        )


def _step_up_for_a_transfer(
    conn: Connection, request: Request, caller: Caller, row: Any, body: Any
) -> None:
    """The `go` that moves a project is as sensitive as the transfer that asked for it
    (§2.8.4); a `no` changes nothing and is not asked."""
    from maity_hub import project_names

    if body.reply_id == "go" and (row.proposal or {}).get("kind") == project_names.KIND:
        second_factor.require_step_up(conn, settings_of(request), caller)


@router.post("/projects/{owner}/{slug}/requests/{request_id}/answer")
def answer(
    slug: str, request_id: str, body: AnswerIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        found = membership(conn, caller, slug)
        if found.project.owner_org_id is not None:  # a transfer out of it moves the owners'
            orgs.lock(conn, found.project.owner_org_id)  # seats: the organisation's row first
        mine = _locked(conn, found)
        if mine.project.owner_org_id != found.project.owner_org_id:
            raise orgs.project_moved()  # moved meanwhile: its new owner is unlocked
        row = _project_request(conn, mine, request_id)
        if row.filed_by == "hub":
            raise not_found()  # no asker reads a hub notice through the project (§7)
        if row.personal:  # answered by its human through POST /requests/{id}/answer (§7)
            # TODO(§6.17): the asking instance, once instances exist; same-team instances
            # share the member id until then.
            if inbox.is_asker(row, mine):
                raise _self_answer()
            raise not_found()
        _refuse_unless_open(row)
        proposals.require_known(row)
        refusal = inbox.needs_a_human(row, mine)
        if refusal is not None:
            raise humans_only(refusal)
        if inbox.forwarded(row) and row.holder_member != mine.id:
            raise _not_holder()  # once forwarded, only its holder answers (§7)
        _refuse_by_kind(conn, row, mine)
        if not inbox.may_answer(conn, row, mine):
            raise forbidden(inbox.answer_scope(row))
        if inbox.is_asker(row, mine):
            raise _self_answer()
        _check_answer(row, body)
        _step_up_for_a_transfer(conn, request, caller, row, body)
        conversation_id = None
        if body.talk:
            conversation_id = _talk_allowed(conn, row, caller)
        addressee = inbox.addressee_of(row)
        in_own_right = inbox.answered_in_own_right(conn, row, mine)
        on_behalf = None
        if inbox.forwarded(row):  # answered for the one it was addressed to (§7)
            on_behalf = addressee.text(conn)
        elif not in_own_right and inbox.covers(row, mine):
            on_behalf = row.cover["for"]  # the covered addressee (§6.12)
        elif not in_own_right and addressee.kind != "role":
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
            "mentions": mentions.resolve(conn, mine.project.id, body.text, "text"),
            # Given by a bridge for the answering agent (§2.3): only then.
            **({"via": caller.bridge.view()} if caller.bridge else {}),
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
        # A consent for a placement: `go` approves, any other answer refuses (§15.6).
        outcome = "go" if body.reply_id == "go" else "no"
        placements.settle(conn, row, outcome, caller.actor(mine.id), mine.principal_id)
        proposals.settle(
            conn, row, outcome, mine.principal_id, caller.actor(mine.id), reply_id=body.reply_id
        )
        # An `adopt` of a jour fixe proposal opens its card (§20.6).
        jour_fixe_triage.settle(
            conn, row, body.reply_id, mine, caller.actor(mine.id), reader_of(request)
        )
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
        ticker.on_request_answered(conn, mine.project, _row(conn, row.id), caller.actor(mine.id))
        return idempotency.Outcome(200, "request", row.id, view)

    try:
        return idempotency.run(engine_of(request), request, caller, action)
    except proposals.Stale as stale:
        # The go no longer applies: the request is withdrawn, and nothing else changes.
        with events.transaction(engine_of(request)) as conn:
            close_request(conn, stale.request_id, "withdrawn", None, reason=stale.reason)
        raise stale.error from None


# --- forwarding and claiming (§7) --------------------------------------------------------


def _not_holder() -> ApiError:
    return ApiError(
        403, "forbidden", "only the request's holder does this", {"reason": "not_request_holder"}
    )


def _holds(conn: Connection, row: Any, mine: Membership) -> bool:
    """The caller holds the request: the member it was forwarded to, or before the first
    forward any member `to` resolves to. While the admins hold it as a pool, nobody does
    until one claims it."""
    if row.holder_pool:
        return False
    if row.holder_member is not None:
        return bool(row.holder_member == mine.id)
    return inbox.originally_addressed(conn, row, mine)


def _holder_audience(conn: Connection, mine: Membership, row: Any) -> list[str]:
    """Who holds it, as an audience: the member, `to` before the first forward, or the
    pool's human admins only, so that opening it to the admins wakes no agent (§7)."""
    if row.holder_member is not None:
        return [f"member:{principal_id(conn, row.holder_member)}"]
    if row.holder_pool:
        humans = conn.execute(
            select(t.membership.c.human_id).where(
                t.membership.c.project_id == row.project_id,
                t.membership.c.trust == "admin",
                t.membership.c.role != "proxy",  # the pool is the admin team's (§2.3)
                t.membership.c.human_id.is_not(None),
                t.membership.c.active.is_(True),
            )
        ).scalars()
        return [f"member:{h}" for h in humans]
    return _addressee_audience(conn, mine, inbox.addressee_of(row))


def _forwarding_audience(conn: Connection, mine: Membership, before: Any, after: Any) -> list[str]:
    """The asker, the old and the new holder, and the original addressee (§7)."""
    return list(
        dict.fromkeys(
            [
                *_asker_audience(conn, before),
                *_holder_audience(conn, mine, before),
                *_holder_audience(conn, mine, after),
                *_addressee_audience(conn, mine, inbox.addressee_of(before)),
            ]
        )
    )


def _step(
    conn: Connection, before: Any, action: str, to: str, by: str, reason: str | None
) -> list[dict[str, Any]]:
    return [
        *(before.forwarding or []),
        {
            "action": action,
            "from": _holder(conn, before),
            "to": to,
            "by": by,
            "reason": reason,
            "at": clock.rfc3339(clock.now()),
        },
    ]


def _originally_for(row: Any, member: Any) -> bool:
    """Whether `to` as filed names this membership row: its member id, `owner` for an
    owner, a role it holds."""
    if row.to_kind == "member":
        return bool(row.to_member == member.id)
    if row.to_kind == "owner":
        return bool(member.trust == "owner")
    return bool(
        row.to_kind == "role"
        and row.to_role in tokens_of(member.trust, member.role, member.role_base)
    )


def _pool_open() -> Any:
    """The request is open to the admins: opened by a forward, or filed `to: trust:admin`
    and not yet forwarded or claimed (§7)."""
    return or_(
        t.request.c.holder_pool.is_(True),
        and_(
            t.request.c.holder_member.is_(None),
            t.request.c.holder_pool.is_(None),
            t.request.c.to_kind == "role",
            t.request.c.to_role == "trust:admin",
        ),
    )


def _open_decision(conn: Connection, mine: Membership, request_id: str) -> Any:
    """The request as forward and claim see it: readable by the caller, never a personal
    one (`not_found`), a `decision`, and open."""
    row = _project_request(conn, mine, request_id)
    if row.personal or not inbox.may_read(conn, row, mine):
        raise not_found()
    if klass(row) != "decision":
        raise invalid({"class": "not_forwardable"}, "only a decision request is forwarded")
    _refuse_unless_open(row)
    return row


@router.post("/projects/{owner}/{slug}/requests/{request_id}/forward")
def forward(
    slug: str, request_id: str, body: ForwardIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = _locked_member(conn, caller, slug)
        row = _open_decision(conn, mine, request_id)
        if not _holds(conn, row, mine):
            raise _not_holder()
        values: dict[str, Any]
        alone = bool(inbox.owners_alone(conn, [row]))
        if body.to == "trust:admin":
            if alone:  # the whole pool would read an owner's round (§20.7)
                raise invalid({"to": "owners_round"}, "this goes to one human, not to the admins")
            target_id = None
            values = {"holder_member": None, "holder_pool": True}
        else:
            try:
                target = member_row(conn, mine.project.id, body.to)
            except ApiError:
                raise invalid({"to": "not_a_member"}) from None
            if target.isolated_since is not None:
                raise invalid({"to": "isolated"}, "the agent is isolated")
            if target.id in (mine.id, row.holder_member) or target.id in (
                row.asked_by,
                row.on_behalf_of,
            ):
                raise invalid({"to": "self"}, "nobody holds a request it asked or holds already")
            original = _originally_for(row, target)
            if (
                "trust:admin" not in tokens_of(target.trust, target.role, target.role_base)
                and not original
            ):
                raise invalid({"to": "not_admin"}, "a member holding admin, or the addressee")
            if target.agent_id is not None and inbox.humans_only(row):
                raise humans_only("a humans_only request goes to a human or to the admins")
            if target.agent_id is not None and alone:
                raise invalid({"to": "owners_round"}, "this goes to one human, the owner's choice")
            # Nor to someone the proposal's kind would not let answer it (§6.19).
            _refuse_by_kind(conn, row, target)
            target_id = target.id
            values = {"holder_member": target.id, "holder_pool": None}
        action_name = "opened" if target_id is None else "forwarded"
        steps = _step(conn, row, action_name, body.to, mine.principal_id, body.reason)
        conn.execute(
            update(t.request)
            .where(t.request.c.id == row.id)
            .values(
                **values,
                forwarding=steps,
                changed_by_credential=caller.credential_id,
                changed_via=caller.via,
            )
        )
        after = _row(conn, row.id)
        view = request_view(conn, after)
        emit(
            conn,
            mine.project.id,
            "request_forwarded",
            _forwarding_audience(conn, mine, row, after),
            {**view, "step": steps[-1]},
            actor=caller.actor(mine.id),
            subject=("request", row.id),
        )
        return idempotency.Outcome(200, "request", row.id, view)

    return idempotency.run(engine_of(request), request, caller, action)


@router.post("/projects/{owner}/{slug}/requests/{request_id}/claim")
def claim(slug: str, request_id: str, request: Request, caller: AnyCaller) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = _locked_member(conn, caller, slug)
        row = _open_decision(conn, mine, request_id)
        if "trust:admin" not in tokens_of(mine.trust, mine.role, mine.role_base):
            raise ApiError(
                403, "forbidden", "only an admin claims from the pool", {"reason": "not_admin"}
            )
        if mine.kind == "agent" and inbox.humans_only(row):
            raise humans_only("only a human admin claims a humans_only request")
        _refuse_by_kind(conn, row, mine)  # a holder that may not answer would strand it
        if inbox.is_asker(row, mine):
            raise invalid({"to": "self"}, "nobody holds a request it asked")
        won = conn.execute(
            update(t.request)
            .where(t.request.c.id == row.id, _pool_open())
            .values(
                holder_member=mine.id,
                holder_pool=None,
                forwarding=_step(conn, row, "claimed", mine.principal_id, mine.principal_id, None),
                changed_by_credential=caller.credential_id,
                changed_via=caller.via,
            )
        ).rowcount
        if won != 1:  # the first claim won, or it was never opened to the admins
            raise ApiError(
                409,
                "request_claimed",
                "another admin holds the request",
                {"holder": _holder(conn, _row(conn, row.id))},
            )
        after = _row(conn, row.id)
        view = request_view(conn, after)
        emit(
            conn,
            mine.project.id,
            "request_claimed",
            _forwarding_audience(conn, mine, row, after),
            {**view, "step": (after.forwarding or [])[-1]},
            actor=caller.actor(mine.id),
            subject=("request", row.id),
        )
        return idempotency.Outcome(200, "request", row.id, view)

    return idempotency.run(engine_of(request), request, caller, action)


def _talk_allowed(conn: Connection, row: Any, caller: Caller) -> str:
    """`talk` only from the human who owns the asking agent; the conversation is that agent."""
    if row.asked_by is None:  # an organisation's invitation: no agent asked
        raise invalid(
            {"talk": "only_the_owner_of_the_agent"}, "only the agent's own human can talk"
        )
    asker = conn.execute(select(t.membership).where(t.membership.c.id == row.asked_by)).one()
    if caller.kind == "human" and asker.agent_id is not None:
        owner = conn.execute(
            select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == asker.agent_id)
        ).scalar()
        if owner == caller.human_id:
            agent_id: str = asker.agent_id
            return agent_id
    raise invalid({"talk": "only_the_owner_of_the_agent"}, "only the agent's own human can talk")


@router.post("/projects/{owner}/{slug}/requests/{request_id}/withdraw")
def withdraw(
    slug: str, request_id: str, body: WithdrawIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        found = membership(conn, caller, slug)
        if found.project.owner_org_id is not None:
            orgs.lock(conn, found.project.owner_org_id)
        mine = _locked(conn, found)
        if mine.project.owner_org_id != found.project.owner_org_id:
            raise orgs.project_moved()
        row = _project_request(conn, mine, request_id)
        # Only its human, or the hub, withdraws a personal request (§7); the one who started a
        # transfer into an organisation withdraws the requests that carry it (§6.26).
        org_transfer = row.personal and row.org_id is not None and inbox.is_asker(row, mine)
        # A cross-owner `reports_to` pair and a bridge's consents across owners have their
        # own withdrawal rule (§6.2, §2.3).
        kind = (row.proposal or {}).get("kind")
        pair = (row.personal and kind == cross_owner.KIND) or kind in bridges.KINDS
        if pair:
            allowed = (
                bridges.may_withdraw(conn, row, mine)
                if kind in bridges.KINDS
                else cross_owner.may_withdraw(conn, row, mine)
            )
            if allowed is None:
                raise not_found()
            if not allowed:
                raise ApiError(
                    403,
                    "forbidden",
                    "an agent that did not ask for the edge does not end the owners' decision",
                    {"reason": "pending_consent"},
                )
        elif row.personal and not org_transfer and not _foreign_asker(row, mine):
            raise not_found()
        if not pair and not (inbox.is_asker(row, mine) or mine.may("requests:answer")):
            raise forbidden("requests:answer")
        _refuse_unless_open(row)
        proposals.require_known(row)
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
        placements.settle(conn, row, "withdrawn", caller.actor(mine.id), mine.principal_id)
        proposals.settle(conn, row, "withdrawn", None, caller.actor(mine.id))
        view = request_view(conn, _row(conn, row.id))
        emit(
            conn,
            mine.project.id,
            "request_withdrawn",
            _asker_audience(conn, row),
            _payload(row, view, reason=body.reason),
            actor=caller.actor(mine.id),
            subject=("request", row.id),
        )
        return idempotency.Outcome(200, "request", row.id, view)

    return idempotency.run(engine_of(request), request, caller, action)


def return_held(conn: Connection, request_id: str, by: str, reason: str) -> None:
    """Give an open `decision` request its holder can no longer hold back to the admins
    (`holder: trust:admin`, §7), from inside the hub: a step `opened` in `forwarding` and
    `request_forwarded`, as a forward to the pool would write, with the hub as actor. One
    of an owner's round never reaches that pool (§20.7): it goes back to its addressee, a
    step `forwarded`, or is withdrawn when that member has left too."""
    row = _row(conn, request_id)
    if row.status != "open" or row.holder_member is None:
        return
    project = lock_project(conn, row.project_id)
    alone = bool(inbox.owners_alone(conn, [row]))
    if alone and not _addressee_active(conn, row):
        close_request(conn, row.id, "withdrawn", None, reason=reason)
        return
    if alone:
        steps = _step(conn, row, "forwarded", inbox.addressee_of(row).text(conn), by, reason)
    else:
        steps = _step(conn, row, "opened", "trust:admin", by, reason)
    conn.execute(
        update(t.request)
        .where(t.request.c.id == row.id)
        .values(
            holder_member=None,
            holder_pool=None if alone else True,
            forwarding=steps,
            changed_by_credential=None,
            changed_via=None,
        )
    )
    after = _row(conn, row.id)
    view = request_view(conn, after)
    where = cast(Membership, SimpleNamespace(project=project))  # only the project is read
    emit(
        conn,
        row.project_id,
        "request_forwarded",
        _forwarding_audience(conn, where, row, after),
        {**view, "step": steps[-1]},
        subject=("request", row.id),
    )


def _addressee_active(conn: Connection, row: Any) -> bool:
    return bool(
        conn.execute(
            select(t.membership.c.active).where(t.membership.c.id == row.to_member)
        ).scalar()
    )


def withdraw_owners_round(conn: Connection, member_id: int, actor: Actor | None) -> None:
    """The addressee of a request of an owner's round leaves (§6.2, §20.7): nobody else may
    read it, so it would lie open with nobody to answer it. One it forwarded stays with its
    holder."""
    rows = conn.execute(
        select(t.request)
        .where(
            t.request.c.to_member == member_id,
            t.request.c.status == "open",
            or_(t.request.c.holder_member.is_(None), t.request.c.holder_member == member_id),
        )
        .order_by(t.request.c.created_at, t.request.c.id)
    ).all()
    for request_id in sorted(inbox.owners_alone(conn, rows)):
        close_request(conn, request_id, "withdrawn", actor, reason="member_removed")


def close_request(
    conn: Connection,
    request_id: str,
    outcome: str,
    actor: Actor | None,
    *,
    by: str | None = None,
    reason: str | None = None,
) -> None:
    """Answer (`go`, in `by`'s name) or withdraw an open request from inside the hub, as
    the routes above would. A proposal it carries is settled here, like every other
    close; a placement is not settled again: the placement code that calls this settles
    its own side (§15.6). A proposal of a kind this hub does not know is withdrawn
    without its settle hook, and the reason and the log say so: a close the hub makes
    itself (the proposer's removal) must not fail on it, while an explicit answer still
    does (`proposals.require_known`)."""
    row = _row(conn, request_id)
    if row.status != "open":
        return
    unknown = not proposals.known(row)
    if unknown:
        outcome = "withdrawn"
        kind = (proposals.of(row) or {}).get("kind")
        note = f"its proposal's kind {kind!r} is unknown to this hub, so it was not settled"
        reason = f"{reason}; {note}" if reason else note
        log.warning("request %s withdrawn by the hub: %s", row.id, note)
    now = clock.now()
    audit = {
        "changed_by_credential": actor.credential_id if actor else None,
        "changed_via": actor.via if actor else None,
    }
    if outcome == "withdrawn":
        conn.execute(
            update(t.request)
            .where(t.request.c.id == row.id)
            .values(
                status="withdrawn",
                withdrawn_at=now,
                withdraw_reason=reason,
                **_snapshot(conn, row),
                **audit,
            )
        )
        kind, extra = "request_withdrawn", {"reason": reason}
    else:
        stored: dict[str, Any] = {
            "reply_id": outcome,
            "text": None,
            "talk": False,
            "by": by,
            "on_behalf_of": None,
            "at": clock.rfc3339(now),
            "conversation_id": None,
            "mentions": [],
        }
        conn.execute(
            update(t.request)
            .where(t.request.c.id == row.id)
            .values(
                status="answered",
                answer=stored,
                answered_by=actor.membership_id if actor else None,
                answered_at=now,
                **_snapshot(conn, row),
                **audit,
            )
        )
        kind, extra = "request_answered", {}
    _unblock(conn, row)
    if not unknown:
        proposals.settle(
            conn,
            row,
            outcome,
            None if outcome == "withdrawn" else by,
            actor,
            reply_id=outcome if outcome in ("go", "no") else None,
        )
    closed = _row(conn, row.id)
    records.personal_request(conn, closed)
    if row.project_id is None:  # an organisation's request: no project, no project event
        return
    view = request_view(conn, closed)
    emit(
        conn,
        row.project_id,
        kind,
        _asker_audience(conn, row),
        _payload(row, view, **extra),
        actor=actor,
        subject=("request", row.id),
    )
    if kind == "request_answered":
        project = conn.execute(select(t.project).where(t.project.c.id == row.project_id)).one()
        ticker.on_request_answered(conn, project, _row(conn, row.id), actor)


def file_consent(
    conn: Connection,
    mine: Membership,
    caller: Caller,
    title_text: str,
    summary: str,
    *,
    placement_id: str | None = None,
    proposal: dict[str, Any] | None = None,
) -> str:
    """A consent request to the owner, go/no, waiting, linked to the placement it
    settles (§15.6) or carrying the proposal it applies (`proposals`, §2.3 ᵃ), never
    both; returns its id."""
    if placement_id is not None and proposal is not None:
        raise ValueError("a consent settles a placement or carries a proposal, not both")
    if proposal is not None:
        proposals.check_kind(proposal)
    request_id = new_id("request")
    to = inbox.Addressee("owner")
    conn.execute(
        insert(t.request).values(
            {
                "id": request_id,
                "project_id": mine.project.id,
                "class": "consent",
                "title": title_text[:200],
                "summary": summary,
                "options": [],
                "priority": "normal",
                "to_kind": to.kind,
                "asked_by": mine.id,
                "asked_session_id": caller.session_id,
                "placement_id": placement_id,
                "proposal": proposal,
                "while_open": "wait",
                "status": "open",
                "changed_by_credential": caller.credential_id,
                "changed_via": caller.via,
                "created_at": clock.now(),
            }
        )
    )
    emit(
        conn,
        mine.project.id,
        "request_created",
        _addressee_audience(conn, mine, to),
        request_view(conn, _row(conn, request_id)),
        actor=caller.actor(mine.id),
        subject=("request", request_id),
    )
    return request_id


def file_proposal(
    conn: Connection,
    project_id: str,
    asked_by: int,
    class_: str,
    title_text: str,
    summary: str,
    proposal: dict[str, Any],
    *,
    to: inbox.Addressee,
    options: list[dict[str, str]],
    while_open: str,
    actor: Actor | None,
    tried: str | None = None,
    task_id: str | None = None,
    takeover_id: str | None = None,
) -> str:
    """A request the hub files on someone's behalf that carries a proposal of a registered
    kind: any class, addressee and options, unlike `file_consent` (§6.19's escalation is a
    `decision` to `trust:admin` with `transfer` and `keep`); returns its id."""
    proposals.check_kind(proposal)
    request_id = new_id("request")
    conn.execute(
        insert(t.request).values(
            {
                "id": request_id,
                "project_id": project_id,
                "class": class_,
                "title": title_text[:200],
                "summary": summary,
                "tried": tried,
                "options": options,
                "priority": "normal",
                "to_kind": to.kind,
                "to_member": to.member,
                "to_role": to.role,
                "asked_by": asked_by,
                "asked_session_id": actor.session_id if actor else None,
                "task_id": task_id,
                "takeover_id": takeover_id,
                "proposal": proposal,
                "while_open": while_open,
                "status": "open",
                "changed_by_credential": actor.credential_id if actor else None,
                "changed_via": actor.via if actor else None,
                "created_at": clock.now(),
            }
        )
    )
    emit(
        conn,
        project_id,
        "request_created",
        _audience_of(conn, project_id, to),
        request_view(conn, _row(conn, request_id)),
        actor=actor,
        subject=("request", request_id),
    )
    return request_id


# --- personal requests (§7) ---------------------------------------------------------------


def file_personal(
    conn: Connection,
    mine: Membership,
    caller: Caller,
    agent_id: str,
    class_: str,
    title_text: str,
    summary: str,
    *,
    options: list[dict[str, Any]] | None = None,
    task_id: str | None = None,
    proposal: dict[str, Any] | None = None,
) -> str:
    """A request the hub files to the human who owns the agent profile `agent_id`, member
    of the project or not (`to: profile_owner:<agent id>`); returns its id. Nothing else
    creates one, and nobody but the asker sees it through the project.

    It keeps the asker's project in `project_id`, so the project's paths find it for the
    asker and its events have a log. `to_human` is the owner at filing time: a profile
    that later changes hands leaves its open personal requests with the human asked."""
    if proposal is not None:
        proposals.check_kind(proposal)
    owner = conn.execute(
        select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == agent_id)
    ).scalar_one()
    return _file_personal(
        conn,
        mine,
        caller,
        class_,
        title_text,
        summary,
        to_kind="profile_owner",
        to_profile=agent_id,
        to_human=owner,
        options=options,
        task_id=task_id,
        proposal=proposal,
    )


def file_to_human(
    conn: Connection,
    mine: Membership,
    caller: Caller,
    human_id: str,
    title_text: str,
    summary: str,
    proposal: dict[str, Any],
) -> str:
    """A consent request the hub files to a human in person (`to: human:<human id>`,
    §19.4), with the proposal its go applies; personal like `file_personal`'s."""
    proposals.check_kind(proposal)
    return _file_personal(
        conn,
        mine,
        caller,
        "consent",
        title_text,
        summary,
        to_kind="human",
        to_profile=None,
        to_human=human_id,
        proposal=proposal,
    )


def file_to_human_outside(
    conn: Connection,
    project_id: str,
    caller: Caller,
    human_id: str,
    title_text: str,
    summary: str,
    proposal: dict[str, Any],
) -> str:
    """A consent request to a human in person, asked by a human who is no member of the
    project (`asked_by_human`): an agent's owner setting its boss across owners (§6.2). It
    carries the project, and no event reaches the asker or anyone else outside it."""
    proposals.check_kind(proposal)
    request_id = new_id("request")
    conn.execute(
        insert(t.request).values(
            {
                "id": request_id,
                "project_id": project_id,
                "class": "consent",
                "title": title_text,
                "summary": summary,
                "options": [],
                "priority": "normal",
                "to_kind": "human",
                "to_human": human_id,
                "personal": True,
                "proposal": proposal,
                "asked_by": None,
                "asked_by_human": caller.human_id,
                "while_open": "wait",
                "status": "open",
                "changed_via": caller.via,
                "created_at": clock.now(),
            }
        )
    )
    row = _row(conn, request_id)
    records.personal_request(conn, row)
    emit(
        conn,
        project_id,
        "request_created",
        [],
        _payload(row, request_view(conn, row)),
        actor=Actor(membership_id=None, human_id=caller.human_id, via=caller.via),
        subject=("request", request_id),
    )
    return request_id


def file_org_consent(
    conn: Connection,
    mine: Membership,
    caller: Caller,
    title_text: str,
    summary: str,
    proposal: dict[str, Any],
    *,
    to_human: str,
    org_id: str,
) -> str:
    """A consent request to one owner of an organisation about a project (§6.26): personal,
    with both the project and `org: {id, handle}`, the asker the project's member who started
    the transfer. Returns its id."""
    proposals.check_kind(proposal)
    return _file_personal(
        conn,
        mine,
        caller,
        "consent",
        title_text,
        summary,
        to_kind="human",
        to_profile=None,
        to_human=to_human,
        proposal=proposal,
        org_id=org_id,
    )


def _file_personal(
    conn: Connection,
    mine: Membership,
    caller: Caller,
    class_: str,
    title_text: str,
    summary: str,
    *,
    to_kind: str,
    to_profile: str | None,
    to_human: str,
    options: list[dict[str, Any]] | None = None,
    task_id: str | None = None,
    proposal: dict[str, Any] | None = None,
    org_id: str | None = None,
) -> str:
    request_id = new_id("request")
    conn.execute(
        insert(t.request).values(
            {
                "id": request_id,
                "project_id": mine.project.id,
                "org_id": org_id,
                "class": class_,
                "title": title_text,
                "summary": summary,
                "options": options or [],
                "priority": "normal",
                "to_kind": to_kind,
                "to_profile": to_profile,
                "to_human": to_human,
                "personal": True,
                "proposal": proposal,
                "asked_by": mine.id,
                "asked_session_id": caller.session_id,
                "task_id": task_id,
                "while_open": "wait",
                "status": "open",
                "changed_by_credential": caller.credential_id,
                "changed_via": caller.via,
                "created_at": clock.now(),
            }
        )
    )
    row = _row(conn, request_id)
    records.personal_request(conn, row)
    emit(
        conn,
        mine.project.id,
        "request_created",
        _asker_audience(conn, row),
        _payload(row, request_view(conn, row)),
        actor=caller.actor(mine.id),
        subject=("request", request_id),
    )
    return request_id


def _preference_edit(conn: Connection, row: Any, body: AnswerIn) -> Any:
    """A preference proposal's go on a stale base is `conflict` before anything is
    answered (§19.4); the human's edit goes into the proposal its settlement applies."""
    from maity_hub import preferences

    edit = (
        {"markdown": body.markdown, "base_version": body.base_version}
        if body.markdown is not None
        else None
    )
    preferences.check_answer(conn, row, body.reply_id, edit)
    if edit is None:
        return row
    conn.execute(
        update(t.request)
        .where(t.request.c.id == row.id)
        .values(proposal={**row.proposal, "edit": edit})
    )
    return _row(conn, row.id)


def _human(caller: Caller) -> None:
    """§2.3: no agent reads, answers or withdraws a personal request on these routes."""
    if caller.kind != "human":
        raise humans_only("a personal request is its human's alone")


def _locked_personal(
    conn: Connection, caller: Caller, request_id: str, *, asker: bool = False
) -> Any:
    """`_personal` under its project's lock, read again after locking, as the project
    routes do: an answer and a withdrawal at once cannot both change it."""
    row = _personal(conn, caller, request_id, asker=asker)
    # An organisation's row before any project's, in the order of their ids (§6.26): the
    # request's own organisation, and the one that owns the project, which a transfer out of
    # it frees.
    wanted = {row.org_id, (row.proposal or {}).get("owner_id")}
    for org_id in sorted(i for i in wanted if isinstance(i, str) and i.startswith("org-")):
        orgs.lock(conn, org_id)
    if row.project_id is not None:
        lock_project(conn, row.project_id)
    return _personal(conn, caller, request_id, asker=asker)


def _personal(conn: Connection, caller: Caller, request_id: str, *, asker: bool = False) -> Any:
    """A personal request addressed to the calling human; any other id is `not_found`. With
    `asker`, also a cross-owner `reports_to` request of the pair the caller is an owner of
    (§6.2): the one they asked as an owner outside the project, and the one addressed to the
    other owner; they read and withdraw it, never answer it."""
    row = conn.execute(
        select(t.request).where(t.request.c.id == request_id, t.request.c.personal.is_(True))
    ).first()
    if row is not None and row.to_human == caller.human_id:
        return row
    pair_owner = (
        row is not None
        and asker
        and _is_cross_owner(row)
        and (row.asked_by_human == caller.human_id or _addressed_in_pair(conn, row, caller))
    )
    if pair_owner:
        return row
    raise not_found()


def _addressed_in_pair(conn: Connection, row: Any, caller: Caller) -> bool:
    """The caller is the addressee of a request of the pair `row` belongs to."""
    named = (row.proposal or {}).get("requests") or []
    return (
        conn.execute(
            select(t.request.c.id).where(
                t.request.c.id.in_(named), t.request.c.to_human == caller.human_id
            )
        ).first()
        is not None
    )


def _scope_project(conn: Connection, row: Any) -> dict[str, Any] | None:
    """The request's project inline, or None for one that concerns an organisation only."""
    return None if row.project_id is None else _project_inline(conn, row.project_id)


def _org_inline_of(conn: Connection, org_id: str) -> dict[str, Any]:
    handle = conn.execute(select(t.org.c.handle).where(t.org.c.id == org_id)).scalar_one()
    return {"id": org_id, "handle": handle}


def _org_inline(conn: Connection, row: Any) -> dict[str, Any] | None:
    """`{id, handle}` of the organisation a personal request concerns (§7, §6.26), else None."""
    return None if row.org_id is None else _org_inline_of(conn, row.org_id)


def _project_inline(conn: Connection, project_id: str) -> dict[str, Any]:
    project = conn.execute(select(t.project).where(t.project.c.id == project_id)).one()
    return {
        "slug": project.slug,
        "full_name": namespace.full_name(conn, project),
        "name": project.name,
        "state": project.state,
    }


@router.get("/requests/{request_id}")
def get_personal(request_id: str, request: Request, caller: AnyCaller) -> JSONResponse:
    _human(caller)
    with engine_of(request).begin() as conn:
        row = _personal(conn, caller, request_id, asker=True)
        # The reading human reviews what a proposal would apply (§19.4), against their
        # current text, which only they see here.
        view = request_view(conn, row, with_proposal=True)
        if (row.proposal or {}).get("kind") == "preferences":
            from maity_hub import preferences

            view["memory_proposal"] = {
                **view["memory_proposal"],
                **preferences.review_view(conn, row),
            }
        return JSONResponse(
            {**view, "project": _scope_project(conn, row), "org": _org_inline(conn, row)}
        )


@router.post("/requests/{request_id}/answer")
def answer_personal(
    request_id: str, body: AnswerIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    _human(caller)

    def action(conn: Connection) -> idempotency.Outcome:
        row = _locked_personal(conn, caller, request_id)
        _refuse_unless_open(row)
        proposals.require_known(row)
        _check_answer(row, body)
        _step_up_for_a_transfer(conn, request, caller, row, body)
        if (row.proposal or {}).get("kind") == "preferences":
            row = _preference_edit(conn, row, body)
        conversation_id = _talk_allowed(conn, row, caller) if body.talk else None
        member = _member_of(conn, row.project_id, caller.human_id)
        now = clock.now()
        stored = {
            "reply_id": body.reply_id,
            "text": body.text,
            "talk": bool(body.talk),
            "by": caller.human_id,
            "on_behalf_of": None,
            "at": clock.rfc3339(now),
            "conversation_id": conversation_id,
            # Resolved for a member only: a non-member learns nobody's id through it (§6.2).
            "mentions": (
                mentions.resolve(conn, row.project_id, body.text, "text") if member else []
            ),
        }
        done = conn.execute(
            update(t.request)
            .where(t.request.c.id == row.id, t.request.c.status == "open")
            .values(
                status="answered",
                answer=stored,
                answered_by=member.id if member is not None else None,
                answered_at=now,
                changed_by_credential=None,
                changed_via=caller.via,
                **_snapshot(conn, row),
            )
        ).rowcount
        if done != 1:
            _refuse_unless_open(_row(conn, row.id))
        _unblock(conn, row)
        actor = caller.actor(member.id) if member is not None else None
        outcome = "go" if body.reply_id == "go" else "no"
        proposals.settle(
            conn, _row(conn, row.id), outcome, caller.human_id, actor, reply_id=body.reply_id
        )
        closed = _row(conn, row.id)
        records.personal_request(conn, closed)
        view = request_view(conn, closed)
        if row.project_id is not None:  # an organisation's request has no project's events
            emit(
                conn,
                row.project_id,
                "request_answered",
                _asker_audience(conn, row),
                _payload(row, view),
                actor=caller.actor(member.id) if member is not None else None,
                subject=("request", row.id),
            )
        return idempotency.Outcome(200, "request", row.id, view)

    try:
        return idempotency.run(engine_of(request), request, caller, action)
    except proposals.Stale as stale:
        # The go no longer applies (an expired invitation): the request is withdrawn and the
        # kind's own clean-up runs, nothing else changes, as on the project route.
        with events.transaction(engine_of(request)) as conn:
            close_request(conn, stale.request_id, "withdrawn", None, reason=stale.reason)
        raise stale.error from None


@router.post("/requests/{request_id}/withdraw")
def withdraw_personal(
    request_id: str, body: WithdrawIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    _human(caller)

    def action(conn: Connection) -> idempotency.Outcome:
        row = _locked_personal(conn, caller, request_id, asker=True)
        _refuse_unless_open(row)
        member = _member_of(conn, row.project_id, caller.human_id)
        done = conn.execute(
            update(t.request)
            .where(t.request.c.id == row.id, t.request.c.status == "open")
            .values(
                status="withdrawn",
                withdrawn_at=clock.now(),
                withdraw_reason=body.reason,
                changed_by_credential=None,
                changed_via=caller.via,
                **_snapshot(conn, row),
            )
        ).rowcount
        if done != 1:
            _refuse_unless_open(_row(conn, row.id))
        _unblock(conn, row)
        # A proposal is settled wherever its request closes (`proposals`): the invited
        # human's own withdrawal of an organisation's invitation counts as their no.
        if row.proposal is not None:
            proposals.require_known(row)
            proposals.settle(
                conn,
                _row(conn, row.id),
                "withdrawn",
                None,
                caller.actor(member.id) if member is not None else None,
            )
        closed = _row(conn, row.id)
        records.personal_request(conn, closed)
        view = request_view(conn, closed)
        if row.project_id is not None:
            emit(
                conn,
                row.project_id,
                "request_withdrawn",
                _asker_audience(conn, row),
                _payload(row, view),
                actor=caller.actor(member.id) if member is not None else None,
                subject=("request", row.id),
            )
        return idempotency.Outcome(200, "request", row.id, view)

    return idempotency.run(engine_of(request), request, caller, action)


SEEN = [{"id": "seen", "label": "Seen", "detail": None}]


def file_hub_notice(
    conn: Connection, project_id: str, member_id: int, agent_id: str, title_text: str, summary: str
) -> str:
    """A notice the hub files to the owner of agent profile `agent_id` on the agent's
    behalf (`filed_by: hub`, §7): class `info`, one option `seen`, `asked_by` the agent's
    member with no instance. Its events reach the owner only, and only when a member."""
    owner = conn.execute(
        select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == agent_id)
    ).scalar_one()
    request_id = new_id("request")
    conn.execute(
        insert(t.request).values(
            {
                "id": request_id,
                "project_id": project_id,
                "class": "info",
                "title": title_text[: t.TITLE],
                "summary": summary,
                "options": SEEN,
                "priority": "normal",
                "to_kind": "profile_owner",
                "to_profile": agent_id,
                "to_human": owner,
                "personal": True,
                "filed_by": "hub",
                "asked_by": member_id,
                "asked_session_id": None,
                "while_open": "wait",
                "status": "open",
                "created_at": clock.now(),
            }
        )
    )
    row = _row(conn, request_id)
    records.personal_request(conn, row)
    emit(
        conn,
        project_id,
        "request_created",
        _asker_audience(conn, row),
        _payload(row, request_view(conn, row)),
        subject=("request", request_id),
    )
    return request_id


def file_hub_digest(conn: Connection, human_id: str, title_text: str, summary: str) -> str:
    """The owner's digest of agent instances that are not listening (§5.3): a personal
    request to the human in person, `filed_by: hub`, class `info`, one option `seen`, with
    no asker, no project and no organisation. Without a project it has no events; the
    human hears of it through its record, as of an organisation's invitation."""
    request_id = new_id("request")
    conn.execute(
        insert(t.request).values(
            {
                "id": request_id,
                "project_id": None,
                "org_id": None,
                "class": "info",
                "title": title_text[: t.TITLE],
                "summary": summary,
                "options": SEEN,
                "priority": "normal",
                "to_kind": "human",
                "to_human": human_id,
                "personal": True,
                "filed_by": "hub",
                "asked_by": None,
                "asked_by_human": None,
                "asked_session_id": None,
                "while_open": "wait",
                "status": "open",
                "created_at": clock.now(),
            }
        )
    )
    records.personal_request(conn, _row(conn, request_id))
    return request_id


def withdraw_hub_notice(conn: Connection, request_id: str | None, reason: str) -> None:
    """Withdraw a hub notice that is still open; one already answered or withdrawn by its
    owner stays as it is."""
    if request_id is None:
        return
    row = _row(conn, request_id)
    done = conn.execute(
        update(t.request)
        .where(t.request.c.id == request_id, t.request.c.status == "open")
        .values(
            status="withdrawn",
            withdrawn_at=clock.now(),
            withdraw_reason=reason,
            changed_by_credential=None,
            **_snapshot(conn, row),
        )
    ).rowcount
    if done != 1:
        return
    closed = _row(conn, request_id)
    records.personal_request(conn, closed)
    emit(
        conn,
        row.project_id,
        "request_withdrawn",
        _asker_audience(conn, row),
        _payload(row, request_view(conn, closed)),
        subject=("request", request_id),
    )


def _foreign_asker(row: Any, mine: Membership) -> bool:
    """The caller asked for a change of another owner's agent: they withdraw it, the owner
    answers it (§6.2, "Another owner's agent")."""
    return (row.proposal or {}).get("kind") == foreign_agent.KIND and inbox.is_asker(row, mine)


def _is_cross_owner(row: Any) -> bool:
    return (row.proposal or {}).get("kind") == cross_owner.KIND


def _asker_matches(conn: Connection, row: Any, caller: Caller, asked_by: str) -> bool:
    """`asked_by` of a personal request: a member id, or `me` for a request the caller asked
    themselves as an owner outside the project (§7)."""
    asker = principal_id(conn, row.asked_by) if row.asked_by is not None else row.asked_by_human
    return asker == asked_by or (asked_by == "me" and asker == caller.human_id)


def _personal_inbox(
    conn: Connection,
    caller: Caller,
    *,
    status: str,
    class_: str | None,
    asked_by: str | None,
    to: str,
) -> list[dict[str, Any]]:
    """The personal requests addressed to the caller, for `GET /requests` (§7)."""
    if to not in ("me", "all"):
        return []  # addressed to the caller, never to a member, role or the owner
    # Addressed to the caller, or a cross-owner `reports_to` request they asked as an owner
    # outside the project (§7): no one else's, whatever else carries `asked_by_human`.
    query = select(t.request).where(
        t.request.c.personal.is_(True),
        (t.request.c.to_human == caller.human_id) | (t.request.c.asked_by_human == caller.human_id),
    )
    if status != "all":
        query = query.where(t.request.c.status.in_([s for s in status.split(",") if s]))
    if class_ is not None:
        query = query.where(t.request.c["class"] == class_)
    rows = [
        row
        for row in conn.execute(query).all()
        if (row.to_human == caller.human_id or _is_cross_owner(row))
        and (asked_by is None or _asker_matches(conn, row, caller, asked_by))
    ]
    inline = {p: _project_inline(conn, p) for p in {r.project_id for r in rows if r.project_id}}
    orgs_inline = {o: _org_inline_of(conn, o) for o in {r.org_id for r in rows if r.org_id}}
    return _entries(
        conn,
        rows,
        lambda row: {
            "project": inline.get(row.project_id) if row.project_id else None,
            "org": orgs_inline.get(row.org_id) if row.org_id else None,
        },
    )
