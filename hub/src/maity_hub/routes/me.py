"""`GET /me` (docs/api.md §5.1) and `GET /me/export` (§2.9)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection, select

from maity_hub import (
    account_deletion,
    avatars,
    clock,
    events,
    export,
    images,
    moderation,
    namespace,
)
from maity_hub import tables as t
from maity_hub.admin import is_instance_admin
from maity_hub.auth import second_factor
from maity_hub.auth.caller import Caller
from maity_hub.deps import AnyCaller, engine_of, settings_of
from maity_hub.errors import forbidden, humans_only, rate_limited, unauthenticated
from maity_hub.models import Strict
from maity_hub.ratelimit import Limiter
from maity_hub.views import agent_member, human_member, isolated, meat_proxy_member, owner_handles

router = APIRouter()

# One export per account in 10 minutes (§2.9): the document reads every project the
# human was ever in, so a loop of it is a load on the hub, not a convenience.
EXPORTS = Limiter(1, 600)


@router.get("/me")
def me(request: Request, caller: AnyCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        if caller.kind == "human":
            assert caller.human_id is not None
            body = human_body(conn, caller.human_id)
        else:
            agent = conn.execute(
                select(t.agent_profile).where(t.agent_profile.c.id == caller.agent_id)
            ).one()
            body = {
                "member": {
                    **agent_member(
                        agent,
                        avatar_url=None,
                        owner_handle=owner_handles(conn, [agent.owner_id])[agent.owner_id],
                    ),
                    **avatars.state(conn, agent.id),
                },
                "projects": _agent_project(conn, caller),
                "membership": {"isolated": _isolated(conn, caller)},
            }
    body["server_time"] = clock.rfc3339(clock.now())
    return JSONResponse(body)


def human_body(conn: Connection, human_id: str) -> dict[str, Any]:
    """A human's `/me` without `server_time`; also the answer of `POST /me/limit`."""
    human = conn.execute(select(t.human).where(t.human.c.id == human_id)).one()
    return {
        "member": {
            **human_member(human, avatar_url=None),
            **avatars.state(conn, human.id),
            "instance_admin": is_instance_admin(conn, human.id),
            **meat_proxy_member(human.meat_proxy_lead, human.meat_proxy_hands),
            # The person's own page, whatever it shows to others (§16.9).
            "public_profile": human.public_profile,
            "public_bio": human.public_bio,
            "website": human.website,
            "social": human.social or {},
            "links_visible": human.links_visible,
            "account_status": human.account_status,
            "terms": (
                {
                    "version": human.terms_version,
                    "accepted_at": clock.rfc3339(human.terms_accepted_at),
                }
                if human.terms_version is not None
                else None
            ),
            # The human's own limit, with the reason other readers may not see (§6.12).
            "limit": limit_view(human),
            # Only while a moderation hold stands on the profile (§16.8).
            **(
                {"moderation": held}
                if (held := moderation.holds_of(conn, "profile", [human.id]).get(human.id))
                else {}
            ),
        },
        # A pending account is a member of nothing (§2.7.5).
        "projects": _human_projects(conn, human.id) if human.account_status == "active" else [],
        # A deletion waiting for its confirmation by mail (§2.9).
        "deletion": account_deletion.view(account_deletion.pending(conn, human.id)),
    }


class DeletionIn(Strict):
    confirm: str = Field(max_length=256)


def _deleting_human(caller: Caller) -> None:
    """Your own account, from a dashboard session (§2.9); an agent never."""
    if caller.kind == "agent":
        raise humans_only("deleting an account is a human's own")
    if caller.kind != "human" or caller.human_session is None:
        raise unauthenticated("this endpoint needs a dashboard session")


@router.post("/me/deletion")
def request_deletion(body: DeletionIn, request: Request, caller: AnyCaller) -> JSONResponse:
    """Step one of deleting the account (§2.9): records the request and mails the link."""
    _deleting_human(caller)
    with events.transaction(engine_of(request)) as conn:
        answer = account_deletion.request(conn, settings_of(request), caller, body.confirm)
    return JSONResponse({"deletion": answer}, status_code=202)


@router.delete("/me/deletion")
def withdraw_deletion(request: Request, caller: AnyCaller) -> JSONResponse:
    """Withdraws a deletion that is not confirmed yet; nothing pending answers the same."""
    _deleting_human(caller)
    with engine_of(request).begin() as conn:
        account_deletion.withdraw(conn, caller.principal_id, "deletion_withdrawn")
    return JSONResponse({"deletion": None})


def limit_view(human: Any) -> dict[str, Any] | None:
    if human.limit_until is None or human.limit_until <= clock.now():
        return None
    return {
        "until": clock.rfc3339(human.limit_until),
        "since": clock.rfc3339(human.limit_since),
        "reason": human.limit_reason,
        "show_reason_in": list(human.limit_show_reason_in or []),
    }


def _project_row(
    project: Any, trust: str, role: str, shown: dict[str, Any], full_name: str
) -> dict[str, Any]:
    logo = shown["logo"]
    return {
        "slug": project.slug,
        "full_name": full_name,
        "name": project.name,
        "state": project.state,
        "trust": trust,
        "role": role,
        # A project switcher shows each project's image without reading every project.
        "logo": {"available": logo["available"], "etag": logo.get("etag")},
    }


def _human_projects(conn: Connection, human_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        select(
            t.membership.c.id,
            t.membership.c.trust,
            t.membership.c.role,
            t.project.c.id.label("project_id"),
            t.project.c.slug,
            t.project.c.name,
            t.project.c.state,
        )
        .join(t.project, t.project.c.id == t.membership.c.project_id)
        .where(t.membership.c.human_id == human_id, t.membership.c.removed_at.is_(None))
        .order_by(t.project.c.slug)
    ).all()
    shown = images.views(conn, [row.project_id for row in rows])
    names = namespace.full_names(conn, [row.project_id for row in rows])
    return [
        {
            **_project_row(row, row.trust, row.role, shown[row.project_id], names[row.project_id]),
            "open_requests": open_requests(conn, row.id),
        }
        for row in rows
    ]


def _isolated(conn: Connection, caller: Caller) -> dict[str, Any] | None:
    """An isolated agent's way to learn why its calls are refused (§6.2)."""
    row = conn.execute(select(t.membership).where(t.membership.c.id == caller.membership_id)).one()
    return isolated(row)


def _agent_project(conn: Connection, caller: Caller) -> list[dict[str, Any]]:
    row = conn.execute(
        select(t.membership.c.trust, t.membership.c.role, t.project)
        .join(t.project, t.project.c.id == t.membership.c.project_id)
        .where(t.membership.c.id == caller.membership_id)
    ).one()
    shown = images.views(conn, [row.id])[row.id]
    return [_project_row(row, row.trust, row.role, shown, namespace.name_of(conn, row.id))]


def open_requests(conn: Connection, membership_id: int) -> int:
    """Open requests addressed to this membership: `GET …/requests` with `to=me` (§7),
    through the listing's own rule so that the two cannot drift."""
    from maity_hub import inbox
    from maity_hub.access import Membership

    row = conn.execute(select(t.membership).where(t.membership.c.id == membership_id)).one()
    project = conn.execute(select(t.project).where(t.project.c.id == row.project_id)).one()
    mine = Membership(project, row, "agent" if row.agent_id else "human")
    open_rows = conn.execute(
        select(t.request).where(
            t.request.c.project_id == row.project_id,
            t.request.c.status == "open",
            # A personal request is never addressed to a membership (§7): not read here.
            t.request.c.personal.is_(False),
        )
    ).all()
    return sum(1 for r in open_rows if inbox.addressed_to(conn, r, mine))


@router.get("/me/export")
def export_own_data(request: Request, caller: AnyCaller) -> JSONResponse:
    """The caller's own data as one JSON document to save (§2.9).

    A sensitive call (§2.8.4): an enrolled human gives the second factor first."""
    if caller.kind == "agent":
        raise humans_only("the export is a human's own")
    if caller.kind != "human" or caller.human_id is None:
        raise forbidden(message="the export needs a dashboard session")
    with engine_of(request).begin() as conn:
        second_factor.require_step_up(conn, settings_of(request), caller)  # §2.8.4
    wait, mark = EXPORTS.place(caller.human_id)
    if wait:
        raise rate_limited(wait)
    now = clock.now()
    try:
        with engine_of(request).begin() as conn:
            body = export.build(conn, caller.human_id, now)
    except BaseException:
        EXPORTS.release(caller.human_id, mark)  # no document, no attempt spent
        raise
    name = export.filename(body["account"]["handle"], now)
    return JSONResponse(
        body,
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "no-store",
        },
    )
