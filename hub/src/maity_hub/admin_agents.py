"""An admin agent's management of the agent memberships below it (docs/api.md §2.3 ᵃ).

An agent with the `admin` role holds `members:admin` only here: `PATCH` and `DELETE` of
an agent membership whose role is `member` or `reviewer` and that is not its own, and
in a `PATCH` only `reports_to`, `areas`, `briefing`, `paused`, `availability_policy`
(§6.12) and `role` between `member` and `reviewer`. Everything a human decides stays a
human's: a human's membership, `capabilities`, the `proxy`, `admin` and `owner` roles,
a pause a human set (`humans_only`). A removal, and a change of the role, the pause or
the availability policy of a reviewer, of the contract arbiter or of the coordinator,
waits for the owner's go: it is filed as a `member_change` proposal (`proposals`),
which only a human with `members:admin` answers, and applied on `go` with the agent as
actor and the human as approver, when the change is still allowed then. Every other use
of `members:admin` stays human-only through the scope table.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, select

from maity_hub import proposals
from maity_hub import tables as t
from maity_hub.access import Membership
from maity_hub.auth.caller import Caller
from maity_hub.errors import ApiError, forbidden, humans_only, invalid
from maity_hub.events import emit
from maity_hub.views import principal_id

AGENT_ROLES = ("member", "reviewer")


def check_target(mine: Membership, target: Any) -> None:
    if target.agent_id is None:
        raise humans_only("an agent never changes a human's membership")
    if target.id == mine.id or target.role not in AGENT_ROLES:
        raise forbidden(
            "members:admin", "an admin agent manages member and reviewer agents, never itself"
        )


def _paused_by_a_human(target: Any) -> bool:
    by: str | None = target.paused_by
    return target.paused_since is not None and by is not None and by.startswith("hum-")


def _pause_of_another_agent(target: Any, agent_id: str) -> bool:
    by: str | None = target.paused_by
    return (
        target.paused_since is not None
        and by is not None
        and by != agent_id
        and (by.startswith("agt-"))
    )


def check_patch(mine: Membership, target: Any, body: Any, given: set[str]) -> None:
    check_target(mine, target)
    if "capabilities" in given:
        raise humans_only("capabilities are a human's to set")
    if body.role is not None and body.role not in AGENT_ROLES:
        raise humans_only("an admin agent moves a role between member and reviewer only")
    if "paused" in given:
        _check_pause(target, mine.principal_id)


def _check_pause(target: Any, agent_id: str) -> None:
    """Who lifts or replaces a pause: a human's only a human, another agent's only that
    agent or a human (§2.3 ᵃ)."""
    if _paused_by_a_human(target):
        raise humans_only("a pause a human set is a human's to lift or replace")
    if _pause_of_another_agent(target, agent_id):
        raise forbidden(
            "members:admin", "a pause another agent set is that agent's or a human's to lift"
        )


def _is_arbiter(project: Any, target: Any) -> bool:
    arbiter: str = project.contract_arbiter
    return bool(arbiter == target.agent_id)


def _is_coordinator(project: Any, target: Any) -> bool:
    coordinator: str = project.coordinator
    return bool(coordinator == target.agent_id)


def needs_consent(
    conn: Connection,
    mine: Membership,
    target: Any,
    values: dict[str, Any],
    pause: tuple[bool, str | None],
) -> bool:
    """A role change or a pause of a reviewer or of the contract arbiter (§2.3 ᵃ), and a
    change of the availability policy of a reviewer, the arbiter or the coordinator,
    as for a role change (§6.12)."""
    del conn
    project = mine.project
    sensitive = target.role == "reviewer" or _is_arbiter(project, target)
    touches = ("role" in values and values["role"] != target.role) or pause[0]
    cover_seat = sensitive or _is_coordinator(project, target)
    return bool((sensitive and touches) or (cover_seat and "availability_policy" in values))


def _handle(conn: Connection, target: Any) -> str:
    handle: str = conn.execute(
        select(t.agent_profile.c.handle).where(t.agent_profile.c.id == target.agent_id)
    ).scalar_one()
    return handle


def propose(
    conn: Connection, mine: Membership, caller: Caller, target: Any, change: dict[str, Any]
) -> str:
    """File the consent request to the owner that applies `change` on its go."""
    from maity_hub.routes.requests import file_consent

    handle = _handle(conn, target)
    if change["action"] == "remove":
        title = f"Remove {handle}"
    elif "role" in change.get("values", {}):
        title = f"Change {handle} to {change['values']['role']}"
    elif "availability_policy" in change.get("values", {}):
        title = f"Change cover for {handle}"
    else:
        title = f"Pause {handle}"
    summary = f"{principal_id(conn, mine.id)} asks for this change of {handle}'s membership."
    proposal = {"kind": "member_change", "membership_id": target.id, **change}
    return file_consent(conn, mine, caller, title, summary, proposal=proposal)


def announce(
    conn: Connection,
    change: Any,
    target: Any,
    kind: str,
    old: Any,
    new: Any,
    request_id: str | None = None,
) -> None:
    """`member_changed_by_agent` to `role:owner` (§8.2), so a role change or a removal
    by an agent reaches the human and not only the log."""
    payload: dict[str, Any] = {
        "member_id": principal_id(conn, target.id),
        "change": kind,
        "old": old,
        "new": new,
        "actor": principal_id(conn, change.actor.membership_id),
    }
    if request_id is not None:
        payload["request_id"] = request_id
    emit(
        conn,
        change.project.id,
        "member_changed_by_agent",
        ["role:owner"],
        payload,
        actor=change.actor,
        subject=("member", payload["member_id"]),
    )


def _still_allowed(conn: Connection, proposer: Any, target: Any, proposal: dict[str, Any]) -> None:
    """A `go` applies what the admin agent may do now, every rule of its call again
    (`hub/context/proposals.md`): the proposer still an active admin agent, the target
    still a member or reviewer agent, a pause still not a human's or another agent's, no
    `reports_to` cycle the time in between made. Otherwise the answer is refused and the
    request stays open."""
    from maity_hub.routes import members

    if proposer is None or proposer.active is not True or proposer.role != "admin":
        raise ApiError(409, "proposer_not_admin", "the proposing agent is no admin here now")
    if target.role not in AGENT_ROLES:
        raise ApiError(
            409, "target_role_changed", f"the member is {target.role} now, not member or reviewer"
        )
    if proposal["action"] != "patch":
        return
    if proposal["pause"][0]:
        try:
            _check_pause(target, proposer.agent_id)
        except ApiError:
            raise ApiError(
                409, "pause_changed", "the pause is someone else's now; the go cannot touch it"
            ) from None
    boss = proposal["values"].get("reports_to")
    if boss is not None and target.id in members.chain(conn, boss):
        raise invalid({"reports_to": "cycle"}, "the chain made a cycle in the meantime")
    cover = proposal["values"].get("availability_policy")
    if cover is not None:
        from maity_hub import availability

        errors = availability.policy_errors(conn, target.project_id, target, cover)
        if errors:  # a substitute left, or changed, while the request waited (§6.12)
            raise invalid(errors, "the cover cannot apply as proposed any more")


def settle(conn: Connection, s: proposals.Settlement) -> None:
    """Apply the change on `go`, with the proposing agent as actor and the approving
    human as the authority for revoked credentials; `no` and a withdrawal change
    nothing."""
    from maity_hub.routes import members

    if s.outcome != "go" or s.approver is None:
        return
    proposal, request = s.proposal, s.request
    target = conn.execute(
        select(t.membership).where(t.membership.c.id == proposal["membership_id"])
    ).one()
    if target.active is None:  # removed meanwhile: nothing left to change
        return
    proposer = conn.execute(
        select(t.membership).where(t.membership.c.id == request.asked_by)
    ).first()
    _still_allowed(conn, proposer, target, proposal)
    project = conn.execute(select(t.project).where(t.project.c.id == request.project_id)).one()
    agent = principal_id(conn, request.asked_by)
    assert agent is not None
    change = members.Change(project, s.proposer, agent, s.approver, None, None)
    if proposal["action"] == "remove":
        members.apply_remove(conn, change, target)
        announce(conn, change, target, "removed", target.role, None, request.id)
        return
    values = dict(proposal["values"])
    boss = values.get("reports_to")
    if boss is not None:  # the boss may have left while the request waited (§6.2)
        active = conn.execute(
            select(t.membership.c.id).where(
                t.membership.c.id == boss, t.membership.c.active.is_(True)
            )
        ).first()
        if active is None:
            values["reports_to"] = None
    given, reason = proposal["pause"]
    old = members.apply_patch(conn, change, target, values, (bool(given), reason))
    if "role" in old:
        announce(conn, change, target, "role", old["role"], values["role"], request.id)


# The approver could make the change themselves: a human with `members:admin` (§2.3 ᵃ).
proposals.register(
    "member_change",
    settle,
    proposals.Answerer(
        scope="members:admin",
        refusal="a human with members:admin answers an agent's change of a membership",
    ),
)
