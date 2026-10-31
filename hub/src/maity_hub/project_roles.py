"""A project's own roles (docs/api.md §2.3 "Project roles").

A project role grants exactly the scopes of its base, a built-in role. The membership
keeps the base next to the role (`role_base`), so every reader of scopes and tokens takes
it from the row; only a role's assignment and the role list itself look the roles up.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import Connection, case, select, update

from maity_hub import tables as t
from maity_hub.scopes import BASES, ROLES

LIMIT = 12
NAME = re.compile(r"[a-z][a-z0-9-]{1,23}", re.ASCII)
# Built-in trusts and tokens a project role may not be named (§2.3); the built-in roles
# are refused as well.
RESERVED = ("owner", "admin", "member", "guest", "team", "all", "proxy", "lead", "null", "none")
DESCRIPTION_MAX = 200
GUIDE_MAX = 500


def of(project: Any) -> list[dict[str, Any]]:
    """The project's roles as stored, in the order they were put."""
    roles: list[dict[str, Any]] = project.roles or []
    return roles


def names(project: Any) -> list[str]:
    return [role["name"] for role in of(project)]


def base_of(project: Any, role: str) -> str | None:
    """The built-in role whose scopes `role` has: itself for a built-in role, the base of
    a project role, None for a name this project does not have."""
    if role in ROLES:
        return role
    return next((r["base"] for r in of(project) if r["name"] == role), None)


def on_base(project: Any, base: str) -> list[str]:
    """The project roles built on `base`."""
    return [r["name"] for r in of(project) if r["base"] == base]


def view(project: Any) -> dict[str, Any]:
    """`GET …/roles`: `{custom: [{name, base, description, guide, guide_by}]}`."""
    return {"custom": of(project)}


def parse(raw: Any) -> list[dict[str, Any]]:
    """The `custom` list of a `PUT …/roles`, checked; `invalid` names every bad field as
    `custom[<i>].<field>`."""
    from maity_hub.errors import invalid

    if not isinstance(raw, list):
        raise invalid({"custom": "not_a_list"})
    if len(raw) > LIMIT:
        raise invalid({"custom": "too_many"})
    errors: dict[str, str] = {}
    seen: set[str] = set()
    parsed: list[dict[str, Any]] = []
    for i, item in enumerate(raw):
        at = f"custom[{i}]"
        if not isinstance(item, dict):
            errors[at] = "not_an_object"
            continue
        for key in item:
            if key not in ("name", "base", "description", "guide"):
                errors[f"{at}.{key}"] = "unknown_field"
        name, base = item.get("name"), item.get("base")
        description, guide = item.get("description", ""), item.get("guide", "")
        if not isinstance(name, str) or not NAME.fullmatch(name):
            errors[f"{at}.name"] = "format"
        elif name in ROLES or name in RESERVED:
            errors[f"{at}.name"] = "reserved"
        elif name in seen:
            errors[f"{at}.name"] = "duplicate"
        else:
            seen.add(name)
        if base not in BASES:
            errors[f"{at}.base"] = "unknown"
        if not isinstance(description, str) or len(description) > DESCRIPTION_MAX:
            errors[f"{at}.description"] = "too_long" if isinstance(description, str) else "format"
        if not isinstance(guide, str) or len(guide) > GUIDE_MAX:
            errors[f"{at}.guide"] = "too_long" if isinstance(guide, str) else "format"
        parsed.append({"name": name, "base": base, "description": description, "guide": guide})
    if errors:
        raise invalid(errors)
    return parsed


def uses(conn: Connection, project: Any, name: str) -> list[str]:
    """What still names the project role `name` (§2.3 `role_in_use`): a membership, an
    open join or invitation, an open request's `to`, a placement that has not made its
    membership yet, the onboarding's `check_in_with`, an entry in a `substitutes` list,
    or live role memory. A card's `needs` is not in the hub yet; its pull request
    adds it here."""
    from maity_hub import clock

    found: list[str] = []
    now = clock.now()
    if conn.execute(
        select(t.membership.c.id).where(
            t.membership.c.project_id == project.id,
            t.membership.c.active.is_(True),
            t.membership.c.role == name,
        )
    ).first():
        found.append("membership")
    if conn.execute(
        select(t.join_link.c.id).where(
            t.join_link.c.project_id == project.id,
            t.join_link.c.role == name,
            t.join_link.c.used_at.is_(None),
            t.join_link.c.burned_at.is_(None),
            t.join_link.c.revoked_at.is_(None),
            t.join_link.c.expires_at > now,
        )
    ).first():
        found.append("join")
    if conn.execute(
        select(t.invitation.c.id).where(
            t.invitation.c.project_id == project.id,
            t.invitation.c.role == name,
            t.invitation.c.used_at.is_(None),
            t.invitation.c.revoked_at.is_(None),
            t.invitation.c.voided_at.is_(None),
            t.invitation.c.expires_at > now,
        )
    ).first():
        found.append("invitation")
    if conn.execute(
        select(t.request.c.id).where(
            t.request.c.project_id == project.id,
            t.request.c.to_kind == "role",
            t.request.c.to_role == f"role:{name}",
            t.request.c.status == "open",
        )
    ).first():
        found.append("request")
    placements = conn.execute(
        select(t.placement.c.new_profile).where(
            t.placement.c.project_id == project.id,
            t.placement.c.membership_id.is_(None),
            t.placement.c.closed_at.is_(None),
        )
    ).scalars()
    if any((profile or {}).get("role") == name for profile in placements):
        found.append("placement")
    onboarding = (project.settings or {}).get("onboarding") or {}
    if onboarding.get("check_in_with") == f"role:{name}":
        found.append("check_in_with")
    policies = conn.execute(
        select(t.membership.c.availability_policy).where(
            t.membership.c.project_id == project.id, t.membership.c.active.is_(True)
        )
    ).scalars()
    if any(f"role:{name}" in (policy or {}).get("substitutes", []) for policy in policies):
        found.append("substitutes")
    if conn.execute(
        select(t.memory_entry.c.id).where(
            t.memory_entry.c.project_id == project.id,
            t.memory_entry.c.store == "role",
            t.memory_entry.c.role == name,
            t.memory_entry.c.deleted_at.is_(None),
        )
    ).first():
        found.append("memory")
    return found


def rebase(conn: Connection, project: Any, new: list[dict[str, Any]]) -> None:
    """The memberships of a role whose base a `PUT` changed take the new base, in the
    same transaction (§2.3)."""
    old = {r["name"]: r["base"] for r in of(project)}
    moved = [r for r in new if r["name"] in old and old[r["name"]] != r["base"]]
    if not moved:
        return
    conn.execute(
        update(t.membership)
        .where(
            t.membership.c.project_id == project.id,
            t.membership.c.role.in_([r["name"] for r in moved]),
        )
        .values(role_base=_case(moved))
    )


def _case(moved: list[dict[str, Any]]) -> Any:
    return case(*((t.membership.c.role == r["name"], r["base"]) for r in moved))
