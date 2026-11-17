"""The instance admin's limits for one project or one human account (docs/api.md §16.5.1).

On a project: the ceilings of its four values (§6.31) and its attachment storage. On an
account: the ceilings of the same four values for the projects the human owns (`max_instances`
for the agent profiles the human owns) and the account values of §16.5. Each is a whole
number within its range, `unlimited`, or `null`, which removes the override. One row per
value set (`limit_override`); no row is the instance's value or the default ceiling.

`max_starred_per_human` is not here: the hub has no stars yet.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, delete, insert, select

from maity_hub import ceilings, clock, limits
from maity_hub import tables as t
from maity_hub.config import Settings
from maity_hub.errors import invalid
from maity_hub.views import ts

UNLIMITED = ceilings.UNLIMITED
# The lowest value of each of the four (§6.31): a project may hold no placement and let no
# member bring an agent, but a claim limit and an instance limit start at 1.
LOWEST = {"max_placements": 0, "member_agents_max": 0, "max_open_claims": 1, "max_instances": 1}
ACCOUNT_VALUES = ("max_agents_per_human", "max_orgs_per_human", "max_projects_per_owner")
RANGES: dict[str, tuple[int, int]] = {
    **{name: (LOWEST[name], ceilings.BOUND) for name in ceilings.VALUES},
    limits.PROJECT_STORAGE: (1024**2, 1024**5),
    **{name: (1, 10000) for name in ACCOUNT_VALUES},
}
ON_PROJECT = (*ceilings.VALUES, limits.PROJECT_STORAGE)
ON_ACCOUNT = (*ceilings.VALUES, *ACCOUNT_VALUES)


def _valid(name: str, value: object) -> bool:
    if value == UNLIMITED:
        return True
    low, high = RANGES[name]
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def patch(
    conn: Connection,
    body: dict[str, Any],
    by: str,
    *,
    project_id: str | None = None,
    human_id: str | None = None,
) -> None:
    """All of the body or nothing; `invalid` names each refused field. `null` removes the
    override, and a body names only the fields it changes."""
    names = ON_PROJECT if project_id is not None else ON_ACCOUNT
    errors: dict[str, str] = {}
    for name, value in body.items():
        if name not in names:
            errors[name] = "extra_forbidden"
        elif value is not None and not _valid(name, value):
            errors[name] = "out_of_range"
    if errors:
        raise invalid(errors)
    lo = t.limit_override.c
    target = lo.project_id == project_id if project_id is not None else lo.human_id == human_id
    for name, value in body.items():
        conn.execute(delete(t.limit_override).where(target, lo.name == name))
        if value is None:
            continue
        conn.execute(
            insert(t.limit_override).values(
                project_id=project_id,
                human_id=human_id,
                name=name,
                value=value,
                updated_at=clock.now(),
                updated_by=by,
            )
        )


def _rows(conn: Connection, *, project_id: str | None, human_id: str | None) -> dict[str, Any]:
    lo = t.limit_override.c
    target = lo.project_id == project_id if project_id is not None else lo.human_id == human_id
    return {row.name: row for row in conn.execute(select(t.limit_override).where(target))}


def _by(conn: Connection, human_id: str | None) -> dict[str, Any] | None:
    if human_id is None:
        return None
    handle = conn.execute(select(t.human.c.handle).where(t.human.c.id == human_id)).scalar()
    return {"kind": "human", "id": human_id, "handle": handle}


def _field(conn: Connection, row: Any, value: object, source: str) -> dict[str, Any]:
    return {
        "override": None if row is None else row.value,
        "value": value,
        "source": source,
        "updated_by": None if row is None else _by(conn, row.updated_by),
        "updated_at": None if row is None else ts(row.updated_at),
    }


def project_view(conn: Connection, hub: Settings, project: Any) -> dict[str, Any]:
    """`GET /admin/projects/{owner}/{slug}/limits`: each field as `{override, value, source,
    updated_by, updated_at}`. `max_instances` has no single account here: its value is the
    project override's or the default ceiling."""
    rows = _rows(conn, project_id=project.id, human_id=None)
    view: dict[str, Any] = {}
    for name in ceilings.VALUES:
        if name == "max_instances" and name not in rows:
            cap = ceilings.Ceiling(ceilings.DEFAULT_CEILINGS[name], "default")
        else:
            cap = ceilings.ceiling(conn, name, project)
        view[name] = _field(conn, rows.get(name), cap.value, cap.source)
    storage = rows.get(limits.PROJECT_STORAGE)
    if storage is not None:
        view[limits.PROJECT_STORAGE] = _field(conn, storage, storage.value, "project_override")
    else:
        value, source = limits.resolve(conn, hub)[limits.PROJECT_STORAGE]
        view[limits.PROJECT_STORAGE] = _field(conn, None, value, source)
    return view


def account_view(conn: Connection, hub: Settings, human_id: str) -> dict[str, Any]:
    """`GET /admin/users/{id}/limits`: the same fields for one account."""
    rows = _rows(conn, project_id=None, human_id=human_id)
    view: dict[str, Any] = {}
    for name in ceilings.VALUES:
        row = rows.get(name)
        if row is None:
            view[name] = _field(conn, None, ceilings.DEFAULT_CEILINGS[name], "default")
        else:
            value = ceilings.BOUND if row.value == UNLIMITED else row.value
            view[name] = _field(conn, row, value, "account_override")
    instance = limits.resolve(conn, hub)
    for name in ACCOUNT_VALUES:
        row = rows.get(name)
        if row is None:
            value, source = instance[name]
            view[name] = _field(conn, None, value, source)
        else:
            view[name] = _field(conn, row, row.value, "account_override")
    return view
