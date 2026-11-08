"""`GET /people/{handle}` (docs/api.md §6.27): a person or an organisation as the dashboard shows
them to a signed-in human. And a human's contacts (§6.29): `PUT` and `DELETE
/people/{handle}/contact`, `GET /me/contacts` and `GET /me/contact-of`.

One answer for every case the caller may not see: an unknown name, an agent's handle, a deleted,
suspended or pending account, a deleted organisation, and a person or an organisation that shows
the caller nothing. The endpoint does not tell which (§6.26). It reads and changes nothing else.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, and_, false, or_, select

from maity_hub import (
    avatars,
    contacts,
    handles,
    moderation,
    namespace,
    orgs,
    paging,
    person_links,
    public_people,
)
from maity_hub import tables as t
from maity_hub.deps import AnyCaller, engine_of, settings_of
from maity_hub.errors import ApiError, forbidden, humans_only, invalid, not_found, rate_limited
from maity_hub.views import ts

router = APIRouter()

PROJECTS_SHOWN = 100
CACHE = "private, no-store"


def _caller(caller: AnyCaller) -> str:
    if caller.kind == "agent":
        raise humans_only("an agent is bound to one project and never reads a person's page")
    if caller.kind != "human" or caller.human_id is None:
        raise forbidden()
    return caller.human_id


def _served(conn: Connection, request: Request, kind: str, target_id: str) -> bool:
    """Whether the hub serves the public page of `target_id` now (§16.9): public pages on, and
    the page in the store, which holds it exactly while its inputs say it is public."""
    if not settings_of(request).public_pages:
        return False
    return (
        conn.execute(
            select(t.public_page.c.path).where(
                t.public_page.c.kind == kind, t.public_page.c.target_id == target_id
            )
        ).first()
        is not None
    )


def _my_projects(conn: Connection, human_id: str) -> set[str]:
    m = t.membership.c
    return set(
        conn.execute(
            select(m.project_id).where(m.human_id == human_id, m.active.is_(True))
        ).scalars()
    )


def _served_project(request: Request, column: Any) -> Any:
    """The condition that the project `column` names has a public page the hub serves now."""
    if not settings_of(request).public_pages:
        return false()
    p = t.public_page.c
    return column.in_(select(p.target_id).where(p.kind == "project"))


def _listed(conn: Connection, ids: set[str], mine: set[str]) -> dict[str, Any]:
    """`projects` and `projects_total` (§6.27): each once, `shared` where the caller is a member,
    archived ones only where the caller is a member, ordered by full name, at most 100."""
    if not ids:
        return {"projects": [], "projects_total": 0}
    rows = conn.execute(
        select(t.project.c.id, t.project.c.name, t.project.c.state).where(t.project.c.id.in_(ids))
    ).all()
    kept = [r for r in rows if r.state != "archived" or r.id in mine]
    names = namespace.full_names(conn, [r.id for r in kept])
    items = sorted(
        ({"full_name": names[r.id], "name": r.name, "shared": r.id in mine} for r in kept),
        key=lambda item: item["full_name"],
    )
    return {"projects": items[:PROJECTS_SHOWN], "projects_total": len(items)}


def _avatar(conn: Connection, request: Request, caller: Any, owner_id: str) -> str | None:
    """The image's address where the caller may read it (§6.10); else, for a public picture,
    its public address, which names no account; else None."""
    if avatars.may_read(conn, caller, owner_id):
        return avatars.urls(conn, [owner_id])[owner_id]
    if avatars.is_public(conn, settings_of(request), owner_id):
        return avatars.public_urls(conn, [owner_id])[owner_id]
    return None


def _person(conn: Connection, request: Request, caller: Any, human: Any) -> dict[str, Any]:
    me = caller.human_id
    own = human.id == me
    mine = _my_projects(conn, me)
    m = t.membership.c
    if own:
        ids = mine
    else:
        theirs = select(m.project_id).where(m.human_id == human.id, m.active.is_(True))
        ids = set(
            conn.execute(
                theirs.where(or_(m.project_id.in_(mine), _served_project(request, m.project_id)))
            ).scalars()
        )
    # With the profile off, the personal details (bio, links, the list of projects) are for
    # members of a shared project only (§16.9); handle and name stay for everyone.
    shared = own or bool(ids & mine)
    chosen = own or bool(human.public_profile)
    if not chosen:
        ids &= mine
    listed = _listed(conn, ids, mine)
    page_served = public_people.served(conn, human) and _served(
        conn, request, public_people.KIND, human.id
    )
    links = _links(conn, human, me) if chosen or shared else {}
    if not own and not page_served and not listed["projects_total"] and not links:
        raise not_found()  # shows the caller nothing
    answer: dict[str, Any] = {
        "kind": "human",
        "handle": human.handle,
        "display_name": human.display_name,
        "avatar_url": _avatar(conn, request, caller, human.id),
        "page_served": page_served,
    }
    if own or (page_served and (chosen or shared)):
        answer["public_bio"] = human.public_bio
    if not own:
        answer["contact"] = contacts.has(conn, me, human.id)  # §6.29
    agents = _agents(conn, caller, human) if page_served else []
    return {**answer, **links, **listed, "agents": agents}


def _agents(conn: Connection, caller: Any, human: Any) -> list[dict[str, Any]]:
    """The agents the person's agents page lists, in its order and by its rule (§6.27, §16.9):
    the caller's own handle answers the same list a visitor sees. A listed agent's picture is
    public (§6.10): `avatar_url` is the image's address where the caller may read it, its
    public address otherwise."""
    listed_agents = public_people.listed_agents(conn, human)
    own = avatars.urls(
        conn, [a.agent.id for a in listed_agents if avatars.may_read(conn, caller, a.agent.id)]
    )
    return [
        {
            "handle": listed.agent.handle,
            "display_name": listed.agent.display_name,
            "avatar_url": own.get(listed.agent.id) or listed.picture,
            "page": listed.page,
            "roles": listed.roles,
            "model": listed.model,
            "harness": listed.harness,
        }
        for listed in listed_agents
    ]


def _links(conn: Connection, human: Any, me: str) -> dict[str, Any]:
    """`website` and `social` where `links_visible` admits the caller (§16.9), as the member
    views show them, the hold rule included (§16.8); nothing when the person has no link."""
    if not human.website and not human.social:
        return {}
    held = {human.id} if moderation.hold(conn, "profile", human.id) is not None else None
    seen = person_links.admitted(
        conn, {human.id: human.links_visible}, person_links.Reader(me), held=held
    )
    return person_links.shown(human) if human.id in seen else {}


def _organisation(conn: Connection, request: Request, caller: Any, org: Any) -> dict[str, Any]:
    me = caller.human_id
    role = orgs.role_of(conn, org.id, me)
    mine = _my_projects(conn, me)
    p = t.project.c
    ids = set(
        conn.execute(
            select(p.id).where(
                p.owner_org_id == org.id,
                or_(p.id.in_(mine), _served_project(request, p.id)),
            )
        ).scalars()
    )
    listed = _listed(conn, ids, mine)
    page_served = moderation.hold(conn, "org", org.id) is None and _served(
        conn, request, "organisation", org.id
    )
    if role is None and not page_served and not listed["projects_total"]:
        raise not_found()  # not a member, and it shows the caller nothing
    answer: dict[str, Any] = {
        "kind": "organisation",
        "handle": org.handle,
        "display_name": org.display_name,
        "avatar_url": _avatar(conn, request, caller, org.id),
        "page_served": page_served,
        **listed,
    }
    if role is not None:
        answer["members"] = [
            {
                "handle": member["handle"],
                "display_name": member["display_name"],
                "avatar_url": _avatar(conn, request, caller, member["id"]),
                "role": member["role"],
            }
            for member in orgs.members(conn, org.id)
        ]
    return answer


@router.get("/people/{handle}")
def get_person(handle: str, request: Request, caller: AnyCaller) -> JSONResponse:
    _caller(caller)
    with engine_of(request).connect() as conn:
        owner_id = namespace.resolve_owner(conn, handle)
        if owner_id is None:
            raise not_found()
        human = conn.execute(select(t.human).where(t.human.c.id == owner_id)).first()
        if human is not None:
            if (
                human.deleted_at is not None
                or human.suspended_at is not None
                or human.account_status != "active"
            ):
                raise not_found()
            answer = _person(conn, request, caller, human)
        else:
            org = conn.execute(
                select(t.org).where(and_(t.org.c.id == owner_id, t.org.c.deleted_at.is_(None)))
            ).first()
            if org is None:
                raise not_found()
            answer = _organisation(conn, request, caller, org)
    return JSONResponse(answer, headers={"Cache-Control": CACHE})


# --- contacts (§6.29) ---------------------------------------------------------------------------


def _contact_target(conn: Connection, me: str, handle: str, *, active: bool) -> str:
    """The human `handle` names (a live alias too, §6.24). `active`: an approved, active
    account only, as `GET /people` answers (§6.27); else any account not deleted, so that a
    contact can always be removed. An organisation is `not_a_person`, the caller `self`."""
    human_id = handles.human_id_of(conn, handle)
    if human_id is None:
        if handles.org_id_of(conn, handle) is not None:
            raise ApiError(
                400, "invalid", "only a person can be a contact", {"reason": "not_a_person"}
            )
        raise not_found()
    human = conn.execute(select(t.human).where(t.human.c.id == human_id)).first()
    if human is None or human.deleted_at is not None:
        raise not_found()
    if active and (human.suspended_at is not None or human.account_status != "active"):
        raise not_found()
    if human_id == me:
        raise ApiError(400, "invalid", "you cannot be your own contact", {"reason": "self"})
    return human_id


@router.put("/people/{handle}/contact")
def add_contact(handle: str, request: Request, caller: AnyCaller) -> Response:
    me = _caller(caller)
    mark = None
    try:
        with engine_of(request).begin() as conn:
            contact_id = _contact_target(conn, me, handle, active=True)
            if contacts.has(conn, me, contact_id):
                return Response(status_code=204)  # not counted
            wait, mark = contacts.ADDED.place(me)
            if wait:
                raise rate_limited(wait)
            if not contacts.add(conn, me, contact_id):
                contacts.ADDED.release(me, mark)  # a concurrent call added it
                mark = None
    except BaseException:
        contacts.ADDED.release(me, mark)  # nothing added, no attempt spent
        raise
    return Response(status_code=204)


@router.delete("/people/{handle}/contact")
def remove_contact(handle: str, request: Request, caller: AnyCaller) -> Response:
    me = _caller(caller)
    with engine_of(request).begin() as conn:
        contacts.remove(conn, me, _contact_target(conn, me, handle, active=False))
    return Response(status_code=204)


def _contact_list(request: Request, caller: AnyCaller, side: str) -> JSONResponse:
    me = _caller(caller)
    limit_raw = request.query_params.get("limit", "50")
    if not limit_raw.isdigit() or not 1 <= int(limit_raw) <= 200:
        raise invalid({"limit": "out_of_range"})
    limit = int(limit_raw)
    bound = paging.scope(list=side)
    cursor = request.query_params.get("cursor")
    with engine_of(request).connect() as conn:
        after = paging.uncursor(cursor, bound) if cursor is not None else None
        rows = contacts.page(conn, me, side, limit, after)
        page = rows[:limit]
        items = [
            {
                "handle": row.handle,
                "display_name": row.display_name,
                "avatar_url": _avatar(conn, request, caller, row.other_id),
                "since": ts(row.since),
            }
            for row in page
        ]
    next_cursor = (
        paging.cursor(page[-1].since, page[-1].other_id, bound) if len(rows) > limit else None
    )
    return JSONResponse(
        {"items": items, "next_cursor": next_cursor}, headers={"Cache-Control": CACHE}
    )


@router.get("/me/contacts")
def my_contacts(request: Request, caller: AnyCaller) -> JSONResponse:
    """The caller's contacts: the people who may contact the caller."""
    return _contact_list(request, caller, contacts.CONTACTS)


@router.get("/me/contact-of")
def contact_of(request: Request, caller: AnyCaller) -> JSONResponse:
    """The people who have the caller as a contact: whom the caller may contact."""
    return _contact_list(request, caller, contacts.CONTACT_OF)
