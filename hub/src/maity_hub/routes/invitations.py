"""Invitations for humans (docs/api.md §3.4): issue, list and revoke them in a project,
the public page behind the link, and accepting it.

A join link brings an agent; an invitation brings a person. The token is 128 bits,
shown once in the `url` and stored as its hash. An unknown, used, expired or revoked
token is one uniform `not_found`, on the page and on accept alike.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import AfterValidator
from sqlalchemy import Connection, and_, insert, or_, select, update
from starlette.concurrency import run_in_threadpool

from maity_hub import (
    clock,
    events,
    idempotency,
    invitation_mail,
    invitations,
    namespace,
    paging,
    registration,
)
from maity_hub import tables as t
from maity_hub.access import membership
from maity_hub.codes import digest, new_token
from maity_hub.db import retrying
from maity_hub.deps import HumanCaller, engine_of, origin_of, settings_of
from maity_hub.errors import ApiError, invalid, not_found, rate_limited
from maity_hub.events import Actor
from maity_hub.ids import new_id
from maity_hub.mail import address
from maity_hub.models import Strict
from maity_hub.namespace import ProjectRoute
from maity_hub.policy import CLOSED_STATES
from maity_hub.routes.joins import EXCHANGE_BY_ADDRESS
from maity_hub.scopes import ROLES
from maity_hub.views import member_view

router = APIRouter(route_class=ProjectRoute)

PAGE_DEFAULT, PAGE_MAX = 50, 200


def _known_role(value: str) -> str:
    """A built-in role of §2.3, from the one list `scopes` keeps."""
    if value not in ROLES:
        raise ValueError(f"role must be one of {', '.join(ROLES)}")
    return value


class InvitationIn(Strict):
    trust: Literal["owner", "admin", "member", "guest"] = "member"
    role: Annotated[str, AfterValidator(_known_role)] = "coder"
    address: str | None = None
    ttl_seconds: int = invitations.TTL_DEFAULT
    note: str | None = None
    via: Literal["join", "public"] | None = None


def _check(body: InvitationIn) -> None:
    errors: dict[str, str] = {}
    if body.address is not None and not address.valid(body.address.strip()):
        errors["address"] = "invalid"
    if not invitations.TTL_MIN <= body.ttl_seconds <= invitations.TTL_MAX:
        errors["ttl_seconds"] = "out_of_range"
    if body.note is not None and (
        len(body.note.encode()) > invitations.NOTE_MAX
        or any(ord(c) < 32 and c not in "\n\t" or ord(c) == 127 for c in body.note)
    ):
        errors["note"] = "invalid"
    if errors:
        raise invalid(errors)


def _via(request: Request, body: InvitationIn) -> str:
    """The host of the link: the join host when one is configured and `via` does not say
    otherwise (§3.4); `join` without one is `invalid`."""
    settings = settings_of(request)
    via = body.via or ("join" if settings.join_url else "public")
    if via == "join" and settings.join_url is None:
        raise invalid({"via": "no_join_host"}, "this hub has no join host")
    return via


def _url(request: Request, via: str, token: str) -> str:
    """`https://<join host>/i/<token>`, a redirect to the page (§1.1), or the page's own."""
    settings = settings_of(request)
    if via == "join" and settings.join_url is not None:
        return f"{settings.join_url}/i/{token}"
    return f"{settings.public_url}/invite/{token}"


def _load(conn: Connection, invitation_id: str) -> dict[str, Any]:
    row = conn.execute(select(t.invitation).where(t.invitation.c.id == invitation_id)).one()
    slug = namespace.name_of(conn, row.project_id)
    return invitations.view(row, str(slug))


idempotency.LOADERS["invitation"] = idempotency.plain(_load)


@router.post("/projects/{owner}/{slug}/invitations", status_code=201)
def create_invitation(
    slug: str, body: InvitationIn, request: Request, caller: HumanCaller
) -> JSONResponse:
    _check(body)
    via = _via(request, body)

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine.require("members:admin")
        if body.role == "proxy" and body.trust != "admin":
            raise invalid({"role": "proxy_needs_admin"}, "a proxy holds trust admin")
        if not invitations.may_issue(body.trust, body.role, mine.trust, mine.role):
            raise ApiError(
                403,
                "forbidden",
                "only an owner grants trust owner or admin, or the role proxy",
                {"reason": "owner_only"},
            )
        wait = invitations.PER_PROJECT.hit(mine.project.id)
        if wait:
            raise rate_limited(wait)
        token = new_token()
        now = clock.now()
        invitation_id = new_id("invitation")
        given = body.address.strip() if body.address is not None else None
        conn.execute(
            insert(t.invitation).values(
                id=invitation_id,
                project_id=mine.project.id,
                trust=body.trust,
                role=body.role,
                address=given,
                address_normalized=registration.normalized(given) if given else None,
                note=body.note or None,
                token_hash=digest(token),
                created_by=caller.principal_id,
                created_at=now,
                expires_at=now + timedelta(seconds=body.ttl_seconds),
                via=via,
            )
        )
        row = conn.execute(select(t.invitation).where(t.invitation.c.id == invitation_id)).one()
        invitations.announce(conn, "invitation_created", row, caller.actor(mine.id))
        url = _url(request, via, token)
        if given is not None:
            invitation_mail.send(conn, invitation_id=invitation_id, to=given, url=url)
        return idempotency.Outcome(
            201,
            "invitation",
            invitation_id,
            invitations.view(row, namespace.full_name(conn, mine.project), url),
        )

    return idempotency.run(engine_of(request), request, caller, action)


@router.get("/projects/{owner}/{slug}/invitations")
def list_invitations(
    slug: str,
    request: Request,
    caller: HumanCaller,
    limit: int = Query(default=PAGE_DEFAULT, ge=1, le=PAGE_MAX),
    cursor: str | None = None,
) -> JSONResponse:
    """Open ones, and those used, revoked, voided or expired within the last 30 days,
    each by its own time (§3.4)."""
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("members:admin")
        c = t.invitation.c
        since = clock.now() - invitations.LISTED_FOR
        query = select(t.invitation).where(
            c.project_id == mine.project.id,
            or_(  # each ended one by the time it ended; an open one has not expired
                c.used_at >= since,
                c.revoked_at >= since,
                c.voided_at >= since,
                and_(
                    c.used_at.is_(None),
                    c.revoked_at.is_(None),
                    c.voided_at.is_(None),
                    c.expires_at >= since,
                ),
            ),
        )
        if cursor is not None:
            after_at, after_id = paging.uncursor(cursor)
            query = query.where(
                or_(c.created_at < after_at, and_(c.created_at == after_at, c.id < after_id))
            )
        rows = conn.execute(query.order_by(c.created_at.desc(), c.id.desc()).limit(limit + 1)).all()
        page = rows[:limit]
        next_cursor = paging.cursor(page[-1].created_at, page[-1].id) if len(rows) > limit else None
        name = namespace.full_name(conn, mine.project)
        items = [invitations.view(r, name) for r in page]
        return JSONResponse({"items": items, "next_cursor": next_cursor})


@router.delete("/projects/{owner}/{slug}/invitations/{invitation_id}")
def revoke_invitation(
    slug: str, invitation_id: str, request: Request, caller: HumanCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine.require("members:admin")
        # Under the project's lock, as accept takes it: an accept and a revocation go in
        # turn, and of two revocations only the first writes and tells (§3.4).
        events.lock_project(conn, mine.project.id)
        row = conn.execute(
            select(t.invitation).where(
                t.invitation.c.id == invitation_id, t.invitation.c.project_id == mine.project.id
            )
        ).first()
        if row is None:
            raise not_found()
        found = invitations.state(row)
        if found not in ("open", "revoked"):
            raise ApiError(
                409,
                "invalid_transition",
                f"a {found} invitation cannot be revoked",
                {"from": found, "to": "revoked"},
            )
        if found == "open":
            conn.execute(
                update(t.invitation)
                .where(t.invitation.c.id == row.id)
                .values(revoked_at=clock.now())
            )
            after = conn.execute(select(t.invitation).where(t.invitation.c.id == row.id)).one()
            invitations.announce(conn, "invitation_revoked", after, caller.actor(mine.id))
        return idempotency.Outcome(200, "invitation", row.id, _load(conn, row.id))

    return idempotency.run(engine_of(request), request, caller, action)


def _open(conn: Connection, token: str) -> Any:
    """The open invitation behind a token, or the uniform `not_found`."""
    row = conn.execute(
        select(t.invitation).where(t.invitation.c.token_hash == digest(token))
    ).first()
    if row is None or invitations.state(row) != "open":
        raise not_found()
    return row


def _logo_url(conn: Connection, request: Request, project: Any) -> str | None:
    from maity_hub import images

    shown = images.views(conn, [project.id]).get(project.id, {})
    if not shown.get("logo", {}).get("available"):
        return None
    name = namespace.full_name(conn, project)
    return f"{settings_of(request).public_url}/api/v1/projects/{name}/logo"


@router.get("/invitations/{token}")
async def invitation_page(token: str, request: Request) -> JSONResponse:
    """What the dashboard's `/invite/<token>` shows (§3.4), the same for every reader."""
    wait = EXCHANGE_BY_ADDRESS.hit(origin_of(request).address)
    if wait:
        raise rate_limited(wait)
    engine = engine_of(request)
    hub = settings_of(request)

    def run() -> dict[str, Any]:
        with engine.begin() as conn:
            row = _open(conn, token)
            project = conn.execute(select(t.project).where(t.project.c.id == row.project_id)).one()
            inviter = conn.execute(
                select(t.human.c.display_name).where(t.human.c.id == row.created_by)
            ).scalar()
            env = hub.registration or registration.RegistrationEnvironment()
            resolved = registration.resolve(
                conn, env, registration.mail_ready(conn, hub), hub.public_url
            )
            return {
                "project": {
                    "slug": project.slug,
                    "full_name": namespace.full_name(conn, project),
                    "name": project.name,
                    "logo_url": _logo_url(conn, request, project),
                },
                "trust": row.trust,
                "role": row.role,
                "invited_by": {"display_name": inviter},
                "note": row.note,
                "expires_at": clock.rfc3339(row.expires_at),
                "address_bound": row.address is not None,
                "registration": _registration(conn, row, project, resolved),
            }

    return JSONResponse(await run_in_threadpool(run))


def _registration(conn: Connection, row: Any, project: Any, resolved: Any) -> str:
    """From the instance and the invitation alone, never from who reads (§3.4)."""
    if not resolved.mail_ready:
        return "sign_in_only"  # no registration without mail, whatever the mode
    if resolved.effective_mode == "open":
        return "sign_in_or_register"
    if row.address is not None and invitations.admits(conn, row, project):
        return "sign_in_or_register"
    return "sign_in_only"


@router.post("/invitations/{token}/accept", status_code=201)
async def accept_invitation(token: str, request: Request, caller: HumanCaller) -> JSONResponse:
    """§3.4: one transaction, under the project's lock. A refusal that changes the
    invitation (used up, voided) is committed before it is answered."""
    wait = EXCHANGE_BY_ADDRESS.hit(origin_of(request).address)
    if wait:
        raise rate_limited(wait)
    engine = engine_of(request)

    def run() -> tuple[ApiError | None, dict[str, Any] | None]:
        with events.transaction(engine) as conn:
            # Before any side effect (§2.7.5): a pending account learns nothing of the token.
            status = conn.execute(
                select(t.human.c.account_status).where(t.human.c.id == caller.human_id)
            ).scalar_one()
            if status != "active":
                return _refused("account_pending", "the account waits for approval")
            row = _open(conn, token)
            project = events.lock_project(conn, row.project_id)
            row = _open(conn, token)  # as it is under the lock: a second accept loses
            return _accept(conn, row, project, caller)

    refusal, member = await run_in_threadpool(retrying, run)
    if refusal is not None:
        raise refusal
    return JSONResponse(member, status_code=201)


def _accept(
    conn: Connection, row: Any, project: Any, caller: Any
) -> tuple[ApiError | None, dict[str, Any] | None]:
    # TODO(§2.6.5): accept only from a session in good standing — a session fresh from a
    # mailbox link accepts nothing — once such sessions exist; every session is one now.
    if project.state in CLOSED_STATES:
        return ApiError(409, "project_closed", f"the project is {project.state}"), None
    if row.address_normalized is not None and (
        invitations.account_address(conn, caller.human_id) != row.address_normalized
    ):
        return _refused("invitation_address_mismatch", "this invitation is for another address")
    outsider = Actor(None, via=caller.via, human_id=caller.human_id)
    already = conn.execute(
        select(t.membership.c.id).where(
            t.membership.c.project_id == row.project_id,
            t.membership.c.human_id == caller.human_id,
            t.membership.c.active.is_(True),
        )
    ).scalar()
    if already is not None:
        if row.address_normalized is not None:  # for this person alone: used up
            _use(conn, row, caller.human_id, caller.actor(already))
        return invalid({"token": "already_member"}, "you are a member already"), None
    if not invitations.issuer_holds(conn, row):
        invitations.void(conn, row, outsider)
        return _refused("invitation_void", "the inviter can no longer grant this invitation")
    now = clock.now()
    result = conn.execute(
        insert(t.membership).values(
            project_id=row.project_id,
            human_id=caller.human_id,
            trust=row.trust,
            role=row.role,
            areas=[],
            capabilities=[],
            joined_at=now,
            last_seen_at=now,
            changed_via=caller.via,
        )
    )
    key = result.inserted_primary_key
    assert key is not None
    membership_id = int(key[0])
    actor = caller.actor(membership_id)
    _use(conn, row, caller.human_id, actor)
    new = conn.execute(select(t.membership).where(t.membership.c.id == membership_id)).one()
    view = member_view(conn, new)
    events.emit(
        conn,
        row.project_id,
        "member_joined",
        ["all"],
        view,
        actor=actor,
        subject=("member", caller.human_id),
    )
    return None, view


def _refused(reason: str, message: str) -> tuple[ApiError, None]:
    return ApiError(403, "forbidden", message, {"reason": reason}), None


def _use(conn: Connection, row: Any, human_id: str, actor: Actor) -> None:
    used = conn.execute(
        update(t.invitation)
        .where(t.invitation.c.id == row.id, t.invitation.c.used_at.is_(None))
        .values(used_at=clock.now(), used_by=human_id)
    ).rowcount
    if used != 1:  # under the project's lock this cannot happen; never two uses
        raise not_found()
    after = conn.execute(select(t.invitation).where(t.invitation.c.id == row.id)).one()
    invitations.announce(conn, "invitation_used", after, actor)
