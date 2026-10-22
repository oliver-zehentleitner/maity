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
# ASCII digits only: `\d` would take every Unicode digit, and `1٠.0.0` looks like 10.0.0.
_ID = r"(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
SEMVER = re.compile(rf"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-{_ID}(?:\.{_ID})*)?")
PR_STATES = ("open", "merged", "closed")


def checklist_item(number: int, text: str) -> dict[str, Any]:
    return {"id": f"chk-{number}", "text": text, "done": False, "by": None, "at": None}


def seed_checklist(texts: list[str]) -> list[dict[str, Any]]:
    return [checklist_item(i, text) for i, text in enumerate(texts, 1)]


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
        for key in ("url", "title"):
            if observed.get(key) is not None:
                entry[key] = observed[key]
        for key in ("state", "checks", "head_sha", "merged_at", "observed_at"):
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
    """The connected `ships_with` components of the shipped cards, over all edges.

    A partner outside the release belongs to its group: the group then
    cannot be complete, which is the half-merged pair this gate exists for.
    """
    seen: set[str] = set()
    found = []
    for start in sorted(c.id for c in shipped):
        if start in seen:
            continue
        component, frontier = {start}, {start}
        while frontier:
            edges = conn.execute(
                select(t.card_edge.c.from_card, t.card_edge.c.to_card).where(
                    t.card_edge.c.kind == "ships_with",
                    t.card_edge.c.from_card.in_(frontier) | t.card_edge.c.to_card.in_(frontier),
                )
            ).all()
            frontier = {card for edge in edges for card in edge} - component
            component |= frontier
        seen |= component
        if len(component) > 1:
            found.append(sorted(component))
    return found


def readiness(
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
    # A reported head the forge does not show; once per PR, a short head as a prefix.
    by_number = {entry["number"]: entry for entry in prs}
    reported: dict[int, set[str]] = {}
    for item in shipped:
        pr = (item.report or {}).get("pr")
        if pr and item.report.get("pr_status") == "found" and pr.get("head"):
            reported.setdefault(int(pr["number"]), set()).add(str(pr["head"]).lower())
    for number, heads in sorted(reported.items()):
        seen = by_number[number]["head_sha"] if by_number[number]["observed_at"] else None
        if seen and not all(seen.lower().startswith(head) for head in heads):
            blocking.append({"reason": "pr_mismatch", "pr": number})
    # A group is complete when all its cards ship here and all their PRs are observed merged.
    by_card = {item.id: item for item in shipped}
    for group in grouped:
        numbers = [
            int(reported_pr["number"])
            for card_id in group
            if card_id in by_card and (reported_pr := (by_card[card_id].report or {}).get("pr"))
        ]
        complete = all(card_id in by_card for card_id in group) and all(
            merged.get(n, False) for n in numbers
        )
        if not complete:
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


def _live(conn: Connection, card: Any) -> dict[str, Any]:
    """Pull requests, groups and readiness as the release stands now."""
    shipped = _shipped(conn, card.id)
    prs = pull_requests(conn, card, shipped)
    grouped = groups(conn, shipped)
    ready = readiness(card, shipped, prs, grouped, probe_configured(conn, card.project_id))
    return {"pull_requests": prs, "groups": grouped, "readiness": ready}


def release_view(conn: Connection, card: Any) -> dict[str, Any]:
    """The release object; a closed release serves what was frozen at its close (§6.7)."""
    data = card.release_data or {}
    version = data.get("version") or card.release_version
    computed = data.get("frozen") or _live(conn, card)
    return {
        "version": version,
        "pull_requests": computed["pull_requests"],
        "pull_requests_typed": data.get("pull_requests_typed", []),
        "groups": computed["groups"],
        "checklist": data.get("checklist", []),
        "readiness": computed["readiness"],
        "tag": _observation(conn, card.project_id, "tag", f"v{version}"),
    }


def close(conn: Connection, card_id: str) -> None:
    """Called by the write that closes a release, after its own update.

    A release that turned ready in this very write is announced here (the
    write also cleared `release_in_flight`, so `recheck` no longer sees it),
    and its pull requests, groups and readiness are frozen into the card: a
    closed release is a record, and later edges or observations do not
    change it.
    """
    card = conn.execute(select(t.card).where(t.card.c.id == card_id)).one()
    data = dict(card.release_data or {})
    live = _live(conn, card)
    if card.status == "done" and live["readiness"]["ready"] and not data.get("ready_announced"):
        data["ready_announced"] = True
        _announce(conn, card, data.get("version") or card.release_version)
    data["frozen"] = live
    conn.execute(update(t.card).where(t.card.c.id == card.id).values(release_data=data))


def _announce(conn: Connection, card: Any, version: str) -> None:
    emit(
        conn,
        card.project_id,
        "release_ready",
        ["all"],
        {"release": card.id, "version": version},
        subject=("task", card.id),
    )


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
        _announce(conn, card, view["version"])
