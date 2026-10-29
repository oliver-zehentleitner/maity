"""Organisations (docs/api.md §6.26): the second kind of namespace owner, a team of humans.

This module is the organisation and its members: the rows, the role rules and the views.
The routes are `routes.orgs`. What an organisation does to the projects it owns (its owners'
hub-kept memberships, transfers) is built on top of this in later changes.

Every change that can alter who owns an organisation runs under the lock on its row
(`lock`), held until commit: two owners who demote each other at once leave one owner.
The row is always locked before any project's, and a human's row (for the count of an
owner's organisations) before an organisation's.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import Connection, delete, func, insert, select, update

from maity_hub import avatars, clock, handle_register, namespace
from maity_hub import tables as t
from maity_hub.errors import ApiError, invalid, not_found
from maity_hub.ids import new_id
from maity_hub.models import HANDLE_PATTERN
from maity_hub.views import ts

ROLES = ("owner", "admin", "member")
PUBLIC_PAGE = ("off", "on")
DISPLAY_NAME_MAX = 64
_HANDLE = re.compile(HANDLE_PATTERN)


# --- errors --------------------------------------------------------------------------------


def org_role() -> ApiError:
    """The caller is a member, but its role does not allow the call (§6.26)."""
    return ApiError(
        403, "forbidden", "the role in the organisation does not allow this", {"reason": "org_role"}
    )


def last_owner(handle: str) -> ApiError:
    return ApiError(
        409,
        "org_last_owner",
        "an organisation keeps at least one owner",
        {"orgs": [handle]},
    )


def org_limit(limit: int, count: int) -> ApiError:
    return ApiError(
        409,
        "org_limit",
        "the human owns as many organisations as allowed",
        {"limit": limit, "count": count},
    )


# --- reading -------------------------------------------------------------------------------


def lock(conn: Connection, org_id: str) -> Any:
    """`SELECT … FOR UPDATE` on the organisation's row, returned as it is now (None for an
    id that names nothing, or an organisation deleted meanwhile)."""
    return conn.execute(
        select(t.org).where(t.org.c.id == org_id, t.org.c.deleted_at.is_(None)).with_for_update()
    ).first()


def find(conn: Connection, human_id: str, handle: str) -> tuple[Any, str]:
    """The organisation `handle` names and the caller's role in it; `not_found` for a
    handle that names none, and for one the caller is not a member of: the routes tell
    nobody which organisations exist (§6.26)."""
    row = conn.execute(
        select(t.org, t.org_member.c.role)
        .join(t.org_member, t.org_member.c.org_id == t.org.c.id)
        .where(
            t.org.c.handle == handle,
            t.org.c.deleted_at.is_(None),
            t.org_member.c.human_id == human_id,
        )
    ).first()
    if row is None:
        raise not_found()
    return row, str(row.role)


def view(conn: Connection, org: Any, role: str) -> dict[str, Any]:
    return {
        "id": org.id,
        "handle": org.handle,
        "display_name": org.display_name,
        "avatar_url": avatars.urls(conn, [org.id])[org.id],
        "aliases": [],
        "created_at": ts(org.created_at),
        "my_role": role,
        "members_create_projects": bool(org.members_create_projects),
        "public_page": org.public_page,
    }


def mine(conn: Connection, human_id: str) -> list[dict[str, Any]]:
    """The organisations the human is a member of, with its role in each."""
    rows = conn.execute(
        select(t.org, t.org_member.c.role)
        .join(t.org_member, t.org_member.c.org_id == t.org.c.id)
        .where(t.org_member.c.human_id == human_id, t.org.c.deleted_at.is_(None))
        .order_by(t.org.c.created_at, t.org.c.id)
    ).all()
    return [view(conn, r, r.role) for r in rows]


def members(conn: Connection, org_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        select(
            t.human.c.id,
            t.human.c.handle,
            t.human.c.display_name,
            t.org_member.c.role,
            t.org_member.c.joined_at,
        )
        .join(t.human, t.human.c.id == t.org_member.c.human_id)
        .where(t.org_member.c.org_id == org_id)
        .order_by(t.org_member.c.joined_at, t.human.c.id)
    ).all()
    urls = avatars.urls(conn, [r.id for r in rows])
    return [
        {
            "id": r.id,
            "handle": r.handle,
            "display_name": r.display_name,
            "avatar_url": urls[r.id],
            "role": r.role,
            "joined_at": ts(r.joined_at),
        }
        for r in rows
    ]


def role_of(conn: Connection, org_id: str, human_id: str) -> str | None:
    found = conn.execute(
        select(t.org_member.c.role).where(
            t.org_member.c.org_id == org_id, t.org_member.c.human_id == human_id
        )
    ).scalar()
    return str(found) if found is not None else None


def owners_count(conn: Connection, org_id: str) -> int:
    return int(
        conn.execute(
            select(func.count())
            .select_from(t.org_member)
            .where(t.org_member.c.org_id == org_id, t.org_member.c.role == "owner")
        ).scalar_one()
    )


def owned_alone(conn: Connection, human_id: str) -> list[str]:
    """The handles of the organisations in which the human is the only owner: what their
    account's deletion would leave without one (§2.9, §6.26)."""
    owners = (
        select(t.org_member.c.org_id)
        .where(t.org_member.c.role == "owner")
        .group_by(t.org_member.c.org_id)
        .having(func.count() == 1)
        .subquery()
    )
    return list(
        conn.execute(
            select(t.org.c.handle)
            .join(t.org_member, t.org_member.c.org_id == t.org.c.id)
            .join(owners, owners.c.org_id == t.org.c.id)
            .where(
                t.org_member.c.human_id == human_id,
                t.org_member.c.role == "owner",
                t.org.c.deleted_at.is_(None),
            )
            .order_by(t.org.c.handle)
        ).scalars()
    )


def lock_all_of(conn: Connection, human_id: str) -> None:
    """The rows of every organisation the human belongs to, in the order of their ids: the
    deletion of an account locks them all (§6.26, "One organisation, one lock")."""
    ids = conn.execute(
        select(t.org_member.c.org_id)
        .where(t.org_member.c.human_id == human_id)
        .order_by(t.org_member.c.org_id)
    ).scalars()
    for org_id in list(ids):
        lock(conn, org_id)


# --- creating and changing -----------------------------------------------------------------


def display_name_ok(display_name: str) -> bool:
    """1–64 characters and no control character, as §2.7.4."""
    return 1 <= len(display_name) <= DISPLAY_NAME_MAX and not any(
        ord(c) < 32 or ord(c) == 127 for c in display_name
    )


def create(
    conn: Connection, human_id: str, handle: str, display_name: str, limit: int | None
) -> tuple[Any, str]:
    """The organisation, with the caller as its first owner. The human's row is locked for
    the count, so two creations at `limit − 1` give one organisation and one `org_limit`."""
    errors: dict[str, str] = {}
    if not _HANDLE.fullmatch(handle):
        errors["handle"] = "invalid"
    elif handle in namespace.DASHBOARD_WORDS:
        errors["handle"] = "reserved"
    if not display_name_ok(display_name):
        errors["display_name"] = "invalid"
    if errors:
        raise invalid(errors)
    conn.execute(select(t.human.c.id).where(t.human.c.id == human_id).with_for_update())
    if limit is not None:
        owned = int(
            conn.execute(
                select(func.count())
                .select_from(t.org_member)
                .join(t.org, t.org.c.id == t.org_member.c.org_id)
                .where(
                    t.org_member.c.human_id == human_id,
                    t.org_member.c.role == "owner",
                    t.org.c.deleted_at.is_(None),
                )
            ).scalar_one()
        )
        if owned >= limit:
            raise org_limit(limit, owned)
    org_id = new_id("org")
    if not handle_register.claim(conn, handle, handle_register.ORG, org_id):
        raise invalid({"handle": "taken"})
    now = clock.now()
    conn.execute(
        insert(t.org).values(id=org_id, handle=handle, display_name=display_name, created_at=now)
    )
    conn.execute(
        insert(t.org_member).values(org_id=org_id, human_id=human_id, role="owner", joined_at=now)
    )
    org = conn.execute(select(t.org).where(t.org.c.id == org_id)).one()
    return org, "owner"


def change_settings(conn: Connection, org: Any, fields: dict[str, Any]) -> Any:
    """`display_name`, `members_create_projects`, `public_page`, as the owner sent them."""
    values: dict[str, Any] = {}
    nulled = {name: "invalid" for name, value in fields.items() if value is None}
    if nulled:  # a field that is sent is a value: `null` does not mean "leave it"
        raise invalid(nulled)
    if "display_name" in fields:
        if not display_name_ok(fields["display_name"]):
            raise invalid({"display_name": "invalid"})
        values["display_name"] = fields["display_name"]
    if "members_create_projects" in fields:
        values["members_create_projects"] = bool(fields["members_create_projects"])
    if "public_page" in fields:
        if fields["public_page"] not in PUBLIC_PAGE:
            raise invalid({"public_page": "invalid"})
        values["public_page"] = fields["public_page"]
    if values:
        conn.execute(update(t.org).where(t.org.c.id == org.id).values(**values))
    return conn.execute(select(t.org).where(t.org.c.id == org.id)).one()


def set_role(
    conn: Connection, org: Any, actor_role: str, human_id: str, role: str
) -> dict[str, Any]:
    """An owner sets any role of anyone; an admin moves a member or admin between `member`
    and `admin`. The last owner is never demoted (`org_last_owner`)."""
    if role not in ROLES:
        raise invalid({"role": "invalid"})
    current = role_of(conn, org.id, human_id)
    if current is None:
        raise not_found()
    if actor_role == "member":
        raise org_role()
    if actor_role == "admin" and (current == "owner" or role == "owner"):
        raise org_role()
    if current == "owner" and role != "owner" and owners_count(conn, org.id) <= 1:
        raise last_owner(org.handle)
    if current != role:
        from maity_hub import org_invitations, org_projects

        conn.execute(
            update(t.org_member)
            .where(t.org_member.c.org_id == org.id, t.org_member.c.human_id == human_id)
            .values(role=role)
        )
        org_invitations.withdraw_by_inviter(conn, org.id, human_id, role)
        if current != "owner" and role == "owner":  # the hub keeps them owners of its projects
            org_projects.keep_in_all(conn, org.id, human_id)
        elif current == "owner" and role != "owner":
            org_projects.release_in_all(conn, org.id, human_id)
    return next(m for m in members(conn, org.id) if m["id"] == human_id)


def remove_member(
    conn: Connection, org: Any, actor_id: str, actor_role: str, human_id: str
) -> None:
    """An owner removes anyone, an admin a member or admin, everyone leaves for themselves.
    The last owner may neither be removed nor leave (`org_last_owner`)."""
    current = role_of(conn, org.id, human_id)
    if current is None:
        raise not_found()
    if human_id != actor_id and (
        actor_role == "member" or (actor_role == "admin" and current == "owner")
    ):
        raise org_role()
    if current == "owner" and owners_count(conn, org.id) <= 1:
        raise last_owner(org.handle)
    from maity_hub import org_invitations, org_projects

    conn.execute(
        delete(t.org_member).where(
            t.org_member.c.org_id == org.id, t.org_member.c.human_id == human_id
        )
    )
    org_invitations.withdraw_by_inviter(conn, org.id, human_id, None)
    if current == "owner":  # and the memberships the hub kept for them end or fall back
        org_projects.release_in_all(conn, org.id, human_id)


def delete_org(conn: Connection, org: Any, confirm: object) -> None:
    """End the organisation: its members go, and the memberships the hub kept for its owners
    with them, its open invitations are withdrawn, the row stays with `deleted_at` and its
    handle stays taken for good (§6.26). Only while it owns no project that is not archived:
    `namespace_owner`, naming them; an archived one stays archived under its name."""
    from maity_hub import org_invitations, org_projects

    if confirm != org.handle:
        raise invalid({"confirm": "mismatch"})
    open_projects = [p.id for p in org_projects.projects_of(conn, org.id) if p.state != "archived"]
    if open_projects:
        raise ApiError(
            409,
            "namespace_owner",
            "the organisation owns a project that is not archived: transfer or archive it first",
            {"projects": sorted(namespace.full_names(conn, open_projects).values())},
        )
    org_invitations.withdraw_all(conn, org.id, "org_deleted")
    owners = org_projects.owners_of(conn, org.id)
    # The members go first: the `member_updated` of a seat that ends must not say `org_owner`.
    conn.execute(delete(t.org_member).where(t.org_member.c.org_id == org.id))
    for human_id in owners:
        org_projects.release_in_all(conn, org.id, human_id)
    avatars.remove_upload(conn, org.id)  # the avatar goes with the organisation (§6.26)
    conn.execute(update(t.org).where(t.org.c.id == org.id).values(deleted_at=clock.now()))
