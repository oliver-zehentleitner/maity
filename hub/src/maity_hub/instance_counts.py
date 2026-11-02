"""How many instances stand behind the agents (docs/api.md §6.2 `manages`, §6.20, §16.7).

One counting rule for every place that shows it: an instance counts while it is not revoked,
and it counts as online while its presence is `online` (§5.3) or while it is dormant (§6.17):
a dormant instance is resting on purpose, not gone. `dormant` is therefore a part of `online`,
never added to it. Revoked instances never count; a paused one counts, offline. An agent
counts as online while one of its instances does, so a dormant team is an online agent.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from sqlalchemy import Connection, select

from maity_hub import tables as t


def online(instance: Mapping[str, Any]) -> bool:
    """One instance view (§6.17) counted as online: present, or dormant."""
    return instance.get("presence") == "online" or instance.get("dormant") is not None


def agent_online(member: Mapping[str, Any]) -> bool:
    """One agent's member view (§6.2) counted as online: one of its instances is."""
    return member.get("presence") == "online" or any(
        online(i) for i in member.get("instances") or []
    )


def tally(instances: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """`{instances, online, dormant}` over instance views of active instances."""
    seen = list(instances)
    return {
        "instances": len(seen),
        "online": sum(online(i) for i in seen),
        "dormant": sum(i.get("dormant") is not None for i in seen),
    }


def _count(members: Sequence[Any], views: Mapping[int, Mapping[str, Any]]) -> dict[str, int]:
    instances = [i for m in members for i in views[m.id].get("instances") or []]
    return {"members": len(members), **tally(instances)}


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
