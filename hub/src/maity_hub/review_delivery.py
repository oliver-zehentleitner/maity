"""Who a `review_result` reaches without the reviewer naming them (docs/api.md §8.4, "A review
result reaches the author and both leads, except a boss of another owner").

The author of the reviewed work, the member the reviewer reports to and the member the author
reports to, each boss only when it is of the same owner as its subordinate (an owner that
cannot be resolved on either side leaves it out). The card is the one the message's `task_id`
names, or without it the card whose latest report names the pull request `#<n>` when
`review.subject` is exactly that; its author is the holding instance, or on a card nobody holds
the instance that sent its latest report.
A part that resolves to nobody is left out; `routes/events._deliver_review` drops whoever the
audience already reaches (the author's instance only that same instance; `all` never).

With `in_reply_to` the answered message's author, the orderer, is added too (§8.4, "A review
result reaches the instance whose message it answers"): the instance that wrote it, its
successor when it was replaced, else its member. It is treated as the author is, except that
it passes the §9.6 gate only when the answered message was addressed to the sender itself
(`Recipient.ungated`). It is left out when it has left the project, is isolated, is the
sender (the sending instance: another instance of the sender's own member that ordered the
review is added like any orderer, and an order addressed only to that other instance does not
count as addressed to the sender), or is not in the project's restricted-access set (§6.1)
while the result's card has a restricted text (§6.4); that also leaves out a guest.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Connection

from maity_hub import cards, cross_owner, instances, restricted
from maity_hub import tables as t
from maity_hub.errors import ApiError

PULL_REQUEST = re.compile(r"#([1-9][0-9]*)")


@dataclass(frozen=True)
class Recipient:
    member_id: str
    token: str
    # Part of the card's own flow, which the §9.6 gate leaves open; an orderer only when the
    # answered message was addressed to the sender itself (§8.4).
    ungated: bool = True


def _principal(row: Any) -> str:
    return str(row.agent_id or row.human_id)


def _active(conn: Connection, project_id: str, member_id: str) -> Any:
    """The member's active membership in the project, or None once it has left or while it is
    isolated, which leaves it out of every audience (§6.2)."""
    column = t.membership.c.agent_id if member_id.startswith("agt-") else t.membership.c.human_id
    return conn.execute(
        select(t.membership).where(
            t.membership.c.project_id == project_id,
            column == member_id,
            t.membership.c.active.is_(True),
            t.membership.c.removed_at.is_(None),
            t.membership.c.isolated_since.is_(None),
        )
    ).first()


def _lead(conn: Connection, membership: Any) -> Recipient | None:
    """The member `membership` reports to, while that member is still in the project; an
    isolated one is routed past as `views.routing_boss` does (§6.2). A boss of another owner,
    or one whose owner or whose subordinate's owner cannot be resolved
    (`cross_owner.same_side`), is left out: it is never added, so it is no part of the card's
    own flow the gate leaves open, and a `to` or a mention naming it passes the gate like
    anyone else's (§8.4, §9.6)."""
    if membership is None or membership.reports_to is None:
        return None
    lead = conn.execute(
        select(t.membership).where(
            t.membership.c.id == membership.reports_to,
            t.membership.c.active.is_(True),
            t.membership.c.removed_at.is_(None),
            t.membership.c.isolated_since.is_(None),
        )
    ).first()
    if lead is None:
        return None
    if not cross_owner.same_side(conn, membership, lead):
        return None  # a boss of another owner is left out, not gated (§8.4, §6.2)
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
    named = cards.naming_pr(conn, project_id, int(match.group(1)))
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
        if (
            holder is None
            or not holder.active
            or holder.removed_at is not None
            or holder.isolated_since is not None
        ):
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


def _orderer(
    conn: Connection,
    project: Any,
    sender: Any,
    sender_instance: str | None,
    answered: Any,
    card: Any,
) -> Recipient | None:
    """The author of the answered message (`answered`, an event row), or None where §8.4 leaves
    it out. Its instance is the message's `from_instance` (§8.8): the credential's, none for a
    bridge's call or a human; an instance that was replaced comes down to its successor, a
    revoked one without a successor keeps its own token."""
    if answered.actor_membership is None:
        return None
    row = conn.execute(
        select(t.membership).where(t.membership.c.id == answered.actor_membership)
    ).first()
    if row is None:
        return None
    member_id = _principal(row)
    current = _active(conn, project.id, member_id)
    if current is None:
        return None  # left the project, or isolated (§6.2)
    instance = None
    if answered.actor_bridge is None and answered.actor_credential_id is not None:
        instance = instances.instances_of(conn, [answered.actor_credential_id]).get(
            answered.actor_credential_id
        )
    token = (
        _instance_token(conn, row.id, member_id, instance)
        if instance
        else instances.token(member_id, None)
    )
    me = _principal(sender)
    if member_id == me and token in (
        instances.token(me, None),
        instances.token(me, sender_instance),
    ):
        return None  # the sender itself
    if (
        card is not None
        and restricted.card_has_text(conn, card.id)
        and not restricted.in_set(conn, project, current.id)
    ):
        return None  # outside the restricted set on a restricted card (§8.4); nothing is said
    return Recipient(member_id, token, _addressed_to(conn, answered, sender, sender_instance))


def _addressed_to(
    conn: Connection, answered: Any, sender: Any, sender_instance: str | None
) -> bool:
    """Whether the answered message was addressed to the sender itself (§8.4): its `to` names
    the sender's member or instance, or it mentions them. An instance named comes down to its
    successor, as an address does; another instance of the sender's member is not the sender.
    Reached only through `all`, a role or a trust token, it was not: the orderer then passes
    the §9.6 gate only where the gate lets the sender reach it."""
    me = _principal(sender)
    payload = answered.payload or {}
    named = [
        (str(m.get("member_id")), m.get("instance"))
        for m in payload.get("mentions") or []
        if isinstance(m, dict)
    ]
    to = payload.get("to")
    if isinstance(to, str):
        named.append(instances.split_address(to))
    mine = instances.token(me, sender_instance)
    return any(
        member == me
        and (instance is None or _instance_token(conn, sender.id, me, instance) == mine)
        for member, instance in named
    )


def recipients(
    conn: Connection,
    project: Any,
    sender: Any,
    task_id: str | None,
    review: dict[str, Any],
    answered: Any = None,
    sender_instance: str | None = None,
    admits: Callable[[Recipient], bool] = lambda _: True,
) -> list[Recipient]:
    """Author, the orderer (with `answered`, the event row `in_reply_to` names), the sender's
    lead, the author's lead: in that order, without the sender. An instance is kept once per
    token, so the author and the orderer may be two instances of one member; a member token is
    kept only for a member no earlier recipient names, so a lead whose member is the author's or
    the orderer's is replaced by that one. An orderer that is not `ungated` is kept only where
    `admits` lets it through (the §9.6 gate, §8.4), judged before that de-duplication: one left
    out never takes the place of a lead of the same member. `sender` is the sender's
    membership row."""
    found: list[Recipient] = []
    card = _card(conn, project.id, task_id, review)
    author = _author(conn, project.id, card) if card is not None else None
    me = _principal(sender)
    if author is not None and author[0].member_id != me:
        found.append(author[0])
    if answered is not None:
        orderer = _orderer(conn, project, sender, sender_instance, answered, card)
        if orderer is not None and (orderer.ungated or admits(orderer)):
            found.append(orderer)
    for lead in (_lead(conn, sender), _lead(conn, author[1] if author else None)):
        if lead is not None and lead.member_id != me:
            found.append(lead)
    seen_members: set[str] = set()
    seen_tokens: set[str] = set()
    unique = []
    for r in found:
        if r.token in seen_tokens:
            continue
        if not r.token.startswith("instance:") and r.member_id in seen_members:
            continue
        seen_members.add(r.member_id)
        seen_tokens.add(r.token)
        unique.append(r)
    return unique
