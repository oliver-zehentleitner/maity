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
- `refuse_taking`, the one check of a card coming to be held by an agent with trust
  `outside` (§6.5, "Until the claim request is built"): such an agent claims nothing itself,
  and gets a card only from a human member with `tasks:admin`, who claims it on the agent's
  behalf (`POST …/claim` with `holder`) or moves an expired claim to it (`assign`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, select

from maity_hub import agent_owners, namespace
from maity_hub import tables as t
from maity_hub.errors import ApiError, humans_only, not_found
from maity_hub.scopes import OUTSIDE

# Off until the own-approvals gate of §2.3 (tsk-3ggnhdmgmkf3) is on main: without it an agent
# with trust `outside` under `done_authority: holder` would move its own card to `done`. While
# off, `joins_open` answers False for every project, so the joins routes answer an outsider
# `not_found` before their body is read, as before this module, and no exchange makes a
# membership with trust `outside`. Turned on by a one-line change of its own.
JOINS_ON = False


def joins_open(conn: Connection, project: Any) -> bool:
    """Whether an outsider may bring an agent of their own into `project` now (§3.1, "An
    outsider's agent"; §6.1, "The outsiders' opt-in"): the switch is on, the project's admins
    opted in, and the project is public for outsiders now (`public_projects.
    public_for_outsiders`: public pages on, its page served, not archived, no hold, its owner
    in good standing). The opt-in is a stored `policy.agent_owners: anyone`, set by a human;
    the unset value, which `agent_owners.effective` reads as `anyone` while the page is
    served, opens no join (req-gp8jzgr6zdvj). The one place this is decided."""
    if not JOINS_ON:
        return False
    if project.agent_owners != "anyone":
        return False
    from maity_hub import public_projects  # the public pages' modules, as `access` reads them

    return project.id in public_projects.public_for_outsiders(conn, [project.id])


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


def contribution(
    conn: Connection, project: Any, human_id: str | None, member: bool
) -> dict[str, Any]:
    """`GET …/contribution` (§6.1, "What the project allows"), as far as it is built:
    `agent_owners` as stored (`null` while unset), `outside_roles` an outsider's agent may hold
    (`agent_owners.outside_role_allowed`), `open_cards` (`0`: until the claim request is
    built, an outsider's agent claims no card, §6.5), the caller's `agents_max`
    (`member_agents_max`; no own quota yet), and `can_join` with `reason`: `member` for a
    member of the project, `members_only` where `joins_open` does not hold (no opt-in, or the
    join still switched off), `limit` when the caller's agents fill the quota. Not built yet:
    `looking_for_coders`, `outside_claims`, `sponsor_url` and the reason `blocked`."""
    from maity_hub import policy
    from maity_hub.routes import joins  # the member rule's count, one rule for both

    limit = joins.member_agents_limit(conn, project).limit
    reason: str | None = None
    if member:
        reason = "member"
    elif not joins_open(conn, project):
        reason = "members_only"
    elif human_id is not None and len(joins.agents_held(conn, project.id, human_id)) >= limit:
        reason = "limit"
    return {
        "agent_owners": project.agent_owners,
        "outside_roles": [
            role
            for role in policy.outside_roles(project)
            if agent_owners.outside_role_allowed(project, role, None)
        ],
        "open_cards": 0,
        "agents_max": limit,
        "can_join": reason is None,
        "reason": reason,
    }


def refuse_taking(holder: Any, by: Any, *, takeover: bool = False) -> None:
    """The interim of §6.5, "Until the claim request is built" (req-yzt08c2qgx6g): the one
    check of a card coming to be held by a membership with trust `outside`. `holder` is the
    membership row that would hold it, `by` the caller's `Membership`; anyone else's card
    passes untouched. Refused with `forbidden`:

    - `not_open_to_outsiders` for its own claim, and for a takeover that would leave it
      holding the card, whoever starts it;
    - `humans_only` when an agent gives it the card (a claim with `holder`, an `assign` that
      moves an expired claim), an admin agent and the coordinator's agent included;
    - `details.scope: tasks:admin` for a human without it (a manager's or a lead's reach).

    So a card reaches such an agent only from a human member with `tasks:admin`."""
    if holder.trust != OUTSIDE:
        return
    if takeover or holder.id == by.id:
        raise ApiError(
            403,
            "forbidden",
            "an outsider's agent takes no card itself; a human of the project with "
            "tasks:admin assigns it one",
            {"reason": "not_open_to_outsiders"},
        )
    if by.kind != "human":
        raise humans_only("only a human of the project gives an outsider's agent a card")
    by.require("tasks:admin")


def still_holds(conn: Connection, row: Any, project: Any, member: Any) -> str | None:
    """An outsider's join at the exchange, under the project's lock (§3.1): what may have
    changed since it was issued. The fixed text of the first check that fails, for the log,
    or None. The creator is still no member, `joins_open` still holds, and the creator still
    owns the profile. A first join's role is still one `agent_owners.outside_role_allowed`
    gives, and the
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
    if not agent_owners.outside_role_allowed(project, row.role, None):
        return "outsider: its role is beyond outside_roles"
    held = joins.agents_held(conn, row.project_id, row.created_by) | {row.agent_id}
    if len(held) > joins.member_agents_limit(conn, project).limit:
        return "outsider: member_agents_max reached"
    return None
