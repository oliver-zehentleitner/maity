# The manager

## The reach is computed on read, in its own module, under the project lock

**Id:** 5acd17fc-3126-49ec-ba06-bfbac8f5804a
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-29 (#541; the shape agreed with the coordinator for the card)
**Revisit when:** a project's membership count makes one read of all its memberships per `line:lead` call too slow

`line.reach()` reads every active membership of the project once and walks
the `reports_to` edges down from the manager: same-owner agents below
governance (trust `member` or `guest`, not `proxy`) as part (a), recursing;
another owner's agent reporting to the manager itself with `line_consent`
as part (b), not recursing. Nothing is stored. Every route that decides a
write on the reach (card assign, `PATCH assigned_to`, release, create with
`assigned_to`, member `PATCH`, and the `go` of a manager's consent request)
holds the project lock before it reads it, so a concurrent `reports_to`
change cannot move a member out of the reach between the check and the
write. The module is separate from `routes/members.py` and
`admin_agents.py` because three routes and a proposal kind share it, and
because the manager's rules are a different right from ᵃ, not a narrower
admin agent.

**Rejected alternatives:**
- A stored reach or line table, updated on every `reports_to`, role, trust
  and ownership change: many writers to keep in step, for chains of at most
  8 members.
- A recursive SQL query: three engines, and the stop conditions (owner,
  trust, role, consent) read more clearly in Python.

## A manager's pause is marked by a column, not by `paused_by`

**Id:** 8040236c-b8c0-41f2-b37c-47838835b447
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-29 (migration 0078)
**Revisit when:** pauses get an origin field in the contract

`membership.paused_line` and `credential.paused_line` say that the pause
beside them was set under `line:lead`. Who lifts a pause depends on the
right it was set under (§5.3): a manager's is lifted by a manager above, an
admin agent and the agent's owner; an admin agent's only by that agent or a
human. `paused_by` names the principal, and the same agent can be a manager
and an admin agent, or a human manager; so the principal alone cannot tell
them apart, and its current role may have changed since.

**Rejected alternative:** read the setter's role at the time of the lift:
wrong as soon as the role changes, and ambiguous for a manager with trust
`admin`.

## How the open points of "The manager" were settled

**Id:** 2a7492c4-826b-437e-834b-8d1ba08c1a1f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** coordinator's ruling on the implementation, 2026-10-29 (#541)
**Revisit when:** docs/api.md §2.3 "The manager" says otherwise on any of these

The contract leaves these open; the hub does this:

- A manager with trust `admin` is an admin agent and is handled by ᵃ alone in
  `PATCH …/members/{id}`; `line:lead` applies to a caller without
  `members:admin` (and, on cards, without `tasks:admin`).
- Only setting a pause of a reviewer, tester, arbiter or coordinator, and
  changing its `reports_to`, wait for a human's `go`; lifting a pause does
  not, since a human agreed to the pause already.
- A pause a manager may not touch (a human's, an admin agent's, a manager's
  outside its reach) is `forbidden` with `details.scope: members:admin`, as
  ᵃ refuses another agent's pause; `not_in_line` stays for members outside
  the reach.
- An admin agent lifts an agent manager's pause but does not replace it. A
  human manager's pause is a human's pause: no admin agent lifts or
  replaces it (§5.3), on the membership, on an instance, and at the `go`
  of a consent request alike.
- A pause set by a manager who was removed since is no longer lifted by the
  manager above (the setter is not in its reach any more); humans and the
  owner still lift it.
- A manager whose trust is lowered to `guest` loses its rights as if it
  lost the role: every `line_consent` naming it is cleared for good and the
  pauses it set over those edges are lifted. Back at trust `member`, it does
  not get the old consents back, as the role coming back does not set them
  again (§6.2). So, as for removing the role, only a human lowers a manager
  to `guest`: an admin agent would otherwise end another owner's consent.
- The agent's owner lifts a manager's pause also when not a member of the
  project, answered `204` with no body, as `team` is.

**Rejected alternatives:** none in contention beyond the opposite reading of
each point.

## The depth check skips a boss that does not change

**Id:** 94c14cdf-2275-4586-bbdd-d38db2447fe1
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-29
**Revisit when:** chains longer than 8 no longer exist anywhere

`validate_assignment` checks the depth only when the named boss differs
from the member's current one (a join for an existing member passes its
current boss as `keeps_boss`). "Chains that already exist stay as they
are" (§2.3 "Depth"): a `PATCH` or a new-instance join that names the same
boss again moves nothing, and refusing it would break an otherwise valid
call on an old chain.

**Rejected alternative:** pass the existing membership as `member` in a
join, which also runs the cycle check and changed the answer of an
existing test (`cycle` before `differs_from_membership`).
