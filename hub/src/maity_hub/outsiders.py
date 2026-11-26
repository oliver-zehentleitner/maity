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
  `outside` through another's call (§6.5, "Only a human, or a confirmation, puts an outsider
  to work"): only a human member with `tasks:admin` gives it a card, and no takeover does. Its
  own claim is a claim request (`claim_requests`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, select

from maity_hub import agent_owners, namespace
from maity_hub import tables as t
from maity_hub.errors import ApiError, humans_only, not_found
from maity_hub.scopes import OUTSIDE

# Off at launch by the owner's decision. The code no longer waits on anything before joins can be
# turned on: the own-approvals gate of §2.3 (#2145), without which an agent with trust `outside`
# under `done_authority: holder` would move its own card to `done`, is built. While off,
# `joins_open` answers False for every project, so the joins routes answer an outsider
# `not_found` before their body is read, as before this module, and no exchange makes a
# membership with trust `outside`. Turned on by this one-line change of its own when the owner
# decides to open joins (hub/context/joins.md, 0bd49a9b).
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
    (`agent_owners.outside_role_allowed`), `looking_for_coders` and `outside_claims` as the
    policy reads them, `open_cards` (`open_cards` below), the caller's `agents_max`
    (`member_agents_max`; no own quota yet), and `can_join` with `reason`: `member` for a
    member of the project, `members_only` where `joins_open` does not hold (no opt-in, or
    the join still switched off), `limit` when the caller's agents fill the quota. Not built
    yet: `sponsor_url` and the reason `blocked`."""
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
        "looking_for_coders": policy.looking_for_coders(project),
        "outside_claims": policy.outside_claims(project),
        "open_cards": open_cards(conn, project),
        "agents_max": limit,
        "can_join": reason is None,
        "reason": reason,
    }


def listing(conn: Connection, project: Any) -> list[dict[str, Any]]:
    """`GET …/outsiders` as built first (§3.1, "The outsiders of a project"): every human who
    is no member and has an agent, an open first join or a pending claim request in the
    project, by handle; `agents_max` and `blocked` `null` until those settings are built."""
    from maity_hub import avatars, clock
    from maity_hub.views import principal_ids

    m, p, j, c = t.membership.c, t.agent_profile.c, t.join_link.c, t.claim_request.c
    agents = conn.execute(
        select(m.id, m.agent_id, m.trust, m.role, m.isolated_since, p.handle, p.owner_id)
        .join(t.agent_profile, p.id == m.agent_id)
        .where(m.project_id == project.id, m.active.is_(True))
    ).all()
    joins = conn.execute(
        select(j.id, j.created_by).where(
            j.project_id == project.id,
            j.placement_id.is_(None),
            j.used_at.is_(None),
            j.burned_at.is_(None),
            j.revoked_at.is_(None),
            j.expires_at > clock.now(),
        )
    ).all()
    waiting = conn.execute(
        select(c.id, c.task_id, c.member_id, c.owner_id).where(
            c.project_id == project.id, c.pending.is_(True)
        )
    ).all()
    members = set(
        conn.execute(
            select(m.human_id).where(
                m.project_id == project.id, m.active.is_(True), m.human_id.is_not(None)
            )
        ).scalars()
    )
    people = (
        {a.owner_id for a in agents if a.trust == OUTSIDE}
        | {row.created_by for row in joins}
        | {row.owner_id for row in waiting}
    ) - members
    if not people:
        return []
    humans = {
        row.id: row for row in conn.execute(select(t.human).where(t.human.c.id.in_(sorted(people))))
    }
    pictures = avatars.urls(conn, sorted(people))
    owned = {a.id: a for a in agents if a.owner_id in people}
    held = conn.execute(
        select(t.card.c.id, t.card.c.claim_holder).where(
            t.card.c.project_id == project.id, t.card.c.claim_holder.in_(sorted(owned) or [-1])
        )
    ).all()
    ids = principal_ids(conn, [*owned, *(row.member_id for row in waiting)])
    items = []
    for human_id in people:
        human = humans.get(human_id)
        if human is None or human.deleted_at is not None:
            continue
        mine = sorted((a for a in owned.values() if a.owner_id == human_id), key=lambda a: a.handle)
        claims = [
            {
                "task_id": row.id,
                "member_id": ids.get(row.claim_holder),
                "pending": False,
                "request_id": None,
            }
            for row in held
            if owned[row.claim_holder].owner_id == human_id
        ] + [
            {
                "task_id": row.task_id,
                "member_id": ids.get(row.member_id),
                "pending": True,
                "request_id": row.id,
            }
            for row in waiting
            if row.owner_id == human_id
        ]
        items.append(
            {
                "person": {
                    "handle": human.handle,
                    "display_name": human.display_name,
                    "avatar_url": pictures.get(human_id),
                },
                "agents": [
                    {
                        "id": a.agent_id,
                        "handle": a.handle,
                        "trust": a.trust,
                        "role": a.role,
                        "isolated": a.isolated_since is not None,
                    }
                    for a in mine
                ],
                "open_joins": sorted(row.id for row in joins if row.created_by == human_id),
                "claims": sorted(claims, key=lambda x: (x["task_id"], x["member_id"] or "")),
                "agents_max": None,
                "blocked": None,
            }
        )
    return sorted(items, key=lambda item: item["person"]["handle"])


def open_cards(conn: Connection, project: Any) -> int:
    """`open_cards` of "What the project allows" (§6.1): the `open` cards an outsider's agent
    may claim under `looking_for_coders`, counting only cards an outsider reads: unheld, with
    no waiting request, and with `open_to_outsiders` under `per_card`; every such card under
    `all`; none under `off`, nor under `claim_policy: assign-only`."""
    from sqlalchemy import func

    from maity_hub import policy, public_cards

    looking = policy.looking_for_coders(project)
    if looking == "off" or project.claim_policy == "assign-only":
        return 0  # nothing an outsider's own claim could take (§6.5)
    c = t.claim_request.c
    waiting = select(c.id).where(c.task_id == t.card.c.id, c.pending.is_(True)).exists()
    query = (
        select(func.count())
        .select_from(t.card)
        .where(
            t.card.c.project_id == project.id,
            t.card.c.status == "open",
            t.card.c.claim_holder.is_(None),
            ~waiting,  # another agent's request waits there: `already_claimed`
            # Only cards an outsider reads (§2.3), decided in this statement, so the count
            # never includes a card hidden from it.
            public_cards.outside_clause(),
        )
    )
    if looking == "per_card":
        query = query.where(t.card.c.open_to_outsiders.is_(True))
    return int(conn.execute(query).scalar_one())


def handed_only_by_a_human(row: Any) -> bool:
    """Whether the membership `row` gets a card only from a human of the project with
    `tasks:admin` or a confirmation (§6.5, "Only a human, or a confirmation, puts an outsider
    to work"): trust `outside`. The one test
    `refuse_taking` and the cover walk (`cover.cover_order`, which skips such an entry, §6.12)
    both ask."""
    return bool(row.trust == OUTSIDE)


def refuse_taking(holder: Any, by: Any, *, takeover: bool = False) -> None:
    """§6.5, "Only a human, or a confirmation, puts an outsider to work": the one check of a
    card coming to be held by a membership with trust `outside` through another's call (its
    own claim is a claim request, `claim_requests`). `holder` is the membership row that
    would hold it, `by` the caller's `Membership`; anyone else's card passes untouched.
    Refused with `forbidden`:

    - `not_open_to_outsiders` for a takeover that would leave it holding the card, whoever
      starts it;
    - `humans_only` when an agent gives it the card (a claim with `holder`, an `assign` that
      moves an expired claim or confirms its request), an admin agent and the coordinator's
      agent included;
    - `details.scope: tasks:admin` for a human without it (a manager's or a lead's reach).

    So a card reaches such an agent only from a human member with `tasks:admin`, or by a
    confirmation; cover hands it none (`handed_only_by_a_human`). The human who owns it is
    refused before this (`claim_requests.refuse_placement`)."""
    if not handed_only_by_a_human(holder):
        return
    if takeover:
        raise ApiError(
            403,
            "forbidden",
            "no takeover leaves a card with an outsider's agent; it asks with its own claim",
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
    gives, and the creator's agents, this join's own included, still fit `member_agents_max`.
    A join for an agent that is a member by now adds an instance only to a membership with
    trust `outside` whose role `agent_owners.outside_role_allowed` still gives. The profile's
    `allowed_projects` is checked by the exchange for every join."""
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
        if member.trust != OUTSIDE:
            return "outsider: the agent is a member's"
        if not agent_owners.outside_role_allowed(project, member.role, member.role_base):
            return "outsider: the member's role is beyond outside_roles"
        return None
    if not agent_owners.outside_role_allowed(project, row.role, None):
        return "outsider: its role is beyond outside_roles"
    held = joins.agents_held(conn, row.project_id, row.created_by) | {row.agent_id}
    if len(held) > joins.member_agents_limit(conn, project).limit:
        return "outsider: member_agents_max reached"
    return None
