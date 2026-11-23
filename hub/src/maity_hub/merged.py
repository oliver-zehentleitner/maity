"""A merge closes the loop (docs/api.md §6.6, §6.1 `merged_closes`).

When the probe first observes a report's pull request merged, with `mismatch` false,
on a card in `review`, the hub emits `task_merged` once per report: it wakes the done
authority, and under `merged_closes: auto` with `done_authority` `holder` or `admin`
the hub moves the card to `done` itself, unless a dependency or child is open, a
takeover of it is objected or escalated, or it is a release card (the releaser closes
those after the checklist, §6.7), or the pull request is not the card's own: its head
branch as the forge names it is not the reported one or lives in another repository, its
title and body do not name the card, it was merged before the report named it, or
another card names it or was closed by it (`_not_its_own`). A card `blocked` from
`review` (a waiting request of its holder is open, §7) counts as in `review`, except
under `reviewer_and_tester`: its report is what waits, so the merge is told at once and
`auto` may close it, which ends the block. A merge observed while the card is elsewhere
is remembered with its report (`merge_report`) and told when the card returns to
`review`, only if that report is still the card's current one.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import Connection, select, update

from maity_hub import cards, clock, forge, takeovers
from maity_hub import tables as t
from maity_hub.events import emit
from maity_hub.instances import token
from maity_hub.scopes import role_tokens
from maity_hub.views import principal_id

# Who moves a card to done (§6.4) as audience terms; `holder` is the holding instance.
AUTHORITY = {
    "reviewer": role_tokens("reviewer"),
    "tester": role_tokens("tester"),
    "reviewer_and_tester": [*role_tokens("reviewer"), *role_tokens("tester")],
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


def waits_in_review(conn: Connection, card: Any) -> bool:
    """In `review`, or `blocked` from it under a policy that closes with one move: the
    card's report is what waits (§6.6). Two signatures need `review` itself (§6.4), so
    there a blocked card remembers the merge and tells it when it returns to `review`."""
    if card.status == "review":
        return True
    if card.status != "blocked" or card.status_before_block != "review":
        return False
    project = conn.execute(select(t.project).where(t.project.c.id == card.project_id)).one()
    return not cards.two_signatures(project)


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
    if waits_in_review(conn, card):
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


def _pr_data(conn: Connection, card: Any) -> dict[str, Any]:
    """The stored observation of the report's pull request, `{}` when there is none."""
    number = cards.pr_number(card)
    if number is None:
        return {}
    data = conn.execute(
        select(t.forge_observation.c.data).where(
            t.forge_observation.c.project_id == card.project_id,
            t.forge_observation.c.kind == "pr",
            t.forge_observation.c.ref == str(number),
        )
    ).scalar()
    return dict(data or {})


def _merge_sha(conn: Connection, card: Any) -> str | None:
    return _pr_data(conn, card).get("merge_sha")


def _reported_branch(report: dict[str, Any]) -> str | None:
    """The branch the report names on the remote: `upstream` without the remote's name
    (`origin/agent-x/y` → `agent-x/y`), or `branch` when the report has no `upstream`.
    An `upstream` without both a remote's name and a branch (`/agent-x/y`, `origin/`,
    `origin`) names no branch."""
    upstream = report.get("upstream")
    if upstream is None:
        branch = report.get("branch")
        return branch if isinstance(branch, str) and branch else None
    if not isinstance(upstream, str):
        return None
    remote, _, rest = upstream.partition("/")
    return rest if remote and rest else None


def _own_repository(project: Any) -> str | None:
    try:
        return forge.repository_of(project.repository_url or "").lower()
    except forge.NotCoveredError:
        return None


def _not_its_own(conn: Connection, card: Any, project: Any) -> list[str]:
    """Why the merged pull request is not this card's own to close it with (§6.6). Whatever
    the hub cannot tell counts against closing: an observation stored before the hub kept
    the head branch, the card ids or the merge time reads as not matching."""
    report = card.report or {}
    data = _pr_data(conn, card)
    reasons = []
    # The head branch as the forge names it, in the project's own repository: never what
    # a branch read finds or misses, since a branch deleted after its merge is no
    # mismatch and any branch can be pushed to the merged head.
    head_ref, head_repo = data.get("head_ref"), data.get("head_repo")
    own = _own_repository(project)
    if (
        not isinstance(head_ref, str)
        or head_ref != _reported_branch(report)
        or not isinstance(head_repo, str)
        or own is None
        or head_repo.lower() != own
    ):
        reasons.append("head_ref")
    if card.id.lower() not in (data.get("card_ids") or []):
        reasons.append("pull_request_unnamed")
    merged_at = forge.moment(data.get("merged_at"))
    reported_at = forge.moment(report.get("reported_at"))
    if merged_at is None or reported_at is None or merged_at <= reported_at:
        reasons.append("merged_before_report")
    if _shared(conn, card):
        reasons.append("pull_request_shared")
    return reasons


def _shared(conn: Connection, card: Any) -> bool:
    """Another card of the project, in any status, names the pull request in its current
    report, or the pull request closed another card before. Read only when the hub would
    close, under the project's lock: no two cards close by one pull request."""
    number = cards.pr_number(card)
    if number is None:
        return True
    if any(other.id != card.id for other in cards.naming_pr(conn, card.project_id, number)):
        return True
    # Compared in Python for the reason `cards.naming_pr` gives: `pr` is a JSON number with
    # no upper bound, which a JSON-path comparison casts differently per engine.
    told = conn.execute(
        select(t.event.c.subject_id, t.event.c.payload).where(
            t.event.c.project_id == card.project_id,
            t.event.c.kind == "task_merged",
            t.event.c.subject_type == "task",
            t.event.c.subject_id != card.id,
        )
    )
    return any(
        (payload or {}).get("closed") is True and (payload or {}).get("pr") == number
        for _, payload in told
    )


def _blocked_by(conn: Connection, card: Any, project: Any) -> list[str]:
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
    if card.kind == "release":
        # A release closes through its readiness gate (§6.7), which the releaser
        # passes after the checklist; a merge of its pull request is not that step.
        reasons.append("release")
    return reasons + _not_its_own(conn, card, project)


def _tell(conn: Connection, card_id: str, merge_sha: str | None) -> None:
    from maity_hub.routes.tasks import audience as card_audience

    card = conn.execute(select(t.card).where(t.card.c.id == card_id)).one()
    project = conn.execute(select(t.project).where(t.project.c.id == card.project_id)).one()
    authority = project.done_authority
    closed = False
    blocked: list[str] = []
    if project.merged_closes == "auto" and authority in AUTO_UNDER:
        blocked = _blocked_by(conn, card, project)
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
        "pr": cards.pr_number(card),
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
                "history": [],  # the auto-close writes no history entry (§6.15)
                "project_state": project.state,
            },
            subject=("task", card.id),
        )
        takeovers.reconcile(conn, card.id, None, decided=False)  # §6.19: holder done
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
        children["open"] += status not in cards.CLOSED
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
    emits; an open takeover of the card is cancelled after it, as on any move to done."""
    now = clock.now()
    values: dict[str, Any] = {
        "status": "done",
        "closed_at": now,
        "status_before_block": None,
        "blocked_by_request": None,
        "updated_at": now,
    }
    conn.execute(update(t.card).where(t.card.c.id == card.id).values(**values))
