"""Another owner's agent changes only with its owner's consent (docs/api.md §6.2, "Another
owner's agent").

A `PATCH` of an agent member by a caller that is neither the agent's owner nor one of that
owner's agents nor a manager inside its reach does not change `trust`, `role`, `areas`,
`capabilities`, `briefing`, `paused` or `availability_policy` on the call: the hub files one
`consent` request, a personal request to the owner (`to: human:<id>`, §7, as the cross-owner
`reports_to` requests are), `asked_by` the caller, and applies the whole change at `go` as one
`member_updated`, the owner as approver and the caller as actor. A `no` or a withdrawal changes
nothing; a further `PATCH` of the member by such a caller withdraws the open request
(`superseded`) and files a new one for the fields it names.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, select

from maity_hub import admin_agents, cross_owner, namespace, project_roles, proposals
from maity_hub import tables as t
from maity_hub.access import Membership
from maity_hub.auth.caller import Caller
from maity_hub.errors import ApiError
from maity_hub.events import Actor, lock_project
from maity_hub.scopes import has_scope, in_admin_team
from maity_hub.views import principal_id

KIND = "foreign_agent_change"
# `role_base` goes with `role` (a role change sets both, §2.3): it waits for the owner too, but
# the summary names the role only.
FIELDS = ("trust", "role", "role_base", "areas", "capabilities", "briefing", "availability_policy")
SHOWN = 300  # characters of one value in the request's summary


def is_foreign(conn: Connection, who: Any, target: Any) -> bool:
    """The change needs the agent owner's consent: `target` is an agent and `who`, a
    membership row, is neither its owner nor one of that owner's agents."""
    if target.agent_id is None:
        return False
    return bool(cross_owner.owner_of(conn, who) != cross_owner.owner_of(conn, target))


def consented(values: dict[str, Any], pause: tuple[bool, str | None]) -> dict[str, Any]:
    """The fields of a change that wait for the owner."""
    wanted = {k: v for k, v in values.items() if k in FIELDS}
    if pause[0]:
        wanted["paused"] = pause[1]
    return wanted


def open_for(conn: Connection, target_id: int, besides: str | None = None) -> list[Any]:
    rows = conn.execute(
        select(t.request)
        .where(
            t.request.c.status == "open",
            t.request.c.proposal.is_not(None),
            t.request.c.personal.is_(True),
        )
        .order_by(t.request.c.created_at, t.request.c.id)
    ).all()
    return [
        r
        for r in rows
        if (r.proposal or {}).get("kind") == KIND
        and (r.proposal or {}).get("target") == target_id
        and r.id != besides
    ]


def withdraw_open(conn: Connection, target_id: int, actor: Actor | None, reason: str) -> None:
    """A newer `PATCH` (`superseded`) or the removal of the member (`member_removed`)."""
    from maity_hub.routes.requests import close_request

    for row in open_for(conn, target_id):
        close_request(conn, row.id, "withdrawn", actor, reason=reason)


def _shown(value: Any) -> str:
    text = "nothing" if value is None else str(value)
    return text if len(text) <= SHOWN else f"{text[:SHOWN]}… ({len(text)} characters)"


def _summary(
    conn: Connection, project: Any, asker: str, handle: str, target: Any, wanted: dict[str, Any]
) -> str:
    """What the decision needs, all in the request: the current and the proposed value of
    each field, for an owner who may not be a member of the project."""
    lines = [
        f"In the project {project.name} ({namespace.full_name(conn, project)}), {asker} asks "
        f"to change your agent {handle}:"
    ]
    for field, proposed in wanted.items():
        if field == "role_base":
            continue
        if field == "paused":
            current = target.paused_reason if target.paused_since is not None else None
            current_text = "not paused" if target.paused_since is None else _shown(current)
            proposed_text = "lift the pause" if proposed is None else f"pause: {_shown(proposed)}"
            lines.append(f"- paused: {current_text} → {proposed_text}")
        else:
            lines.append(f"- {field}: {_shown(getattr(target, field))} → {_shown(proposed)}")
    lines.append("Nothing changes until you answer; a `no` or a withdrawal changes nothing.")
    return "\n".join(lines)


def file(
    conn: Connection,
    project: Any,
    mine: Membership,
    caller: Caller,
    target: Any,
    values: dict[str, Any],
    pause: tuple[bool, str | None],
    instance: str | None,
) -> str | None:
    """File the owner's consent for `values` and `pause` of `target`; its id, or None when
    nothing in the change waits for the owner."""
    from maity_hub.routes.requests import file_to_human

    wanted = consented(values, pause)
    if not wanted:
        return None
    owner = cross_owner.owner_of(conn, target)
    assert owner is not None
    handle = cross_owner._handle(conn, target)
    asker = cross_owner._handle(conn, mine.row)
    proposal = {
        "kind": KIND,
        "target": target.id,
        "values": {k: v for k, v in values.items() if k in FIELDS},
        "pause": [pause[0], pause[1]],
        "instance": instance,
    }
    return file_to_human(
        conn,
        mine,
        caller,
        owner,
        f"Change {handle} in {project.name}",
        _summary(conn, project, asker, handle, target, wanted),
        proposal,
    )


def _refuse(why: str) -> ApiError:
    return ApiError(409, "asker_not_allowed", why)


def _still_allowed(
    asker: Any, project: Any, target: Any, values: dict[str, Any], pause: tuple[bool, str | None]
) -> None:
    """The asker may still make this change: still an active member, not isolated, still
    holding `members:admin` (a human) or still an admin agent, by the role's base (a project's
    own role holds the scopes of its base), and the call's own checks hold against today's
    state: only an owner grants trust `owner` or `admin` or the role `proxy`, an admin agent
    stays within §2.3 ᵃ. Otherwise the `go` is refused and the request stays open, for a `no`
    or a withdrawal, as every other refusal at a `go` (§6.2)."""
    from maity_hub.routes import members

    if asker is None or asker.active is not True or asker.isolated_since is not None:
        raise _refuse("the one who asked may not change this member any more")
    agent = asker.agent_id is not None
    if agent and not in_admin_team(asker.trust, asker.role_base):
        raise _refuse("the one who asked is no admin agent any more")
    if not agent and not has_scope(asker.trust, asker.role_base, "human", "members:admin"):
        raise _refuse("the one who asked no longer holds members:admin")
    mine = Membership(project, asker, "agent" if agent else "human")
    try:
        members._require_owner_for_change(mine, target, values)
    except ApiError:
        raise _refuse("the one who asked may not grant this any more") from None
    if agent:
        try:
            admin_agents.check_change(
                mine,
                target,
                trust=values.get("trust"),
                role=values.get("role"),
                capabilities="capabilities" in values,
                pause=(bool(pause[0]), pause[1] is None),
            )
        except ApiError:
            raise _refuse("an admin agent does not make this change") from None


def settle(conn: Connection, s: proposals.Settlement) -> None:
    """Apply the whole change on `go`, the owner as approver and the asker as actor; `no` and a
    withdrawal change nothing (§6.2)."""
    from maity_hub.routes import members

    if s.outcome != "go" or s.approver is None:
        return
    proposal, request = s.proposal, s.request
    project = lock_project(conn, request.project_id)
    target = conn.execute(
        select(t.membership).where(t.membership.c.id == proposal["target"])
    ).first()
    if target is None or target.active is None:  # removed meanwhile: nothing left to change
        return
    asker = conn.execute(select(t.membership).where(t.membership.c.id == request.asked_by)).first()
    given, reason = proposal["pause"]
    values = dict(proposal["values"])
    if "role" in values:
        # The base of the role as the project has it now: a project role may have been rebased
        # or removed while the request waited (§2.3 "Project roles").
        base = project_roles.base_of(project, values["role"])
        if base is None:
            raise ApiError(409, "role_unknown", "the project has no such role any more")
        values["role_base"] = base
    _still_allowed(asker, project, target, values, (bool(given), reason))
    assert asker is not None  # `_still_allowed` refuses a missing asker
    by = principal_id(conn, asker.id)
    assert by is not None
    change = members.Change(project, s.proposer, by, s.approver, None, None)
    old = members.apply_patch(
        conn, change, target, values, (bool(given), reason), instance=proposal.get("instance")
    )
    if asker.agent_id is not None:
        for field in ("trust", "role"):
            if field in old:
                admin_agents.announce(conn, change, target, field, old[field], values[field])


def _addressee_only(conn: Connection, request: Any, mine: Any) -> str | None:
    return None


proposals.register(
    KIND,
    settle,
    proposals.Answerer(
        refusal="only the agent's owner answers this consent",
        predicate=_addressee_only,
    ),
)
