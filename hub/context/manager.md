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
admin agent. Since #590, `POST …/tasks` and the import from a forge issue
run through the same `create_card`, so the manager's check for
`assigned_to` (`_require_assigner`) holds for both, and a change to it
changes both ways (§6.4, §6.14).

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

## An agent's owner moves its `reports_to` on a path of their own, to nobody, to a member they own, or by asking the other side

**Id:** 4a7342a5-50d1-4d38-bc6b-daa38413efd1
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §2.3 ("A human may always set the `reports_to` of an agent they own to null or to a member they own … whether or not they are a member of the project. Nothing else of the membership opens to them this way"); spq4's finding on #754 (seq 16437); the card tsk-fw3x5c13vq9g from the coordinator, 2026-10-30
**Revisit when:** the owner's own path gains another field (§2.3 "Nothing else of the membership opens to them this way"), or the pair of consent requests changes who may start it
**See:** manager.md#a-managers-pause-is-marked-by-a-column-not-by-paused_by — 8040236c-b8c0-41f2-b37c-47838835b447 — as of 2026-10-30
**See:** manager.md#a-cross-owner-reports_to-is-a-pair-of-personal-consent-requests-that-set-the-edge-at-the-last-go — 5d9be0ad-ef77-487e-b95a-1cf9ea2674d4 — as of 2026-10-30

`PATCH …/members/{id}` has the owner's path `_owner_sets_reports_to` before the ordinary rules, as
`_owner_lifts_line_pause` has: the caller is a human who owns the agent profile of the target, the body
is exactly `{reports_to}`, and the value is `null`, a member the caller owns (themselves, or another of
their agents in the project) or, since the pair of consent requests exists, a member of another owner: that
one is not applied but asks the boss's side (202, see the entry on the pair). Anything else falls through
to the ordinary rules, so another owner's member
is `forbidden` (`members:admin`) for a member and `not_found` for someone outside the project, and a caller
who holds `members:admin` is left to the admin's own path. What the path checks and does is an admin's:
`not_a_member` (naming oneself while outside the project), `guest`, `cycle`, `too_deep`; the `line_consent`
of the old edge ends; `member_updated`. A member of the project gets the member view, an owner outside it
`204` and nothing of the project (§1.3).

Withdrawing an open cross-owner request was not built when this path was (the hub had no such
request); the pair of consent requests has its own withdrawal rule now.

**Reason:** an owner should not need `members:admin` in a project to hang their own agent under
themselves or another of theirs, and an owner outside the project has no membership to get it from;
the contract opens exactly this and nothing else. A path of its own keeps the admin's rules untouched
and makes "nothing else opens" a property of the shape of the body.

**Rejected alternatives:**
- Letting any owner name any member at once: that is the cross-owner edge, which needs the other side's
  consent (§6.2); first the contract kept it out, then the pair of consent requests built the way it
  happens with that consent.
- Widening the ordinary path (`members:admin` OR owns the agent): the same call would then carry role,
  trust and areas too, and "nothing else opens" would depend on every field's check.

## A cross-owner `reports_to` is a pair of personal consent requests that set the edge at the last go

**Id:** 5d9be0ad-ef77-487e-b95a-1cf9ea2674d4
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §6.2 ("Across owners"), §3.1, §2.3 and the contract change that adapted them (#769); the maintainer's go and the coordinator's decisions on card tsk-3jdqtppzmtdb, 2026-10-30 (the personal request instead of a project route for a human outside the project; the owner's own path included; existing edges stay)
**See:** manager.md#an-agents-owner-moves-its-reports_to-on-a-path-of-their-own-to-nobody-to-a-member-they-own-or-by-asking-the-other-side — 4a7342a5-50d1-4d38-bc6b-daa38413efd1 — as of 2026-10-30
**Revisit when:** an organisation's agents get their own owner rules (§6.26), or the consent flow gains a third party, or a manager's consented change (`line_change`) and a placement's new profile (§15.6) are made to ask as the others do

`cross_owner.owners` decides: the subordinate is an agent and the boss's side (an agent's owner, or a human)
is not its owner. `cross_owner.file` then files one `consent` request per owner still to consent, as a
**personal request** to that human in person (`to: human:<id>`, a proposal of kind `cross_owner_reports_to`),
the boss's side first, titles and summary as §6.2 gives them; the caller who is one of the two owners
counts as consenting and asks only the other. The requests of one edge name each other
(`proposal.requests`), and `reports_to` stays as it is while they are open. `settle` does the rest: a `go`
that leaves none open validates the edge as it is then (guest, cycle, depth) and applies it with the
asker as actor and the answering human as approver, `line_consent` set when the boss held the role
`manager` at filing and still does; a `no` or a withdrawal withdraws the other (`refused`, or the hub's
own reason it was withdrawn for); a failed check leaves the request open for a `no`.

The paths that start it: a `PATCH` with `members:admin` (202, the other fields at once, the boss side's
request the answer); the owner of the subordinate without `members:admin`, member or not (`_owner_sets_reports_to`,
for a foreign boss, `asked_by_human` when they are no member); an admin agent's patch after its owner's go (§2.3 ᵃ), which asks both;
and a join, which starts the membership with `reports_to: null` and asks the boss's side at the exchange
with the join's creator as asker. A further `PATCH` of the member's `reports_to` withdraws the open
requests (`superseded`), an agent that did not ask is refused (`pending_consent`), the removal of either
member withdraws them (`member_removed`).

Who reads and withdraws: either owner of the edge, member of the project or not, reads and withdraws
**both** requests of the pair, also the one addressed to the other owner, under `/requests/{id}` (and on
the project route as a member without any scope), and answers only the one addressed to them; a request
asked from outside the project is also in the asker's `GET /requests` (`asked_by=me` included), and only
that kind: other requests with `asked_by_human` (an organisation's) are not. A `go` on an edge that
already exists (an older edge, or the same boss named again after it became a manager) still sets
`line_consent`, though `reports_to` does not change.

**Reason:** an agent reports across owners only with a human's consent, and a human who owns one side
need not be a member of the project. A personal request already reaches such a human, is answered where
every personal request is, and opens no call into the project.

**Rejected alternatives:**
- A normal project request that a human outside the project reads and answers by the project route (the
  first reading of §6.2): a new access path into a project for non-members, next to the personal
  requests the hub already has; the contract was changed to the personal route instead.
- One request for the pair with two answers: each owner answers their own request (`addressee_only`), and
  a `no` on either must be visible as a refusal by that owner.
- Letting an owner see only the request addressed to or asked by them: the contract gives both owners
  the withdrawal of both requests (§6.2 "Pending"), and a withdrawal one cannot read would be blind; the
  reviewer's finding on #772 (the owner outside the project could not reach the sibling).
- A column naming the pair: the proposal carries its sibling ids, and nothing queries by them but the
  hub's own withdrawals.

**Not covered, and why:** a manager's consented change (`line_change`) and a placement's new profile
(§15.6) still set a cross-owner `reports_to` directly; the contract names the join, the `PATCH` and the
owner. Existing cross-owner edges stay as they are (alpha, no migration of data).

## A join whose creator left the project asks nobody for the boss's side

**Id:** 6cdf91ec-75d5-4b73-b095-8b439a8529af
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** `routes/joins.py` `_ask_boss_side`; the contract (§3.1) says the creator's creating the profile is the subordinate owner's consent and is silent on a creator who is gone
**Revisit when:** the contract says whom a join asks for the boss's side when its creator is no member any more
**See:** manager.md#a-cross-owner-reports_to-is-a-pair-of-personal-consent-requests-that-set-the-edge-at-the-last-go — 5d9be0ad-ef77-487e-b95a-1cf9ea2674d4 — as of 2026-10-30

A join with a cross-owner `reports_to` starts the membership without the boss and asks the boss's side at the
exchange, with the join's creator as asker. When the creator is no active member by then, no request is
filed and the member stays without a boss; an owner or admin can set it with a `PATCH` afterwards, which asks
as for any cross-owner edge.

**Reason:** the request needs an asker to read and withdraw it, and the asker is a membership of the
project; a creator who left has none. That is what the code needs; no maintainer was asked whether a
different rule was wanted, so the evidence is the code's own.

**Rejected alternatives:**
- Filing the request as the human creator would (`asked_by_human`, as for an owner outside the project):
  possible for a human creator, not for an agent, and nothing asked for it; not built.
