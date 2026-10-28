"""A merge closes the loop (docs/api.md §6.6, §6.1 `merged_closes`).

When the probe first observes a report's pull request merged, with `mismatch` false,
on a card in `review`, the hub emits `task_merged` once per report: it wakes the done
authority, and under `merged_closes: auto` with `done_authority` `holder` or `admin`
the hub moves the card to `done` itself, unless a dependency or child is open or an
objection hold is on it. A merge observed while the card is elsewhere is remembered
with its report (`merge_report`) and told when the card returns to `review`, only if
that report is still the card's current one.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import Connection, select, update

from maity_hub import cards, clock
from maity_hub import tables as t
from maity_hub.events import emit
from maity_hub.instances import token
from maity_hub.views import principal_id

# Who moves a card to done (§6.4) as audience terms; `holder` is the holding instance.
AUTHORITY = {
    "reviewer": ["role:reviewer"],
    "tester": ["role:tester"],
    "reviewer_and_tester": ["role:reviewer", "role:tester"],
    "admin": ["trust:admin"],
}
# Where a merge is the step the project asks for, and `auto` may close (§6.6).
AUTO_UNDER = ("holder", "admin")


def report_key(report: dict[str, Any]) -> str:
    """The report as the agent sent it, as a digest: two reports differ in their time."""
    core = {k: v for k, v in report.items() if k not in ("observed", "mismatch")}
    return hashlib.sha256(json.dumps(core, sort_keys=True, default=str).encode()).hexdigest()


def merged(report: dict[str, Any] | None) -> bool:
    """The report's pull request observed merged, and what was merged is what was
    reported (`mismatch` false)."""
    if not report:
        return False
    return (report.get("observed") or {}).get("pr_state") == "merged" and report.get(
        "mismatch"
    ) is False


def observed(conn: Connection, card_id: str, merge_sha: str | None) -> None:
    """The probe stored a report's observation, under the project's lock."""
    card = conn.execute(select(t.card).where(t.card.c.id == card_id)).one()
    if not merged(card.report):
        return
    key = report_key(card.report)
    if card.merge_report == key and card.merge_told:
        return  # once per report
    if card.merge_report != key:
        conn.execute(
            update(t.card).where(t.card.c.id == card_id).values(merge_report=key, merge_told=False)
        )
    if card.status == "review":
        _tell(conn, card_id, merge_sha)


def returned_to_review(conn: Connection, card_id: str) -> None:
    """A card back in `review`: a merge remembered with its current report is told now."""
    card = conn.execute(select(t.card).where(t.card.c.id == card_id)).one()
    if (
        card.status == "review"
        and not card.merge_told
        and card.merge_report is not None
        and merged(card.report)
        and card.merge_report == report_key(card.report)
    ):
        _tell(conn, card_id, _merge_sha(conn, card))


def _merge_sha(conn: Connection, card: Any) -> str | None:
    number = ((card.report or {}).get("pr") or {}).get("number")
    if number is None:
        return None
    data = conn.execute(
        select(t.forge_observation.c.data).where(
            t.forge_observation.c.project_id == card.project_id,
            t.forge_observation.c.kind == "pr",
            t.forge_observation.c.ref == str(number),
        )
    ).scalar()
    return (data or {}).get("merge_sha")


def _blocked_by(conn: Connection, card: Any) -> list[str]:
    reasons = []
    children = conn.execute(
        select(t.card.c.id).where(t.card.c.parent == card.id, t.card.c.status.not_in(cards.CLOSED))
    ).first()
    if children is not None or cards.open_dependencies(conn, card.id):
        reasons.append("dependencies")
    held = conn.execute(
        select(t.takeover.c.id).where(
            t.takeover.c.task_id == card.id, t.takeover.c.status.in_(("objected", "escalated"))
        )
    ).first()
    if held is not None:
        reasons.append("objection")
    return reasons


def _tell(conn: Connection, card_id: str, merge_sha: str | None) -> None:
    from maity_hub.routes.tasks import audience as card_audience

    card = conn.execute(select(t.card).where(t.card.c.id == card_id)).one()
    project = conn.execute(select(t.project).where(t.project.c.id == card.project_id)).one()
    authority = project.done_authority
    closed = False
    blocked: list[str] = []
    if project.merged_closes == "auto" and authority in AUTO_UNDER:
        blocked = _blocked_by(conn, card)
        if not blocked:
            _close(conn, card)
            closed = True
    holder = principal_id(conn, card.claim_holder)
    holding = [token(holder, card.claim_instance)] if holder else []
    terms = holding if authority == "holder" else AUTHORITY.get(authority, ["trust:admin"])
    audience = [*terms, *(x for x in holding if x not in terms)]
    if "trust:admin" not in audience:
        audience.append("trust:admin")
    payload: dict[str, Any] = {
        "task": card.id,
        "pr": ((card.report or {}).get("pr") or {}).get("number"),
        "merge_sha": merge_sha,
        "done_authority": authority,
        "closed": closed,
    }
    if blocked:
        payload["blocked_by"] = blocked
    emit(conn, card.project_id, "task_merged", audience, payload, subject=("task", card.id))
    conn.execute(update(t.card).where(t.card.c.id == card.id).values(merge_told=True))
    if closed:
        after = conn.execute(select(t.card).where(t.card.c.id == card.id)).one()
        emit(
            conn,
            card.project_id,
            "task_updated",
            card_audience(conn, after),
            {
                "id": card.id,
                "status": "done",
                "fields": ["status"],
                "project_state": project.state,
            },
            subject=("task", card.id),
        )
        if card.parent is not None:
            _touch_parent(conn, card.parent, project.state)


def _touch_parent(conn: Connection, parent_id: str, state: str) -> None:
    """A child's status change reaches its parent as `task_updated` with `children`
    (§6.4 Child cards), as when an agent closes the child."""
    from maity_hub.routes.tasks import audience as card_audience

    conn.execute(update(t.card).where(t.card.c.id == parent_id).values(updated_at=clock.now()))
    parent = conn.execute(select(t.card).where(t.card.c.id == parent_id)).one()
    children = {"open": 0, "total": 0}
    for (status,) in conn.execute(select(t.card.c.status).where(t.card.c.parent == parent_id)):
        children["total"] += 1
        children["open"] += status not in ("done", "cancelled")
    emit(
        conn,
        parent.project_id,
        "task_updated",
        card_audience(conn, parent),
        {
            "id": parent_id,
            "fields": ["children"],
            "children": children,
            "history": [],
            "project_state": state,
        },
        subject=("task", parent_id),
    )


def _close(conn: Connection, card: Any) -> None:
    """The move to done the hub makes on its own (§6.15): no history entry; its record
    is `task_merged` with `closed: true` and the `task_updated` that every status change
    emits."""
    now = clock.now()
    values: dict[str, Any] = {
        "status": "done",
        "closed_at": now,
        "status_before_block": None,
        "blocked_by_request": None,
        "updated_at": now,
    }
    if card.kind == "release":
        values["release_in_flight"] = None
    conn.execute(update(t.card).where(t.card.c.id == card.id).values(**values))
