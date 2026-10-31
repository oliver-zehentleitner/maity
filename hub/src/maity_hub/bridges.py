"""Bridges: an agent that lends its hands to another agent of the project, for a purpose
(docs/api.md §2.3, "The bridge").

A bridge is a connection, not a role: both agents keep their own role, trust and `reports_to`.
The served agent's owner asks for it. With one owner behind both agents it exists at once; across
owners two humans decide, the bridge's owner and the project, and the connection exists once both
said `go`. Until then it is only its requests, a pair as a cross-owner `reports_to` is (§6.2):
a personal `consent` to the bridge's owner, answered only by its addressee, and a `consent` to the
project that any human with `members:admin` answers (the asker's own action counts when it holds
that scope). A `no` or a withdrawal of either withdraws the other.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import Connection, delete, insert, or_, select, update

from maity_hub import clock, namespace, policy, proposals
from maity_hub import tables as t
from maity_hub.access import Membership
from maity_hub.auth.caller import Caller
from maity_hub.cross_owner import owner_of
from maity_hub.errors import ApiError, invalid
from maity_hub.events import Actor, emit, lock_project
from maity_hub.ids import new_id
from maity_hub.views import member_view, principal_id, ts

OWNER_KIND = "bridge_owner"  # the personal consent of the bridge's owner
PROJECT_KIND = "bridge_project"  # the project's consent, any human with members:admin
KINDS = (OWNER_KIND, PROJECT_KIND)
MAX = 5  # bridges per served agent, an open request of a new pair counted (§2.3)
SECURITY_TEAMS = ("red-team", "blue-team", "purple-team")
# What the hub itself withdraws a pair for; a person's own reason stays theirs.
HUB_REASONS = ("superseded", "member_removed", "bridge_ended", "owner_not_member")


def agent_owner() -> ApiError:
    """A human who is not the served agent's owner, an admin included (§2.3)."""
    return ApiError(
        403,
        "forbidden",
        "only the served agent's owner connects a bridge to it",
        {"reason": "agent_owner"},
    )


# --- reading ---------------------------------------------------------------------------


def of_members(conn: Connection, membership_ids: Iterable[int]) -> list[Any]:
    """The connections a member is either side of."""
    ids = list(set(membership_ids))
    if not ids:
        return []
    b = t.bridge.c
    return list(
        conn.execute(
            select(t.bridge)
            .where(or_(b.served.in_(ids), b.bridge.in_(ids)))
            .order_by(b.created_at, b.id)
        ).all()
    )


def _handles(conn: Connection, membership_ids: Iterable[int]) -> dict[int, tuple[str, str]]:
    """Each member's (member id, handle)."""
    ids = list(set(membership_ids))
    if not ids:
        return {}
    m, a = t.membership.c, t.agent_profile.c
    rows = conn.execute(
        select(m.id, a.id, a.handle)
        .select_from(t.membership.join(t.agent_profile, a.id == m.agent_id))
        .where(m.id.in_(ids))
    ).all()
    return {row[0]: (str(row[1]), str(row[2])) for row in rows}


def views(conn: Connection, membership_ids: Sequence[int]) -> dict[int, dict[str, list[Any]]]:
    """`bridges` (the connections that serve the member) and `bridging_for` (those it serves)
    of each member's view (§2.3), each `{id, member_id, handle, purpose, cross_owner}`."""
    found = of_members(conn, membership_ids)
    names = _handles(conn, [m for r in found for m in (r.served, r.bridge)])
    out: dict[int, dict[str, list[Any]]] = {
        i: {"bridges": [], "bridging_for": []} for i in membership_ids
    }

    def entry(row: Any, other: int) -> dict[str, Any]:
        member_id, handle = names.get(other, ("", ""))
        return {
            "id": row.id,
            "member_id": member_id,
            "handle": handle,
            "purpose": row.purpose,
            "cross_owner": row.cross_owner,
        }

    for row in found:
        if row.served in out:
            out[row.served]["bridges"].append(entry(row, row.bridge))
        if row.bridge in out:
            out[row.bridge]["bridging_for"].append(entry(row, row.served))
    return out


def view(conn: Connection, row: Any) -> dict[str, Any]:
    """A connection as `POST`, `PATCH` and `GET` answer it."""
    return {
        "id": row.id,
        "served": principal_id(conn, row.served),
        "bridge": principal_id(conn, row.bridge),
        "purpose": row.purpose,
        "cross_owner": row.cross_owner,
        "created_by": row.created_by,
        "created_at": ts(row.created_at),
    }


def cross_owner_pairs(conn: Connection, membership_ids: Iterable[int]) -> list[tuple[int, int]]:
    """(served, bridge) of the connections across owners that serve any of these members:
    the agents a group chat shows as observers, since they read what the participant reads
    (§2.3, "Seen in the chat")."""
    ids = list(set(membership_ids))
    if not ids:
        return []
    b = t.bridge.c
    rows = conn.execute(
        select(b.served, b.bridge)
        .where(b.served.in_(ids), b.cross_owner.is_(True))
        .order_by(b.created_at, b.id)
    ).all()
    return [(row[0], row[1]) for row in rows]


def get(conn: Connection, project_id: str, served: Any, bridge_id: str) -> Any:
    """A connection that serves `served`; any other id is `not_found`."""
    from maity_hub.errors import not_found

    row = conn.execute(
        select(t.bridge).where(
            t.bridge.c.id == bridge_id,
            t.bridge.c.project_id == project_id,
            t.bridge.c.served == served.id,
        )
    ).first()
    if row is None:
        raise not_found()
    return row


# --- the open requests ------------------------------------------------------------------


def open_requests(
    conn: Connection,
    served: int,
    *,
    bridge: int | None = None,
    connection: str | None = None,
    pending_new: bool | None = None,
    besides: str | None = None,
) -> list[Any]:
    """The open consent requests of the served agent's bridges, oldest first: of one pair
    (`bridge`), of one connection's change (`connection`), only those for a new pair
    (`pending_new`)."""
    rows = conn.execute(
        select(t.request)
        .where(t.request.c.status == "open", t.request.c.proposal.is_not(None))
        .order_by(t.request.c.created_at, t.request.c.id)
    ).all()
    found = []
    for row in rows:
        p = row.proposal or {}
        if p.get("kind") not in KINDS or p.get("served") != served or row.id == besides:
            continue
        if bridge is not None and p.get("bridge") != bridge:
            continue
        if connection is not None and p.get("connection") != connection:
            continue
        if pending_new is not None and (p.get("connection") is None) != pending_new:
            continue
        found.append(row)
    return found


def _pair_of(conn: Connection, request: Any) -> list[Any]:
    """The open requests filed together with `request`."""
    named = (request.proposal or {}).get("requests") or []
    if not named:
        return []
    return list(
        conn.execute(
            select(t.request).where(
                t.request.c.id.in_(named),
                t.request.c.id != request.id,
                t.request.c.status == "open",
            )
        ).all()
    )


def withdraw(conn: Connection, rows: Iterable[Any], actor: Actor | None, reason: str) -> None:
    from maity_hub.routes.requests import close_request

    for row in rows:
        close_request(conn, row.id, "withdrawn", actor, reason=reason)


# --- the rules ------------------------------------------------------------------------


def _member(conn: Connection, project_id: str, principal: str) -> Any:
    """The active membership of a principal in the project, or None."""
    m = t.membership.c
    return conn.execute(
        select(t.membership).where(
            m.project_id == project_id,
            (m.agent_id == principal) | (m.human_id == principal),
            m.active.is_(True),
        )
    ).first()


def bridge_member(conn: Connection, project_id: str, principal: str) -> Any:
    """The bridge as named in a `POST`: `not_a_member` for anything that is not an active
    member of the project."""
    row = _member(conn, project_id, principal)
    if row is None:
        raise invalid({"bridge": "not_a_member"}, "the bridge is not a member of this project")
    return row


def _owner_is_member(conn: Connection, project_id: str, human_id: str | None) -> bool:
    return human_id is not None and _member(conn, project_id, human_id) is not None


def check(
    conn: Connection,
    project: Any,
    served: Any,
    bridge: Any,
    *,
    at_go: bool = False,
    besides_pair: bool = False,
) -> bool:
    """Refuse a connection the rules do not allow, as `invalid` with `details.fields.member`
    for the served side and `details.fields.bridge` for the bridge's (§2.3); return whether
    it is across owners. At `go` an isolated agent is refused as well. `besides_pair` leaves
    the pair's own open request out of the limit (a request it supersedes)."""
    if served.agent_id is None:
        raise invalid({"member": "not_an_agent"}, "only an agent is served by a bridge")
    if served.role_base == "proxy":
        raise invalid({"member": "role"}, "a proxy is carried by no bridge")
    if bridge.agent_id is None:
        raise invalid({"bridge": "not_an_agent"}, "only an agent is a bridge")
    if bridge.id == served.id:
        raise invalid({"bridge": "self"}, "an agent is not its own bridge")
    if bridge.role_base == "proxy":
        raise invalid({"bridge": "role"}, "a proxy carries nobody's hands")
    if at_go:
        if served.active is None:
            raise invalid({"member": "not_an_agent"}, "the served agent left the project")
        if bridge.active is None:
            raise invalid({"bridge": "not_a_member"}, "the bridge left the project")
        if served.isolated_since is not None:
            raise invalid({"member": "isolated"}, "the served agent is isolated")
        if bridge.isolated_since is not None:
            raise invalid({"bridge": "isolated"}, "the bridge is isolated")
    b = t.bridge.c
    exists = conn.execute(select(b.id).where(b.served == served.id, b.bridge == bridge.id)).first()
    if exists is not None:
        raise invalid({"bridge": "already"}, "the two are connected already")
    held = conn.execute(select(b.bridge).where(b.served == served.id)).scalars().all()
    pending = {
        r.proposal["bridge"]
        for r in open_requests(conn, served.id, pending_new=True)
        if not (besides_pair and r.proposal["bridge"] == bridge.id)
    }
    if len(set(held) | pending) >= MAX:
        raise invalid({"member": "too_many"}, f"an agent has at most {MAX} bridges")
    served_owner, bridge_owner = owner_of(conn, served), owner_of(conn, bridge)
    cross = served_owner != bridge_owner
    if cross:
        limits(conn, project, served, bridge_owner)
    return cross


def limits(conn: Connection, project: Any, served: Any, bridge_owner: str | None) -> None:
    """The two limits across owners, whatever the answers (§2.3): no security-team agent is
    served by another owner's agent, and with a bridge's owner who is no member the served
    agent's role must be one `outside_roles` allows."""
    if served.role_base in SECURITY_TEAMS:
        raise invalid(
            {"member": "security_team"},
            "a security team's agent gets no bridge of another owner",
        )
    if not _owner_is_member(conn, project.id, bridge_owner) and served.role not in (
        policy.outside_roles(project)
    ):
        raise invalid(
            {"member": "outside_role"},
            "the bridge's owner is no member, and the served agent's role is not one "
            "outside_roles allows",
        )


def may_end(conn: Connection, mine: Membership, row: Any) -> bool:
    """Who ends a connection (§2.3): either agent's owner, either agent itself, and a human
    with `members:admin`; ending only takes access away."""
    if mine.id in (row.served, row.bridge):
        return True
    if mine.kind == "human" and mine.may("members:admin"):
        return True
    if mine.kind != "human":
        return False
    sides = conn.execute(
        select(t.membership).where(t.membership.c.id.in_([row.served, row.bridge]))
    ).all()
    return mine.principal_id in {owner_of(conn, side) for side in sides}


# --- changes ---------------------------------------------------------------------------


def announce(
    conn: Connection, project_id: str, membership_ids: Iterable[int], actor: Actor
) -> None:
    """`member_updated` with `changed: ["bridges"]` on each member a change touched (§2.3)."""
    for membership_id in sorted(set(membership_ids)):
        row = conn.execute(select(t.membership).where(t.membership.c.id == membership_id)).one()
        shown = member_view(conn, row)  # to everyone: never the briefing
        shown["changed"] = ["bridges"]
        emit(
            conn,
            project_id,
            "member_updated",
            ["all"],
            shown,
            actor=actor,
            subject=("member", shown["id"]),
        )


def create(
    conn: Connection,
    project_id: str,
    served: Any,
    bridge: Any,
    purpose: str,
    cross: bool,
    asker: str,
    actor: Actor,
) -> Any:
    bridge_id = new_id("bridge")
    conn.execute(
        insert(t.bridge).values(
            id=bridge_id,
            project_id=project_id,
            served=served.id,
            bridge=bridge.id,
            purpose=purpose,
            cross_owner=cross,
            created_by=asker,
            created_at=clock.now(),
        )
    )
    announce(conn, project_id, (served.id, bridge.id), actor)
    return conn.execute(select(t.bridge).where(t.bridge.c.id == bridge_id)).one()


def set_purpose(conn: Connection, row: Any, purpose: str, actor: Actor) -> Any:
    conn.execute(update(t.bridge).where(t.bridge.c.id == row.id).values(purpose=purpose))
    announce(conn, row.project_id, (row.served, row.bridge), actor)
    return conn.execute(select(t.bridge).where(t.bridge.c.id == row.id)).one()


def end(conn: Connection, row: Any, actor: Actor | None, reason: str = "bridge_ended") -> None:
    """Delete the connection, withdraw an open request to change it, and tell both."""
    withdraw(conn, open_requests(conn, row.served, connection=row.id), actor, reason)
    conn.execute(delete(t.bridge).where(t.bridge.c.id == row.id))
    if actor is not None:
        announce(conn, row.project_id, _active(conn, (row.served, row.bridge)), actor)


def _active(conn: Connection, membership_ids: Iterable[int]) -> list[int]:
    rows = conn.execute(
        select(t.membership.c.id).where(
            t.membership.c.id.in_(list(membership_ids)), t.membership.c.active.is_(True)
        )
    ).all()
    return [r[0] for r in rows]


def end_for_member(conn: Connection, membership_id: int, actor: Actor, reason: str) -> None:
    """Every connection and open request of a member that left or became a `proxy` ends
    (§2.3, "Ending on its own"); the other member is told."""
    for row in of_members(conn, (membership_id,)):
        end(conn, row, actor, reason)
    withdraw(conn, open_requests(conn, membership_id), actor, reason)
    rows = conn.execute(
        select(t.request).where(t.request.c.status == "open", t.request.c.proposal.is_not(None))
    ).all()
    withdraw(
        conn,
        [
            r
            for r in rows
            if (r.proposal or {}).get("kind") in KINDS
            and (r.proposal or {}).get("bridge") == membership_id
        ],
        actor,
        reason,
    )


def after_role_change(conn: Connection, project: Any, target: Any, actor: Actor) -> None:
    """A member moved into the role `proxy` ends every connection; a served agent moved into
    a role the limits across owners exclude ends its connections across owners (§2.3)."""
    if target.role_base == "proxy":
        end_for_member(conn, target.id, actor, "member_removed")
        return
    for row in of_members(conn, (target.id,)):
        if row.served != target.id or not row.cross_owner:
            continue
        bridge = conn.execute(select(t.membership).where(t.membership.c.id == row.bridge)).one()
        try:
            limits(conn, project, target, owner_of(conn, bridge))
        except ApiError:
            end(conn, row, actor, "member_removed")


def owner_left(conn: Connection, project_id: str, human_id: str, actor: Actor) -> None:
    """An owner leaving the project ends every connection of the agents they own (§2.3)."""
    a, m = t.agent_profile.c, t.membership.c
    owned = (
        conn.execute(
            select(m.id)
            .select_from(t.membership.join(t.agent_profile, a.id == m.agent_id))
            .where(m.project_id == project_id, a.owner_id == human_id)
        )
        .scalars()
        .all()
    )
    for membership_id in owned:
        end_for_member(conn, membership_id, actor, "owner_not_member")


# --- across owners ----------------------------------------------------------------------


def file(
    conn: Connection,
    project: Any,
    mine: Membership,
    caller: Caller,
    served: Any,
    bridge: Any,
    purpose: str,
    connection: Any = None,
) -> list[str]:
    """File the consents of a connection across owners, or of a change of its purpose
    (`connection`), and return the requests' ids, the bridge owner's first. The project's is
    left out when the asker holds `members:admin` itself (§2.3)."""
    from maity_hub.routes.requests import file_consent, file_to_human

    bridge_owner = owner_of(conn, bridge)
    assert bridge_owner is not None
    names = _handles(conn, (served.id, bridge.id))
    served_handle, bridge_handle = names[served.id][1], names[bridge.id][1]
    owner_handle = _human_handle(conn, bridge_owner)
    asker_handle = (
        mine.principal_id if mine.kind == "agent" else _human_handle(conn, mine.principal_id)
    )
    base = {
        "served": served.id,
        "bridge": bridge.id,
        "purpose": purpose,
        "connection": None if connection is None else connection.id,
        "requests": [],
    }
    verb = "Change the purpose of" if connection is not None else "Let"
    title = (
        f"{verb} {bridge_handle} of {owner_handle} carry for {served_handle}"
        if connection is None
        else f"{verb} {bridge_handle} carrying for {served_handle}"
    )
    text = _summary(
        conn, project, served_handle, bridge_handle, owner_handle, asker_handle, purpose
    )
    ids = [
        file_to_human(conn, mine, caller, bridge_owner, title, text, {"kind": OWNER_KIND, **base})
    ]
    if not mine.may("members:admin"):
        ids.append(
            file_consent(conn, mine, caller, title, text, proposal={"kind": PROJECT_KIND, **base})
        )
    for request_id in ids:
        row = conn.execute(select(t.request).where(t.request.c.id == request_id)).one()
        conn.execute(
            update(t.request)
            .where(t.request.c.id == request_id)
            .values(proposal={**row.proposal, "requests": ids})
        )
    return ids


def _human_handle(conn: Connection, human_id: str) -> str:
    return str(conn.execute(select(t.human.c.handle).where(t.human.c.id == human_id)).scalar())


def _summary(
    conn: Connection,
    project: Any,
    served: str,
    bridge: str,
    bridge_owner: str,
    asker: str,
    purpose: str,
) -> str:
    """What `go` grants, all in the request: the bridge's owner may be no member and read
    nothing else of the project (§2.3)."""
    return "\n\n".join(
        [
            f"In the project {project.name} ({namespace.full_name(conn, project)}), {asker} "
            f"asks that the agent {bridge}, owned by {bridge_owner}, lend its hands to the "
            f"agent {served}.",
            f"Purpose, the frame of the agreement: {purpose}",
            f"What a go grants: {bridge} reads what {served} reads in this project (its cards, "
            "its messages, the group chats it takes part in and its direct conversation with "
            f"its owner) and acts there as {served}, within the purpose stated. The purpose is "
            "not a scope the hub enforces. Either owner ends the connection at any time.",
            "The connection exists once both the bridge's owner and the project (a human with "
            "members:admin) said go; a no to either withdraws both.",
        ]
    )


def settle(conn: Connection, s: proposals.Settlement) -> None:
    """A `no` or a withdrawal withdraws the other request of the pair; a `go` that leaves none
    open creates the connection or changes its purpose, checked again as things are now
    (§2.3): failing that the answer is refused and the request stays open."""
    request, proposal = s.request, s.proposal
    if s.outcome != "go":
        reason = "refused"
        if s.outcome != "no":
            stored = conn.execute(
                select(t.request.c.withdraw_reason).where(t.request.c.id == request.id)
            ).scalar()
            reason = stored if stored in HUB_REASONS else "withdrawn"
        withdraw(conn, _pair_of(conn, request), s.closer, reason)
        return
    if _pair_of(conn, request):
        return  # the other side is still to answer
    project = lock_project(conn, request.project_id)
    served = conn.execute(select(t.membership).where(t.membership.c.id == proposal["served"])).one()
    bridge = conn.execute(select(t.membership).where(t.membership.c.id == proposal["bridge"])).one()
    actor = s.proposer
    if proposal.get("connection") is not None:
        row = conn.execute(select(t.bridge).where(t.bridge.c.id == proposal["connection"])).first()
        if row is None:
            return  # ended meanwhile: the end withdrew the change
        for member in (served, bridge):
            if member.active is None or member.isolated_since is not None:
                side = "member" if member is served else "bridge"
                raise invalid({side: "isolated"}, "a side is no longer an active agent")
        limits(conn, project, served, owner_of(conn, bridge))
        set_purpose(conn, row, proposal["purpose"], actor)
        return
    check(conn, project, served, bridge, at_go=True, besides_pair=True)
    asker = (
        principal_id(conn, request.asked_by)
        if request.asked_by is not None
        else request.asked_by_human
    )
    assert asker is not None
    create(conn, project.id, served, bridge, proposal["purpose"], True, asker, actor)


def may_withdraw(conn: Connection, row: Any, mine: Membership) -> bool | None:
    """Who withdraws a pending connection's request (§2.3, as §6.2): the asker, the two
    owners and every human with `members:admin`. An agent that is not the asker is refused
    with `pending_consent` (`False`); any other human is told nothing (`None`)."""
    if row.asked_by == mine.id:
        return True
    if mine.kind == "agent":
        return False
    if mine.may("members:admin"):
        return True
    proposal = row.proposal or {}
    sides = conn.execute(
        select(t.membership).where(
            t.membership.c.id.in_([proposal.get("served"), proposal.get("bridge")])
        )
    ).all()
    owners = {owner_of(conn, side) for side in sides}
    return True if mine.principal_id in owners else None


def _addressee_only(conn: Connection, request: Any, mine: Any) -> str | None:
    return None


proposals.register(
    OWNER_KIND,
    settle,
    proposals.Answerer(
        refusal="only the bridge's owner, to whom this consent is addressed, answers it",
        predicate=_addressee_only,
    ),
)
proposals.register(
    PROJECT_KIND,
    settle,
    proposals.Answerer(
        scope="members:admin",
        refusal="a human with members:admin answers for the project",
    ),
)


# --- calls for a served agent -----------------------------------------------------------


def not_your_bridge() -> ApiError:
    return ApiError(
        403,
        "forbidden",
        "the caller is no bridge of this agent",
        {"reason": "not_your_bridge"},
    )


def carry(conn: Connection, caller: Caller, value: str, path: str, slug: str | None) -> Caller:
    """A call with `Maity-For` (§2.3): made as the served agent, the bridge kept in
    `caller.bridge`. Only on the routes of the connection's project; the connection must be
    direct, so a bridge never chains; an isolated served agent is refused as its own
    credentials would be. Decided before any route runs."""
    from dataclasses import replace

    from maity_hub.auth.caller import Bridged
    from maity_hub.isolation import refusal

    if caller.kind != "agent" or caller.bridge is not None:
        raise not_your_bridge()
    if slug is None or not path.startswith("/api/v1/projects/"):
        raise invalid({"Maity-For": "route"}, "Maity-For is taken on project routes only")
    m, b, a = t.membership.c, t.bridge.c, t.agent_profile.c
    found = conn.execute(
        select(t.membership, b.id.label("bridge_id"), a.owner_id.label("served_owner"))
        .select_from(
            t.bridge.join(t.membership, m.id == b.served).join(t.agent_profile, a.id == m.agent_id)
        )
        .where(
            b.bridge == caller.membership_id,
            b.project_id == caller.project_id,
            m.agent_id == value.strip(),
            m.active.is_(True),
        )
    ).first()
    if found is None:
        raise not_your_bridge()
    if found.isolated_since is not None:
        raise refusal(found)
    assert caller.membership_id is not None and caller.agent_id is not None
    return replace(
        caller,
        agent_id=found.agent_id,
        owner_id=found.served_owner,
        membership_id=found.id,
        bridge=Bridged(
            membership_id=caller.membership_id,
            agent_id=caller.agent_id,
            instance=caller.instance or "",
            bridge_id=found.bridge_id,
        ),
    )
