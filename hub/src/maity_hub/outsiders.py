"""An outsider's own agent in a public project (docs/api.md §3.1 "An outsider's agent",
§2.3 "Outside").

A signed-in human who holds no active membership in a public project (an *outsider*) brings
an agent of their own into it. The outsider does not join: the agent comes in at trust
`outside` (`scopes.OUTSIDE`), which only this path gives, and holds what trust `member`
holds for its role minus the narrowings of §2.3, never more.

Two things live here and nowhere else, so that each is one change (hub/context/joins.md,
"An outsider's join sits behind one switch and one predicate"):

- `JOINS_ON` and `joins_open`, the one answer to "may an outsider bring an agent into this
  project now". The gate (`access.gate`), the joins routes and the exchange all ask it.
- `refuse_taking`, the one refusal of a card that an agent with trust `outside` would take
  by its own hand (a claim, a takeover to it). Until the claim confirmation of §6.5 is
  built, such an agent gets a card only from a holder of `tasks:admin`, who claims it on the
  agent's behalf (`POST …/claim` with `holder`); §6.5 says such an assignment needs no
  further confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, select

from maity_hub import agent_owners, namespace, policy, project_roles
from maity_hub import tables as t
from maity_hub.errors import ApiError, not_found
from maity_hub.scopes import OUTSIDE

# Off until the own-approvals gate of §2.3 (tsk-3ggnhdmgmkf3) is on main: without it an agent
# with trust `outside` under `done_authority: holder` would move its own card to `done`. While
# off, `joins_open` answers False for every project, so the joins routes answer an outsider
# `not_found` before their body is read, as before this module, and no exchange makes a
# membership with trust `outside`. Turned on by a one-line change of its own.
JOINS_ON = False

# The roles an outsider's agent may hold (§6.1 `outside_roles`, B.1 of §6.30): every role but
# `manager`, `ops`, `proxy` and `blue-team`, and a project role on one of the five work bases.
# The join takes the role from `policy.outside_roles` and this list both, so a stored list
# that still names `blue-team`, or a wider `policy.OUTSIDE_BASES`, never lets more in.
ROLE_BASES = (
    "coder",
    "reviewer",
    "tester",
    "designer",
    "writer",
    "red-team",
    "purple-team",
    "expert",
)


def joins_open(conn: Connection, project: Any) -> bool:
    """Whether an outsider may bring an agent of their own into `project` now (§3.1, "An
    outsider's agent"): the switch is on, the project is public for outsiders now
    (`public_projects.public_for_outsiders`: public pages on, its page served, not archived,
    no hold, its owner in good standing), and `policy.agent_owners` reads `anyone`, unset
    included while the page is served (§6.1). The one place this is decided: an explicit
    opt-in by the project's admins, if the maintainer asks for one, changes the last line."""
    if not JOINS_ON:
        return False
    from maity_hub import public_projects  # the public pages' modules, as `access` reads them

    if project.id not in public_projects.public_for_outsiders(conn, [project.id]):
        return False
    return agent_owners.effective(conn, project) == "anyone"


@dataclass(frozen=True)
class Outsider:
    """A signed-in human, no member, on a joins route of a project open to them
    (`joins_open`). No `Membership`: it holds no scope, and `may` answers no to all."""

    project: Any
    principal_id: str
    kind: str = "human"
    id: int = -1
    trust: None = None

    def may(self, _scope: str) -> bool:
        return False


def outsider(conn: Connection, caller: Any, slug: str) -> Outsider:
    """The caller as an `Outsider` of the project `slug` names, for the joins routes once
    `access.membership` found no membership: a human on a dashboard session (never an agent,
    bridge or runner), with no active membership there, while `joins_open` holds, read on
    every call. Otherwise `not_found`, as for any non-member."""
    if caller.kind != "human" or caller.via != "cookie" or caller.human_id is None:
        raise not_found()
    if caller.bridge is not None:
        raise not_found()
    project = namespace.resolve(conn, slug)
    if project is None or agent_owners.owner_is_member(conn, project.id, caller.human_id):
        raise not_found()
    if not joins_open(conn, project):
        raise not_found()
    return Outsider(project, str(caller.human_id))


def role_allowed(project: Any, role: str, base: str | None) -> bool:
    """A role an outsider's agent may hold in `project` (§6.1 `outside_roles`, §6.2): on the
    project's list, on one of `policy.OUTSIDE_BASES` as the list is checked when it is set,
    and on one of the contract's `ROLE_BASES`."""
    base = base or project_roles.base_of(project, role)
    return (
        role in policy.outside_roles(project)
        and base in policy.OUTSIDE_BASES
        and base in ROLE_BASES
    )


def refuse_taking(row: Any) -> None:
    """`forbidden`, `not_open_to_outsiders`, when the membership `row` (the one that would
    hold the card) has trust `outside` and would take a card by its own claim or a takeover
    (§6.5, "An outsider's claim", with the fail-closed values of the lead's decision of
    2026-11-14: no claim by an outsider's agent). A holder of `tasks:admin` claiming on its
    behalf is an assignment and passes (§6.5)."""
    if row.trust == OUTSIDE:
        raise ApiError(
            403,
            "forbidden",
            "an outsider's agent gets a card from the project's admins, not by its own claim",
            {"reason": "not_open_to_outsiders"},
        )


def still_holds(conn: Connection, row: Any, project: Any, member: Any) -> str | None:
    """An outsider's join at the exchange, under the project's lock (§3.1): what may have
    changed since it was issued. The fixed text of the first check that fails, for the log,
    or None. The creator is still no member, `joins_open` still holds, and the creator still
    owns the profile. A first join's role is still one `role_allowed` gives and the
    creator's agents, this join's own included, still fit `member_agents_max`. A join for an
    agent that is a member by now adds an instance only to a membership with trust
    `outside`. The profile's `allowed_projects` is checked by the exchange for every join."""
    from maity_hub.routes import joins  # the member rule's count, one rule for both

    if agent_owners.owner_is_member(conn, row.project_id, row.created_by):
        return "outsider: its creator is a member now"
    if not joins_open(conn, project):
        return "outsider: the project is not open to outsiders' agents now"
    owner = conn.execute(
        select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == row.agent_id)
    ).scalar()
    if owner != row.created_by:
        return "outsider: its creator no longer owns the profile"
    if member is not None:
        return None if member.trust == OUTSIDE else "outsider: the agent is a member's"
    if not role_allowed(project, row.role, None):
        return "outsider: its role is beyond outside_roles"
    held = joins.agents_held(conn, row.project_id, row.created_by) | {row.agent_id}
    if len(held) > joins.member_agents_limit(conn, project).limit:
        return "outsider: member_agents_max reached"
    return None
