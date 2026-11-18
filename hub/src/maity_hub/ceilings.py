"""The ceilings of a project's limits and the quota details (docs/api.md §6.31, §16.5.1).

Four values limit what a project may hold, each set inside the project: `max_placements`,
`member_agents_max`, `max_open_claims` and an agent membership's `max_instances`. Each is set
at most up to its ceiling: the instance admin's override on the project, else the override
on an account (the agent profile owner's for `max_instances`, the project owner's for the
three others; a project in an organisation's namespace has no owner's account), else the
default ceiling, the product bound as it was before ceilings. `unlimited` lifts the ceiling
to the hub's bound of 1000 (`BOUND`), never past it: the lists that carry these things are
read in one answer without pages.

The value in effect is the stored value, or the ceiling when that is lower. A ceiling lowered
below a stored value keeps the stored value and ends nothing that exists; only new things
are refused. Without an override nothing changes for anybody: the default ceilings are the
bounds the hub had before.

`max_open_claims` has no field and no check yet (tsk-ybc2ma72dzvq): only its override is
stored here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, select

from maity_hub import tables as t

BOUND = 1000
UNLIMITED = "unlimited"
DEFAULT_CEILINGS = {
    "max_placements": 1000,
    "member_agents_max": 20,
    "max_open_claims": 1000,
    "max_instances": 16,
}
VALUES = tuple(DEFAULT_CEILINGS)
# The value a project or a membership has while nobody set it (§6.1, §6.18): `source`
# says `default` for it.
UNSET = {"max_placements": 8, "member_agents_max": 3, "max_instances": 1}


@dataclass(frozen=True)
class Ceiling:
    value: int
    source: str  # `default`, `project_override` or `account_override`


@dataclass(frozen=True)
class Limit:
    name: str
    limit: int
    source: str  # `default`, `project`, `agent_owner` or `ceiling`
    ceiling: Ceiling
    stored: int


def stored_override(
    conn: Connection, name: str, *, project_id: str | None = None, human_id: str | None = None
) -> Any:
    """The override row for `name` on the project or on the account, or None."""
    lo = t.limit_override.c
    where = lo.project_id == project_id if project_id is not None else lo.human_id == human_id
    return conn.execute(select(t.limit_override).where(where, lo.name == name)).first()


def _number(value: object) -> int:
    return BOUND if value == UNLIMITED else int(value)  # type: ignore[call-overload]


def account_of(project: Any, name: str, agent_owner_id: str | None) -> str | None:
    """The account whose override applies: the agent profile owner's for `max_instances`,
    the project owner's for the others, none for a project in an organisation's namespace."""
    if name == "max_instances":
        return agent_owner_id
    owner = str(project.owner_id)
    return owner if owner.startswith("hum-") else None


def ceiling(
    conn: Connection, name: str, project: Any, agent_owner_id: str | None = None
) -> Ceiling:
    """The ceiling in effect for `name` in `project`, first to last: the override on the
    project, the override on the account (`account_of`), the default ceiling."""
    row = stored_override(conn, name, project_id=project.id)
    if row is not None:
        return Ceiling(_number(row.value), "project_override")
    account = account_of(project, name, agent_owner_id)
    if account is not None:
        row = stored_override(conn, name, human_id=account)
        if row is not None:
            return Ceiling(_number(row.value), "account_override")
    return Ceiling(DEFAULT_CEILINGS[name], "default")


def resolve(
    conn: Connection, name: str, project: Any, stored: int, agent_owner_id: str | None = None
) -> Limit:
    """The value in effect: `stored`, or the ceiling when that is lower (`source:
    "ceiling"`)."""
    cap = ceiling(conn, name, project, agent_owner_id)
    if stored > cap.value:
        return Limit(name, cap.value, "ceiling", cap, stored)
    if stored == UNSET.get(name):
        source = "default"
    else:
        source = "agent_owner" if name == "max_instances" else "project"
    return Limit(name, stored, source, cap, stored)


def setter(name: str) -> str:
    """The right that sets the value within its ceiling."""
    return "agent_owner" if name == "max_instances" else "project:admin"


def raise_of(limit: Limit, project: str, member_id: str | None = None) -> dict[str, Any] | None:
    """`raise` (§6.31): who can lift `limit.limit` and where, for the project of the full
    name `project` (`<owner>/<slug>`); None at the hub's bound."""
    if limit.limit >= BOUND:
        return None
    if limit.limit >= limit.ceiling.value:
        return {
            "right": "instance:admin",
            "path": f"/api/v1/admin/projects/{project}/limits",
            "field": limit.name,
        }
    if limit.name == "max_instances":
        return {
            "right": "agent_owner",
            "path": f"/api/v1/projects/{project}/members/{member_id}",
            "field": "team.max_instances",
        }
    return {
        "right": "project:admin",
        "path": f"/api/v1/projects/{project}",
        "field": f"policy.{limit.name}",
    }


def ceiling_view(limit: Limit, sees_value: bool) -> dict[str, Any]:
    """`ceiling`: its `value` only to a caller who holds the right that sets the value."""
    view: dict[str, Any] = {"source": limit.ceiling.source}
    if sees_value:
        view = {"value": limit.ceiling.value, **view}
    return view


def details(
    limit: Limit,
    count: int,
    project: str,
    *,
    sees_ceiling: bool,
    member_id: str | None = None,
) -> dict[str, Any]:
    """The quota details of a refusal by `limit` (§6.31). `member_id` puts the refusal in
    the scope of one membership (`member_agents_max`, `max_instances`), else the project."""
    scope: dict[str, Any] = (
        {"scope": "member", "member": member_id}
        if member_id is not None
        else {"scope": "project", "project": project}
    )
    return {
        "name": limit.name,
        "limit": limit.limit,
        "count": count,
        "max": limit.limit,
        **scope,
        "source": limit.source,
        "ceiling": ceiling_view(limit, sees_ceiling),
        "raise": raise_of(limit, project, member_id),
    }


def above_ceiling(field: str, cap: Ceiling) -> Any:
    """`invalid` for a value set above its ceiling (§6.31)."""
    from maity_hub.errors import ApiError

    return ApiError(
        400,
        "invalid",
        "the value is above its ceiling",
        {"fields": {field: "above_ceiling"}, "ceiling": cap.value},
    )
