"""The caps on what one account may hold (docs/api.md §16.5): agent profiles and organisations
owned, each from the environment, else from the instance admin, else its default, by
`instance_settings.effective`. A value is a whole number from 1 to 10000 or `unlimited`; the
creations the caps gate read the effective value through `of`, and lowering one never
deletes anything.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, func, select

from maity_hub import instance_settings as store
from maity_hub import tables as t
from maity_hub.config import Settings
from maity_hub.errors import ApiError, invalid

UNLIMITED = "unlimited"
DEFAULTS = {"max_agents_per_human": 100, "max_orgs_per_human": 5}
NAMES = tuple(DEFAULTS)
READ_ONLY = ("humans_at_limit", "humans_at_org_limit")


def _check(value: object) -> object | None:
    """The value to store, or None when it is no cap."""
    if value == UNLIMITED:
        return value
    if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 10000:
        return value
    return None


store.register(*(store.Setting(f"limits.{name}", _check, DEFAULTS[name]) for name in NAMES))


def resolve(conn: Connection, hub: Settings) -> dict[str, tuple[Any, str]]:
    stored = store.stored(conn, "limits")
    return {name: store.effective(f"limits.{name}", getattr(hub, name), stored) for name in NAMES}


def of(conn: Connection, hub: Settings, name: str) -> int | None:
    """The cap in force, None for `unlimited`."""
    value = resolve(conn, hub)[name][0]
    return None if value == UNLIMITED else int(value)


def agent_limit(limit: int, count: int) -> ApiError:
    return ApiError(
        409,
        "agent_limit",
        "the human holds as many agent profiles as allowed",
        {"limit": limit, "count": count},
    )


def _humans_at(conn: Connection, per_human: Any, limit: int | None) -> int:
    """The humans with at least `limit` of the rows `per_human` selects (a query of one
    column, the human's id); 0 under `unlimited`."""
    if limit is None:
        return 0
    counted = per_human.group_by(*per_human.selected_columns).having(func.count() >= limit)
    return int(conn.execute(select(func.count()).select_from(counted.subquery())).scalar_one())


def view(conn: Connection, hub: Settings) -> dict[str, Any]:
    values = resolve(conn, hub)
    agents = select(t.agent_profile.c.owner_id).where(t.agent_profile.c.deleted_at.is_(None))
    owners = (
        select(t.org_member.c.human_id)
        .join(t.org, t.org.c.id == t.org_member.c.org_id)
        .where(t.org_member.c.role == "owner", t.org.c.deleted_at.is_(None))
    )
    return {
        "max_agents_per_human": _answer(values["max_agents_per_human"]),
        "humans_at_limit": _humans_at(conn, agents, of(conn, hub, "max_agents_per_human")),
        "max_orgs_per_human": _answer(values["max_orgs_per_human"]),
        "humans_at_org_limit": _humans_at(conn, owners, of(conn, hub, "max_orgs_per_human")),
    }


def _answer(resolved: tuple[Any, str]) -> dict[str, Any]:
    return {"value": resolved[0], "source": resolved[1]}


def patch(conn: Connection, hub: Settings, body: dict[str, Any], by: str) -> None:
    """All of the body or nothing; `invalid` names each refused field. `null` restores the
    default (§16.2)."""
    errors: dict[str, str] = {}
    changes: dict[str, object] = {}
    for name, value in body.items():
        if name in READ_ONLY:
            errors[name] = "read_only"
        elif name not in NAMES:
            errors[name] = "extra_forbidden"
        elif getattr(hub, name) is not None:
            errors[name] = "set_by_environment"
        elif value is None:
            changes[name] = None
        elif _check(value) is None:
            errors[name] = "invalid"
        else:
            changes[name] = value
    if errors:
        raise invalid(errors)
    for name, value in changes.items():
        store.put(conn, f"limits.{name}", value, by)
