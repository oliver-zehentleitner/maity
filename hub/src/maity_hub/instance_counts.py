"""How many instances stand behind the agents (docs/api.md §6.2 `manages`, §6.20, §16.7).

One counting rule for every place that shows it: an instance counts while it is not revoked,
and it counts as online while its presence is `online` (§5.3) or while it is dormant (§6.17):
a dormant instance is resting on purpose, not gone. `dormant` is therefore a part of `online`,
never added to it. Revoked instances never count; a paused one counts, offline, a dormant one
included. A member that is held — paused, its account suspended (both `presence: paused` in
the member view, §16.8), or isolated (§6.2) — has no instance online. An agent counts as
online while one of its instances does, so an agent whose instances all rest is online.

The member views carry the rule for the badge and `manages`; `sql_counted` and `sql_online`
are the same rule over the credential rows for the landing counters, which count across the
whole instance and read no member views (a suspended account's credentials are revoked).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, Connection, and_, or_, select

from maity_hub import tables as t


def online(instance: Mapping[str, Any]) -> bool:
    """One instance view (§6.17) counted as online: present, or dormant and not paused."""
    presence = instance.get("presence")
    if presence == "paused":
        return False
    return presence == "online" or instance.get("dormant") is not None


def held(member: Mapping[str, Any]) -> bool:
    """A member view (§6.2) whose instances are never online: paused, suspended or isolated."""
    return member.get("presence") == "paused" or member.get("isolated") is not None


def agent_online(member: Mapping[str, Any]) -> bool:
    """One agent's member view counted as online: not held, and one of its instances is."""
    if held(member):
        return False
    return member.get("presence") == "online" or any(
        online(i) for i in member.get("instances") or []
    )


def tally(members: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """`{instances, online, dormant}` over the active instances of these member views."""
    found = {"instances": 0, "online": 0, "dormant": 0}
    for member in members:
        live = [i for i in member.get("instances") or [] if not i.get("revoked_at")]
        found["instances"] += len(live)
        if held(member):
            continue
        awake = [i for i in live if online(i)]
        found["online"] += len(awake)
        found["dormant"] += sum(i.get("dormant") is not None for i in awake)
    return found


def _count(members: Sequence[Any], views: Mapping[int, Mapping[str, Any]]) -> dict[str, int]:
    return {"members": len(members), **tally(views[m.id] for m in members)}


def manages(
    rows: Sequence[Any], views: Mapping[int, Mapping[str, Any]], wanted: Iterable[int]
) -> dict[int, dict[str, dict[str, int]]]:
    """Per wanted membership id, `{direct, total}`: the members reporting to it, and the whole
    branch below it through `reports_to`, with their instances. `rows` are the project's active
    memberships, `views` their member views by membership id (for the instances)."""
    found: dict[int, dict[str, dict[str, int]]] = {}
    for top in wanted:
        direct = [r for r in rows if r.reports_to == top]
        found[top] = {"direct": _count(direct, views), "total": _count(branch(rows, top), views)}
    return found


def branch(rows: Sequence[Any], top: int) -> list[Any]:
    """The memberships below `top` through `reports_to`, at any depth."""
    below: dict[int, list[Any]] = {}
    for row in rows:
        if row.reports_to is not None:
            below.setdefault(row.reports_to, []).append(row)
    found: list[Any] = []
    seen, queue = {top}, list(below.get(top, []))
    while queue:
        row = queue.pop()
        if row.id not in seen:
            seen.add(row.id)
            found.append(row)
            queue.extend(below.get(row.id, []))
    return found


def for_member(conn: Connection, row: Any) -> dict[str, dict[str, int]]:
    """`manages` of one member: reads the project's active memberships, and the member views
    of its branch only (for their instances)."""
    from maity_hub.views import member_views  # views imports this module's callers

    rows = conn.execute(
        select(t.membership).where(
            t.membership.c.project_id == row.project_id, t.membership.c.active.is_(True)
        )
    ).all()
    below = branch(rows, row.id)
    views = {r.id: v for r, v in zip(below, member_views(conn, below), strict=True)}
    return manages(below, views, [row.id])[row.id]


# The same rule over `credential JOIN membership`, for counts across the instance.


def sql_counted() -> ColumnElement[bool]:
    """An instance that counts: of an active agent membership, not revoked."""
    return and_(
        t.membership.c.agent_id.is_not(None),
        t.membership.c.active.is_(True),
        t.credential.c.revoked_at.is_(None),
    )


def sql_online(now: datetime, window: Any) -> ColumnElement[bool]:
    """A counted instance that is online: its member not paused or isolated, the instance not
    paused, and a call within `window` or dormant (the presence rule's call time, §5.3)."""
    return and_(
        t.membership.c.paused_since.is_(None),
        t.membership.c.isolated_since.is_(None),
        t.credential.c.paused_since.is_(None),
        or_(
            t.credential.c.last_used_at >= now - window,
            t.credential.c.dormant_since.is_not(None),
        ),
    )
