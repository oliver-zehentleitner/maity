"""Who a `review_result` reaches without the reviewer naming them (docs/api.md §8.4, "A review
result reaches the author and both leads").

The author of the reviewed work, the member the reviewer reports to and the member the author
reports to. The card is the one the message's `task_id` names, or without it the card whose
latest report names the pull request `review.subject` gives as `#<n>`; its author is the
holding instance, or on a card nobody holds the instance that sent its latest report. A part
that resolves to nobody is left out; `routes/events.post_message` drops whoever the audience
already reaches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Connection

from maity_hub import instances
from maity_hub import tables as t
from maity_hub.errors import ApiError

PULL_REQUEST = re.compile(r"#([1-9][0-9]*)")


@dataclass(frozen=True)
class Recipient:
    member_id: str
    token: str


def _principal(row: Any) -> str:
    return str(row.agent_id or row.human_id)


def _active(conn: Connection, project_id: str, member_id: str) -> Any:
    """The member's active membership in the project, or None once it has left (§6.2)."""
    column = t.membership.c.agent_id if member_id.startswith("agt-") else t.membership.c.human_id
    return conn.execute(
        select(t.membership).where(
            t.membership.c.project_id == project_id,
            column == member_id,
            t.membership.c.active.is_(True),
            t.membership.c.removed_at.is_(None),
        )
    ).first()


def _lead(conn: Connection, membership: Any) -> Recipient | None:
    """The member `membership` reports to, while that member is still in the project."""
    if membership is None or membership.reports_to is None:
        return None
    lead = conn.execute(
        select(t.membership).where(
            t.membership.c.id == membership.reports_to,
            t.membership.c.active.is_(True),
            t.membership.c.removed_at.is_(None),
        )
    ).first()
    if lead is None:
        return None
    member_id = _principal(lead)
    return Recipient(member_id, instances.token(member_id, None))


def _card(conn: Connection, project_id: str, task_id: str | None, review: dict[str, Any]) -> Any:
    if task_id is not None:
        return conn.execute(
            select(t.card).where(t.card.c.id == task_id, t.card.c.project_id == project_id)
        ).first()
    match = PULL_REQUEST.fullmatch(review["subject"].strip())
    if match is None:
        return None
    number = int(match.group(1))
    # As `ticker.linked_cards` does: the reports live on the cards as JSON, read in Python.
    rows = conn.execute(
        select(t.card).where(t.card.c.project_id == project_id, t.card.c.report.is_not(None))
    ).all()
    named = [row for row in rows if (((row.report or {}).get("pr") or {}).get("number")) == number]
    if not named:
        return None
    return max(named, key=lambda row: ((row.report or {}).get("reported_at") or "", row.id))


def _instance_token(conn: Connection, membership_id: int, member_id: str, instance: str) -> str:
    """The instance as an address in a `to` comes down to, its successor when it was replaced;
    the team when the member never had that instance."""
    try:
        return instances.addressed(conn, membership_id, member_id, instance, "review")
    except ApiError:
        return instances.token(member_id, None)


def _author(conn: Connection, project_id: str, card: Any) -> tuple[Recipient, Any] | None:
    if card.claim_holder is not None:
        holder = conn.execute(
            select(t.membership).where(t.membership.c.id == card.claim_holder)
        ).first()
        if holder is None or not holder.active or holder.removed_at is not None:
            return None
        member_id = _principal(holder)
        token = (
            _instance_token(conn, holder.id, member_id, card.claim_instance)
            if card.claim_instance
            else instances.token(member_id, None)
        )
        return Recipient(member_id, token), holder
    report = card.report or {}
    reporter = report.get("reported_by")
    if not isinstance(reporter, str) or not reporter:
        return None
    member_id = reporter
    membership = _active(conn, project_id, member_id)
    if membership is None:
        return None
    instance = report.get("reported_instance")
    token = (
        _instance_token(conn, membership.id, member_id, instance)
        if instance
        else instances.token(member_id, None)
    )
    return Recipient(member_id, token), membership


def recipients(
    conn: Connection,
    project_id: str,
    sender: Any,
    task_id: str | None,
    review: dict[str, Any],
) -> list[Recipient]:
    """Author, the sender's lead, the author's lead: in that order, each member once, without
    the sender. `sender` is the sender's membership row."""
    found: list[Recipient] = []
    card = _card(conn, project_id, task_id, review)
    author = _author(conn, project_id, card) if card is not None else None
    if author is not None:
        found.append(author[0])
    for lead in (_lead(conn, sender), _lead(conn, author[1] if author else None)):
        if lead is not None:
            found.append(lead)
    me = _principal(sender)
    seen: set[str] = set()
    unique = []
    for r in found:
        if r.member_id == me or r.member_id in seen:
            continue
        seen.add(r.member_id)
        unique.append(r)
    return unique
