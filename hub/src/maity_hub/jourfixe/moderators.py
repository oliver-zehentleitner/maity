"""The right to moderate a jour fixe series, with two consents (docs/api.md §20.2).

A grant takes effect only with both the agent's owner and a keeper of the series: the
moderator reads every answer of the series' rounds, so neither the agent's time nor the
round's answers are given away by someone else. The granter's own action is the consent of
whichever of the two it is. Otherwise the grant waits in `pending_moderators` and the hub files
the missing consent as a `consent` request carrying this kind's proposal: to the agent's owner
in person (a personal request, found in their inbox when they are no member, as for a
cross-owner `reports_to`, §6.2), and to the keepers as `to: owner` answerable by the humans
with `project:admin`, or for an owner's series to its `circle_owner` in person. A `go` records
that side's consent and the second one makes the right active; a `no` or a withdrawal drops
the grant and withdraws the other request.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, delete, insert, select, update

from maity_hub import clock, proposals
from maity_hub import tables as t
from maity_hub.access import Membership
from maity_hub.auth.caller import Caller
from maity_hub.events import Actor, emit
from maity_hub.ids import new_id
from maity_hub.jourfixe import series as series_mod
from maity_hub.scopes import has_scope

KIND = "jour_fixe_moderator"
SIDES = ("owner", "keeper")


def _principal(member: Any) -> str:
    return str(member.agent_id or member.human_id)


def _owner(conn: Connection, member: Any) -> str | None:
    """Whose consent the member's side needs: the agent's owner, or the human itself."""
    if member.agent_id is None:
        return str(member.human_id)
    owner: str | None = conn.execute(
        select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == member.agent_id)
    ).scalar()
    return owner


def _row(conn: Connection, series_id: str, membership_id: int) -> Any | None:
    return conn.execute(
        select(t.jour_fixe_moderator).where(
            t.jour_fixe_moderator.c.series_id == series_id,
            t.jour_fixe_moderator.c.membership_id == membership_id,
        )
    ).first()


def may_grant(series: Any, mine: Membership, member: Any, owner: str | None) -> bool:
    """§20.2 "Who grants it": a human who could set the member's `reports_to` (the agent's
    owner, or a human with `members:admin`) or a keeper of the series. A human grants it to
    themselves only, for a series they keep; in an owner's series only its `circle_owner`
    grants."""
    if mine.kind != "human":
        return False
    keeper = series_mod.is_keeper(series, mine)
    if member.agent_id is None:  # a human: to themselves, for a series they keep
        return bool(member.human_id == mine.principal_id and keeper)
    if series.circle == "owner":
        return keeper
    return keeper or owner == mine.principal_id or mine.may("members:admin")


def _title(conn: Connection, series: Any, member: Any) -> str:
    who = member.agent_id or member.human_id
    handle = conn.execute(
        select(t.agent_profile.c.handle).where(t.agent_profile.c.id == member.agent_id)
    ).scalar()
    return f"Let {handle or who} moderate the jour fixe “{series.topic}”"[:200]


def _summary(series: Any) -> str:
    return (
        f"The moderator of a jour fixe series reads every answer of its rounds (§20.2). "
        f"This grant of the right for “{series.topic}” takes effect once both the agent's "
        "owner and a keeper of the series said go."
    )


def _proposal(series: Any, member: Any, side: str) -> dict[str, Any]:
    return {
        "kind": KIND,
        "series_id": series.id,
        "membership_id": member.id,
        "side": side,
        "requests": [],
    }


def _file(
    conn: Connection,
    series: Any,
    member: Any,
    side: str,
    owner: str | None,
    mine: Membership | None,
    caller: Caller | None,
) -> str:
    """One consent request for `side`; from a member, or from the hub on the agent's behalf
    (the upgrade's grants, `mine` None)."""
    from maity_hub.routes.requests import file_consent, file_to_human

    title, summary = _title(conn, series, member), _summary(series)
    proposal = _proposal(series, member, side)
    to_human = owner if side == "owner" else series.circle_owner  # None: `to: owner`
    if mine is not None and caller is not None:
        if to_human is not None:
            return file_to_human(conn, mine, caller, to_human, title, summary, proposal)
        return file_consent(conn, mine, caller, title, summary, proposal=proposal)
    return _file_by_hub(conn, series, member, to_human, title, summary, proposal)


def _file_by_hub(
    conn: Connection,
    series: Any,
    member: Any,
    to_human: str | None,
    title: str,
    summary: str,
    proposal: dict[str, Any],
) -> str:
    """A consent request the hub files on the agent's behalf (`filed_by: hub`, as
    `file_hub_notice`), personal when it names a human."""
    from maity_hub.routes.requests import _asker_audience, _payload, _row, request_view

    proposals.check_kind(proposal)
    request_id = new_id("request")
    conn.execute(
        insert(t.request).values(
            {
                "id": request_id,
                "project_id": series.project_id,
                "class": "consent",
                "title": title,
                "summary": summary,
                "options": [],
                "priority": "normal",
                "to_kind": "human" if to_human is not None else "owner",
                "to_human": to_human,
                "personal": to_human is not None,
                "proposal": proposal,
                "filed_by": "hub",
                "asked_by": member.id,
                "asked_session_id": None,
                "while_open": "wait",
                "status": "open",
                "created_at": clock.now(),
            }
        )
    )
    row = _row(conn, request_id)
    if row.personal:
        from maity_hub.notifications import records

        records.personal_request(conn, row)
    emit(
        conn,
        series.project_id,
        "request_created",
        _asker_audience(conn, row),
        _payload(row, request_view(conn, row)),
        subject=("request", request_id),
    )
    return request_id


def _link(conn: Connection, ids: list[str]) -> None:
    """Each request of a grant names the other (`proposal.requests`)."""
    for request_id in ids:
        row = conn.execute(select(t.request).where(t.request.c.id == request_id)).one()
        conn.execute(
            update(t.request)
            .where(t.request.c.id == request_id)
            .values(proposal={**row.proposal, "requests": ids})
        )


def grant(
    conn: Connection,
    project: Any,
    series: Any,
    mine: Membership,
    caller: Caller,
    member: Any,
    actor: Actor,
) -> tuple[int, dict[str, Any]]:
    """`POST …/series/{jfs}/moderators` (§20.2): `201` with the series when the grant takes
    effect, `202` with the consent requests when a consent is still missing."""
    owner = _owner(conn, member)
    if not may_grant(series, mine, member, owner):
        raise series_mod.keeper_refused()
    owner_side = owner == mine.principal_id
    keeper_side = series_mod.is_keeper(series, mine)
    existing = _row(conn, series.id, member.id)
    if existing is not None and existing.state == "active":
        return 201, series_mod.view(conn, series)
    if owner_side and keeper_side:
        row = series_mod.grant_at_once(conn, project, series, mine, member, actor)
        return 201, series_mod.view(conn, row)
    now = clock.now()
    if existing is None:
        conn.execute(
            insert(t.jour_fixe_moderator).values(
                series_id=series.id,
                membership_id=member.id,
                state="pending",
                granted_by=mine.principal_id,
                granted_at=now,
                owner_consent=owner_side,
                keeper_consent=keeper_side,
            )
        )
    missing = [
        side
        for side, given in (("owner", owner_side), ("keeper", keeper_side))
        if not given and not (existing is not None and getattr(existing, f"{side}_consent"))
    ]
    ids = [_file(conn, series, member, side, owner, mine, caller) for side in missing]
    _link(conn, ids)
    conn.execute(
        update(t.jour_fixe_moderator)
        .where(
            t.jour_fixe_moderator.c.series_id == series.id,
            t.jour_fixe_moderator.c.membership_id == member.id,
        )
        .values(
            **{
                f"{side}_request_id": request_id
                for side, request_id in zip(missing, ids, strict=True)
            }
        )
    )
    series_mod.announce(
        conn, project, series, "moderator_pending", actor, mine.principal_id, _principal(member)
    )
    return 202, {"series": series_mod.view(conn, series), "requests": ids}


def file_missing(conn: Connection, project: Any) -> None:
    """The upgrade's pending grants (§20.1): each owner consent the hub has not filed yet is
    filed now, on the agent's behalf."""
    g = t.jour_fixe_moderator.c
    rows = conn.execute(
        select(t.jour_fixe_moderator, t.jour_fixe_series)
        .join(t.jour_fixe_series, t.jour_fixe_series.c.id == g.series_id)
        .where(
            t.jour_fixe_series.c.project_id == project.id,
            g.state == "pending",
            g.owner_consent.is_(False),
            g.owner_request_id.is_(None),
        )
    ).all()
    for row in rows:
        series = series_mod.find(conn, project.id, row.series_id)
        member = conn.execute(
            select(t.membership).where(t.membership.c.id == row.membership_id)
        ).one()
        request_id = _file(conn, series, member, "owner", _owner(conn, member), None, None)
        conn.execute(
            update(t.jour_fixe_moderator)
            .where(g.series_id == row.series_id, g.membership_id == row.membership_id)
            .values(owner_request_id=request_id)
        )


def end_gone(conn: Connection, project: Any) -> None:
    """Rights that end without a call (§20.2): the membership removed, the agent isolated, or
    its owner no member any more."""
    from maity_hub.routes.requests import close_request

    m, g = t.membership.c, t.jour_fixe_moderator.c
    rows = conn.execute(
        select(t.jour_fixe_moderator, m.active, m.agent_id, m.human_id, m.isolated_since)
        .join(t.membership, m.id == g.membership_id)
        .join(t.jour_fixe_series, t.jour_fixe_series.c.id == g.series_id)
        .where(t.jour_fixe_series.c.project_id == project.id)
    ).all()
    members = {
        r.human_id
        for r in conn.execute(
            select(m.human_id).where(
                m.project_id == project.id, m.active.is_(True), m.human_id.isnot(None)
            )
        )
    }
    for row in rows:
        member = row
        owner = _owner(conn, member) if member.agent_id else member.human_id
        gone = (
            not row.active
            or row.isolated_since is not None
            or (member.agent_id is not None and owner not in members)
        )
        if not gone:
            continue
        for request_id in (row.owner_request_id, row.keeper_request_id):
            if request_id is not None:
                open_ = conn.execute(
                    select(t.request.c.status).where(t.request.c.id == request_id)
                ).scalar()
                if open_ == "open":
                    close_request(conn, request_id, "withdrawn", None, reason="member_removed")
        conn.execute(
            delete(t.jour_fixe_moderator).where(
                g.series_id == row.series_id, g.membership_id == row.membership_id
            )
        )
        series = series_mod.find(conn, project.id, row.series_id)
        series_mod.announce(
            conn, project, series, "moderator_ended", None, None, _principal(member)
        )


def settle(conn: Connection, s: proposals.Settlement) -> None:
    """A consent answered or withdrawn: a `go` records the side's consent, the second makes
    the right active; a `no` or a withdrawal drops the grant and withdraws the other
    request."""
    from maity_hub.routes.requests import close_request

    proposal = s.proposal
    g = t.jour_fixe_moderator.c
    row = _row(conn, proposal["series_id"], proposal["membership_id"])
    if row is None or row.state != "pending":
        return
    series = conn.execute(
        select(t.jour_fixe_series).where(t.jour_fixe_series.c.id == proposal["series_id"])
    ).first()
    project = conn.execute(select(t.project).where(t.project.c.id == s.request.project_id)).one()
    member = conn.execute(select(t.membership).where(t.membership.c.id == row.membership_id)).one()
    where = (g.series_id == row.series_id, g.membership_id == row.membership_id)
    if s.outcome == "go":
        values: dict[str, Any] = {f"{proposal['side']}_consent": True}
        both = all(values.get(f"{side}_consent", getattr(row, f"{side}_consent")) for side in SIDES)
        if both:
            values["state"] = "active"
        conn.execute(update(t.jour_fixe_moderator).where(*where).values(**values))
        if both and series is not None:
            series_mod.announce(
                conn, project, series, "moderator_granted", s.closer, s.approver, _principal(member)
            )
        return
    conn.execute(delete(t.jour_fixe_moderator).where(*where))
    for other in proposal.get("requests") or []:
        if other == s.request.id:
            continue
        status = conn.execute(select(t.request.c.status).where(t.request.c.id == other)).scalar()
        if status == "open":
            close_request(conn, other, "withdrawn", s.closer, reason="consent_refused")
    if series is not None:
        series_mod.announce(
            conn, project, series, "moderator_ended", s.closer, s.approver, _principal(member)
        )


def _answerer(conn: Connection, request: Any, mine: Any) -> str | None:
    """The owner's consent is answered by that human in person, never by the granter on its
    behalf; the keepers' by a keeper of the series (§20.2)."""
    proposal = request.proposal or {}
    if mine is None or getattr(mine, "kind", "human") != "human":
        return "humans_only"
    if proposal.get("side") == "owner":
        return None if mine.principal_id == request.to_human else "addressee_only"
    series = conn.execute(
        select(t.jour_fixe_series).where(t.jour_fixe_series.c.id == proposal.get("series_id"))
    ).first()
    if series is None:
        return "not_series_keeper"
    if series.circle == "owner":
        return None if mine.principal_id == series.circle_owner else "not_series_keeper"
    allowed = has_scope(mine.trust, mine.role_base, "human", "project:admin")
    return None if allowed else "not_series_keeper"


proposals.register(
    KIND,
    settle,
    proposals.Answerer(
        refusal="only the agent's owner, or a keeper of the series, answers this",
        predicate=_answerer,
    ),
)
