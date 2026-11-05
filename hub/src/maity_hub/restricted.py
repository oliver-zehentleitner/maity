"""A card's restricted text and the project's restricted-access set (docs/api.md §6.4
"Restricted text", §6.1 "Restricted access").

The set is resolved on every call from `settings.restricted_access` and the project's
memberships, never stored resolved. Nothing outside this module and `routes/restricted.py`
reads `task_restricted`, so no other read of a card can carry the text."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, func, select

from maity_hub import tables as t

MODES = ("nobody_except", "all_except")
GUEST = "guest"


def access(project: Any) -> dict[str, Any] | None:
    """The stored `restricted_access`, or None: no key or `null` is a closed set (§6.1)."""
    value = (project.settings or {}).get("restricted_access")
    if not isinstance(value, dict) or value.get("mode") not in MODES:
        return None
    return value


def _seated(row: Any) -> bool:
    """An active member with trust above `guest`."""
    return row is not None and row.removed_at is None and row.trust != GUEST


def resolve(conn: Connection, project: Any) -> set[int]:
    """The membership row ids in the project's set now (§6.1 "Who is in the set")."""
    setting = access(project)
    if setting is None:
        return set()
    listed = set(setting.get("members") or [])
    rows = conn.execute(
        select(
            t.membership.c.id,
            t.membership.c.human_id,
            t.membership.c.agent_id,
            t.membership.c.trust,
            t.membership.c.removed_at,
            t.membership.c.isolated_since,
            t.agent_profile.c.owner_id,
        )
        .select_from(t.membership)
        .outerjoin(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
        .where(t.membership.c.project_id == project.id, t.membership.c.removed_at.is_(None))
    ).all()
    humans = {row.human_id: row for row in rows if row.agent_id is None}
    all_except = setting["mode"] == "all_except"

    def named(member_id: str) -> bool:
        return (member_id not in listed) if all_except else (member_id in listed)

    def eligible(row: Any) -> bool:
        return _seated(row) and row.isolated_since is None

    def human_in(row: Any) -> bool:
        return eligible(row) and named(row.human_id)

    found: set[int] = set()
    for row in rows:
        if row.agent_id is None:
            if human_in(row):
                found.add(row.id)
            continue
        owner = humans.get(row.owner_id)
        if not (eligible(row) and _seated(owner) and named(row.agent_id)):
            continue
        # Under `all_except` an agent is in only while its owner is (§6.1); under
        # `nobody_except` it is listed itself and needs no listing of its owner.
        if all_except and not human_in(owner):
            continue
        found.add(row.id)
    return found


def in_set(conn: Connection, project: Any, membership_id: int) -> bool:
    return membership_id in resolve(conn, project)


def cards_with_text(conn: Connection, project_id: str) -> int:
    """How many cards of the project have a restricted text now (§6.1, the quota of §6.4)."""
    count: int = conn.execute(
        select(func.count())
        .select_from(t.task_restricted)
        .where(t.task_restricted.c.project_id == project_id, t.task_restricted.c.text.is_not(None))
    ).scalar_one()
    return count
