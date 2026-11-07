"""The caps of the admin section Limits (docs/api.md §16.5): agent profiles and organisations
owned by a human, projects in one namespace (a human's or an organisation's), the aliases of
one id (`max_aliases`, 1–8, never `unlimited`), and the attachment storage of each project
and of the whole instance, each from the environment, else from the instance admin, else its
default, by `instance_settings.effective`. A cap on an account is a whole number from 1 to
10000, a project's storage a number of bytes from 1 MiB to 1 PiB, the instance's from 1 GiB
to 1 PiB, either one or `unlimited`; the creations, moves and uploads the caps gate read the
effective value through `of`, and lowering one never deletes anything.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, func, or_, select

from maity_hub import attachments
from maity_hub import instance_settings as store
from maity_hub import tables as t
from maity_hub.config import Settings
from maity_hub.errors import ApiError, invalid

UNLIMITED = "unlimited"
STORAGE = "max_attachment_storage"
PROJECT_STORAGE = "max_attachment_storage_per_project"
ALIASES = "max_aliases"
DEFAULTS: dict[str, object] = {
    "max_agents_per_human": 100,
    "max_orgs_per_human": 5,
    "max_projects_per_owner": 10,
    ALIASES: 3,
    PROJECT_STORAGE: 1024**3,
    STORAGE: UNLIMITED,
}
NAMES = tuple(DEFAULTS)
READ_ONLY = (
    "humans_at_limit",
    "humans_at_org_limit",
    "owners_at_project_limit",
    "names_at_alias_limit",
    "attachment_storage_used",
)
RANGES = {name: (1, 10000) for name in NAMES} | {
    PROJECT_STORAGE: (1024**2, 1024**5),
    STORAGE: (1024**3, 1024**5),
    ALIASES: (1, 8),
}


def _checker(name: str) -> Any:
    low, high = RANGES[name]

    def check(value: object) -> object | None:
        """The value to store, or None when it is no cap."""
        if value == UNLIMITED:
            return None if name == ALIASES else value
        if isinstance(value, int) and not isinstance(value, bool) and low <= value <= high:
            return value
        return None

    return check


CHECKS = {name: _checker(name) for name in NAMES}
store.register(*(store.Setting(f"limits.{name}", CHECKS[name], DEFAULTS[name]) for name in NAMES))


def resolve(conn: Connection, hub: Settings) -> dict[str, tuple[Any, str]]:
    stored = store.stored(conn, "limits")
    return {name: store.effective(f"limits.{name}", getattr(hub, name), stored) for name in NAMES}


def of(conn: Connection, hub: Settings, name: str) -> int | None:
    """The cap in force, None for `unlimited`."""
    value = resolve(conn, hub)[name][0]
    return None if value == UNLIMITED else int(value)


def aliases(conn: Connection, hub: Settings | None) -> int:
    """`max_aliases` in force (§16.5). Without the hub's settings (a request the hub closes
    itself) the environment is not known here, so the admin's value or the default applies."""
    env = None if hub is None else hub.max_aliases
    return int(store.effective(f"limits.{ALIASES}", env, store.stored(conn, "limits"))[0])


def agent_limit(limit: int, count: int) -> ApiError:
    return ApiError(
        409,
        "agent_limit",
        "the human holds as many agent profiles as allowed",
        {"limit": limit, "count": count},
    )


def project_limit(limit: int, count: int) -> ApiError:
    return ApiError(
        409,
        "project_limit",
        "the namespace holds as many projects as allowed",
        {"limit": limit, "count": count},
    )


def refuse_project_over(conn: Connection, owner_id: str, limit: int | None) -> None:
    """`project_limit` when the namespace owner `owner_id` (a human or an organisation) holds
    `limit` projects or more, archived ones included; nothing under `unlimited`. The owner's
    row (the human's or the organisation's) is locked for the count, so that two creations or
    moves at `limit - 1` give one project and one `project_limit`; a caller that locks an
    organisation before a project has locked it already (§6.26)."""
    if limit is None:
        return
    table = t.human if owner_id.startswith("hum-") else t.org
    conn.execute(select(table.c.id).where(table.c.id == owner_id).with_for_update())
    count = int(
        conn.execute(
            select(func.count()).select_from(t.project).where(t.project.c.owner_id == owner_id)
        ).scalar_one()
    )
    if count >= limit:
        raise project_limit(limit, count)


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
    # A namespace owner whose account or organisation is deleted keeps its archived projects
    # (account_deletion.py), but creates nothing more: it is not counted at the limit.
    namespaces = select(t.project.c.owner_id).where(
        or_(
            t.project.c.owner_id.in_(select(t.human.c.id).where(t.human.c.deleted_at.is_(None))),
            t.project.c.owner_id.in_(select(t.org.c.id).where(t.org.c.deleted_at.is_(None))),
        )
    )
    return {
        "max_agents_per_human": _answer(values["max_agents_per_human"]),
        "humans_at_limit": _humans_at(conn, agents, of(conn, hub, "max_agents_per_human")),
        "max_orgs_per_human": _answer(values["max_orgs_per_human"]),
        "humans_at_org_limit": _humans_at(conn, owners, of(conn, hub, "max_orgs_per_human")),
        "max_projects_per_owner": _answer(values["max_projects_per_owner"]),
        "owners_at_project_limit": _humans_at(
            conn, namespaces, of(conn, hub, "max_projects_per_owner")
        ),
        ALIASES: _answer(values[ALIASES]),
        "names_at_alias_limit": _names_at(conn, aliases(conn, hub)),
        PROJECT_STORAGE: _answer(values[PROJECT_STORAGE]),
        STORAGE: _answer(values[STORAGE]),
        "attachment_storage_used": attachments.used_total(conn),
    }


def _names_at(conn: Connection, limit: int) -> int:
    """The humans, organisations, agent profiles and projects holding `limit` aliases or more
    (§16.5); a deleted profile's retired aliases do not count."""
    alias = t.handle_alias.c
    owner = func.coalesce(alias.human_id, alias.org_id, alias.agent_id).label("owner")
    handles = select(owner).where(alias.live.is_(True))
    projects = select(t.project_alias.c.project_id)
    return _humans_at(conn, handles, limit) + _humans_at(conn, projects, limit)


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
        elif CHECKS[name](value) is None:
            errors[name] = "invalid"
        else:
            changes[name] = value
    if errors:
        raise invalid(errors)
    for name, value in changes.items():
        store.put(conn, f"limits.{name}", value, by)
