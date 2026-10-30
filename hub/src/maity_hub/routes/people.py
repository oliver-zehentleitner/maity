"""`GET /people/{handle}` (docs/api.md §6.27): a person or an organisation as the dashboard shows
them to a signed-in human.

One answer for every case the caller may not see: an unknown name, an agent's handle, a deleted,
suspended or pending account, a deleted organisation, and a person or an organisation that shows
the caller nothing. The endpoint does not tell which (§6.26). It reads and changes nothing else.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, and_, false, or_, select

from maity_hub import avatars, moderation, namespace, orgs, person_links, public_people
from maity_hub import tables as t
from maity_hub.deps import AnyCaller, engine_of, settings_of
from maity_hub.errors import forbidden, humans_only, not_found

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


def _avatar(conn: Connection, caller: Any, owner_id: str) -> str | None:
    """The image's address only where the caller may read it (§6.10), else None."""
    if not avatars.may_read(conn, caller, owner_id):
        return None
    return avatars.urls(conn, [owner_id])[owner_id]


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
    listed = _listed(conn, ids, mine)
    page_served = public_people.served(conn, human) and _served(
        conn, request, public_people.KIND, human.id
    )
    links = _links(conn, human, me)
    if not own and not page_served and not listed["projects_total"] and not links:
        raise not_found()  # shows the caller nothing
    answer: dict[str, Any] = {
        "kind": "human",
        "handle": human.handle,
        "display_name": human.display_name,
        "avatar_url": _avatar(conn, caller, human.id),
        "page_served": page_served,
    }
    if own or page_served:
        answer["public_bio"] = human.public_bio
    return {**answer, **links, **listed}


def _links(conn: Connection, human: Any, me: str) -> dict[str, Any]:
    """`website` and `social` where `links_visible` admits the caller (§16.9), as the member
    views show them; nothing when the person has no link. A hold on the profile (§16.8) makes
    `everyone` count as `colleagues`."""
    if not human.website and not human.social:
        return {}
    visible = human.links_visible
    if visible == "everyone" and moderation.hold(conn, "profile", human.id) is not None:
        visible = "colleagues"
    seen = person_links.admitted(conn, {human.id: visible}, person_links.Reader(me))
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
        "avatar_url": _avatar(conn, caller, org.id),
        "page_served": page_served,
        **listed,
    }
    if role is not None:
        answer["members"] = [
            {
                "handle": member["handle"],
                "display_name": member["display_name"],
                "avatar_url": (
                    member["avatar_url"] if avatars.may_read(conn, caller, member["id"]) else None
                ),
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
