"""Release cards: versions, pull requests, groups, checklist, readiness (docs/api.md §6.7).

Readiness is computed on every read from observed state only
(`context/integrations.md`): what an agent reported or a human typed counts
for nothing until the forge probe observed it. Without a probe a release is
never ready.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import Connection, select, update

from maity_hub import clock, forge
from maity_hub import tables as t
from maity_hub.events import emit

# SemVer 2.0 core with an optional pre-release; no build metadata (§6.7).
_ID = r"(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
SEMVER = re.compile(rf"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-{_ID}(?:\.{_ID})*)?")
PR_STATES = ("open", "merged", "closed")


def seed_checklist(texts: list[str]) -> list[dict[str, Any]]:
    return [
        {"id": f"chk-{i}", "text": text, "done": False, "by": None, "at": None}
        for i, text in enumerate(texts, 1)
    ]


def _observation(conn: Connection, project_id: str, kind: str, ref: str) -> dict[str, Any] | None:
    row = conn.execute(
        select(t.forge_observation).where(
            t.forge_observation.c.project_id == project_id,
            t.forge_observation.c.kind == kind,
            t.forge_observation.c.ref == ref,
        )
    ).first()
    if row is None:
        return None
    data: dict[str, Any] = dict(row.data)
    data["observed_at"] = clock.rfc3339(row.observed_at)
    return data


def _shipped(conn: Connection, card_id: str) -> list[Any]:
    return list(
        conn.execute(
            select(t.card)
            .join(t.card_edge, t.card_edge.c.to_card == t.card.c.id)
            .where(t.card_edge.c.from_card == card_id, t.card_edge.c.kind == "depends_on")
            .order_by(t.card.c.id)
        ).all()
    )


def _entry(
    number: int, source: str, task_id: str | None, attested: dict[str, Any], observed: Any
) -> dict[str, Any]:
    entry = {
        "number": number,
        "url": attested.get("url"),
        "title": attested.get("title"),
        "task_id": task_id,
        "state": attested.get("state"),
        "checks": None,
        "head_sha": attested.get("head"),
        "merged_at": None,
        "observed_at": None,
        "source": source,
    }
    if observed is not None:  # the forge's word replaces what was typed or reported
        for key in ("url", "title", "state", "checks", "head_sha", "merged_at", "observed_at"):
            if observed.get(key) is not None or key in ("merged_at", "observed_at"):
                entry[key] = observed.get(key)
    return entry


def pull_requests(conn: Connection, card: Any, shipped: list[Any]) -> list[dict[str, Any]]:
    """The shipped cards' reported PRs, then the typed ones; one entry per number."""
    entries: dict[int, dict[str, Any]] = {}
    for item in shipped:
        report = item.report or {}
        pr = report.get("pr")
        if report.get("pr_status") == "found" and pr:
            observed = _observation(conn, card.project_id, "pr", str(pr["number"]))
            entries.setdefault(
                pr["number"], _entry(pr["number"], "reported", item.id, pr, observed)
            )
    for typed in (card.release_data or {}).get("pull_requests_typed", []):
        number = typed["number"]
        if number not in entries:
            observed = _observation(conn, card.project_id, "pr", str(number))
            entries[number] = _entry(number, "typed", None, typed, observed)
    return [entries[n] for n in sorted(entries)]


def groups(conn: Connection, shipped: list[Any]) -> list[list[str]]:
    """The `ships_with` groups among the shipped cards (connected, two or more)."""
    ids = {c.id for c in shipped}
    edges = conn.execute(
        select(t.card_edge.c.from_card, t.card_edge.c.to_card).where(
            t.card_edge.c.kind == "ships_with", t.card_edge.c.from_card.in_(ids)
        )
    ).all()
    neighbours: dict[str, set[str]] = {i: set() for i in ids}
    for a, b in edges:
        if b in ids:
            neighbours[a].add(b)
    seen: set[str] = set()
    found = []
    for start in sorted(ids):
        if start in seen:
            continue
        component, frontier = set(), [start]
        while frontier:
            current = frontier.pop()
            if current in component:
                continue
            component.add(current)
            frontier += neighbours[current] - component
        seen |= component
        if len(component) > 1:
            found.append(sorted(component))
    return found


def readiness(
    conn: Connection,
    card: Any,
    shipped: list[Any],
    prs: list[dict[str, Any]],
    grouped: list[list[str]],
    probe_configured: bool,
) -> dict[str, Any]:
    if not probe_configured:
        return {"ready": False, "blocking": [{"reason": "probe_not_configured"}]}
    blocking: list[dict[str, Any]] = []
    for item in shipped:
        if item.status != "done":
            blocking.append({"reason": "task_open", "task": item.id})
    merged: dict[int, bool] = {}
    for entry in prs:
        number = entry["number"]
        if entry["observed_at"] is None:
            blocking.append({"reason": "pr_unverified", "pr": number})
        elif entry["state"] != "merged":
            blocking.append({"reason": "pr_open", "pr": number})
        merged[number] = entry["observed_at"] is not None and entry["state"] == "merged"
    for item in shipped:  # a reported head the forge does not show
        pr = (item.report or {}).get("pr")
        if pr and item.report.get("pr_status") == "found":
            seen = _observation(conn, card.project_id, "pr", str(pr["number"]))
            if seen is not None and seen.get("head_sha") and seen["head_sha"] != pr.get("head"):
                blocking.append({"reason": "pr_mismatch", "pr": pr["number"]})
    # A group is complete when every PR of every card in it is observed merged.
    by_card = {item.id: item for item in shipped}
    for group in grouped:
        numbers = [
            int(reported["number"])
            for card_id in group
            if (reported := (by_card[card_id].report or {}).get("pr"))
        ]
        if not all(merged.get(n, False) for n in numbers):
            blocking.append({"reason": "group_incomplete", "tasks": group})
    for item in (card.release_data or {}).get("checklist", []):
        if not item["done"]:
            blocking.append({"reason": "checklist_open", "item": item["id"]})
    return {"ready": not blocking, "blocking": blocking}


def probe_configured(conn: Connection, project_id: str) -> bool:
    url = conn.execute(
        select(t.project.c.repository_url).where(t.project.c.id == project_id)
    ).scalar()
    return forge.configured_for(url)


def release_view(conn: Connection, card: Any) -> dict[str, Any]:
    data = card.release_data or {}
    shipped = _shipped(conn, card.id)
    prs = pull_requests(conn, card, shipped)
    grouped = groups(conn, shipped)
    version = data.get("version") or card.release_version
    return {
        "version": version,
        "pull_requests": prs,
        "pull_requests_typed": data.get("pull_requests_typed", []),
        "groups": grouped,
        "checklist": data.get("checklist", []),
        "readiness": readiness(
            conn, card, shipped, prs, grouped, probe_configured(conn, card.project_id)
        ),
        "tag": _observation(conn, card.project_id, "tag", f"v{version}"),
    }


def recheck(conn: Connection, project_id: str) -> None:
    """Announce `release_ready` when the open release turned ready (§6.7).

    Called after anything readiness reads changed. The announcement is kept on
    the card, so it fires once per turn to ready, and again only after a turn back.
    """
    card = conn.execute(
        select(t.card).where(
            t.card.c.project_id == project_id, t.card.c.release_in_flight.is_(True)
        )
    ).first()
    if card is None:
        return
    view = release_view(conn, card)
    data = dict(card.release_data or {})
    announced = bool(data.get("ready_announced"))
    ready = bool(view["readiness"]["ready"])
    if ready == announced:
        return
    data["ready_announced"] = ready
    conn.execute(update(t.card).where(t.card.c.id == card.id).values(release_data=data))
    if ready:
        emit(
            conn,
            project_id,
            "release_ready",
            ["all"],
            {"release": card.id, "version": view["version"]},
            subject=("task", card.id),
        )
