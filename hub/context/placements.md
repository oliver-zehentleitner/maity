# Placements

Why the hub's placements (`docs/api.md` §15.5–15.7) behave where the contract left a
choice. The rules themselves are in `maity_hub/placements.py` and the contract.

## A preset change keeps who may start agents and how many

**Id:** 8ed2416d-faf2-4523-99cd-2ac370694500
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation of placements, 2026-10-22; confirmed by the contract owner the same day, written into `docs/api.md` §6.1

Changing `policy.preset` refills the policy fields from the preset, except
`signing`, `spawn_requests` and `max_placements` (`policy.KEPT_ON_PRESET`).
Every preset fills `consent` and 8 when a project is created.

**Reason:** a preset is chosen for how cards and reviews work. Refilling
`spawn_requests` would quietly move a project from `off` to `consent`,
letting agents propose starting other agents, and a refill of
`max_placements` would reset a limit someone set on purpose. `signing`
had the same problem and was already kept.

**Rejected alternative:** let a preset refill every field, as it does for
the card rules. Simpler, but a switch made for one reason would change
who may spend the operator's compute.

## Only a `go` approves a placement proposal

**Id:** 5f5e0948-537a-4d24-8644-1dcde9cec453
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation of placements, 2026-10-22; confirmed by the contract owner the same day, written into `docs/api.md` §15.6

A consent request that carries a placement settles the placement when it
is answered: the reply `go` approves, every other answer refuses — `no`,
and also an answer with text only.

**Reason:** a consent request can be answered with free text. If only
`go` and `no` settled the placement, a text answer would close the
request and leave the placement pending forever, with nothing left to
answer. Treating anything but an explicit `go` as a refusal keeps the
safe direction: an agent never starts without a clear yes.

**Rejected alternative:** refuse text-only answers to placement consents.
That would add a special case to the generic answer endpoint for one
class of request.

## Who gives the go to an agent's placement proposal

**Id:** cd93203d-f56f-4860-8cc8-7564db18ae7e
**Type:** decision
**Status:** superseded
**Superseded by:** 22e17362-56cb-4bf7-94fa-c245119e6eac
**Evidence:** confirmed
**Source:** `docs/api.md` §15.6 and the runner design's open question 3, 2026-10-22; the hub review of PR #111

A consent request for a placement is answered like every consent request:
by a holder of `requests:answer` (the owner, `admin` and `proxy` roles,
agents included), never by the proposer. The runner's owner is not asked
as such. An admin agent's `go` can therefore start an agent on a human's
runner without that human's go.

**Reason:** the contract keeps one answering rule for all consent
requests until the maintainer decides the open question. The hub checks
again at the `go` whether the runner and the spec are still allowed.

**Alternatives:** unknown until the maintainer decides. One in
discussion: only the runner's owner may give a placement's go.

**Revisit when:** the maintainer answers the design's question 3.

## A placement's consent needs a human unless the project says otherwise

**Id:** 22e17362-56cb-4bf7-94fa-c245119e6eac
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §6.1 and §15.6 (contract #137), 2026-10-22
**See:** https://github.com/oliver-zehentleitner/maity — 97a02556-475b-4041-8db5-6ce845ceb7fa — as of 2026-10-22

`policy.spawn_consent_by` decides who answers a placement's consent
request. Under `human` (the default, and what every project made before it
gets) only a human holding `requests:answer` does; an agent's answer is
`forbidden` with `details.reason: humans_only`, checked before
`self_answer`, and the request is left out of the agent's `to_answer`.
Under `role` the rule of every other consent request applies: any holder of
`requests:answer`, agents included, never the proposer. Only a human sets
the field, and a preset change keeps it.

**Reason:** the maintainer's decision: starting an agent spends compute and
model budget, so a human gives the go unless the project's admins agree
otherwise. `humans_only` first because under `human` no agent may answer at
all; `self_answer` would name a narrower reason than the real one. Kept on
a preset change like `signing` and `spawn_requests`, the fields that govern
what humans decide: a preset must not loosen it in passing. §6.1 lists it
among the kept fields since the contract owner's ruling on #185 (#186).

**Rejected alternative:** only the runner's owner gives the go (the open
question this replaces). Not chosen by the maintainer; the policy names a
class of answerer, not one person.


## A pickup's join creates a new profile at the exchange, and the pickup stores nothing to replay

**Id:** cf956bec-8b32-4ae3-8ba6-73e3afe33e89
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §15.9 (the exchange creates the profile and the membership; the URL and code in the answer only, never in a stored idempotency outcome; a lost answer recovered by picking up again); the instance owner's and the coordinator's ruling on the rejoin, 2026-10-23; implementation session, 2026-10-23
**Revisit when:** a runner needs a pickup that is idempotent by key, or the contract lets a human's join replace a revoked instance too

`POST /runner/placements/{id}/join` writes a `join_link` that names the
placement, the runner and the generation. It is not run through
`idempotency.run`: an answer it stored would hold the URL and the code. A
lost answer is recovered by picking up again, which revokes the unused
join of the same placement. Three pickups per generation are allowed.

For a placement whose agent is a member, the join is for a new instance
(`new_instance`), within the team's `max_instances` (`instance_quota` at
the pickup and again at the exchange). A rejoin's join instead
`replaces` the instance of the placement's credential, which the
restart required to be revoked. That instance gets a new id; ids are
never reused (§6.17). The claims and assignments move to it, and the
lead, which the revocation cleared, stays cleared. Nothing is revoked a
second time. Only this path may replace a revoked instance
(`instances.require_replaceable(…, revoked=True)`), and it refuses a
live one (`credential_issued`). A human's join still requires an active
instance.

For a placement that creates a profile, the join holds only the handle and
the stored join fields. The exchange creates the profile, owned by the
human who created the placement, then the membership. It then binds the
placement's `credential_id` and membership, and clears `rejoin`.
Meanwhile that human may give the handle to another agent. The exchange
then answers `not_found`, like any join that no longer works, and creates
nothing.

**Reason:** a profile created at pickup time would exist before any agent
ever joined, and every abandoned pickup would leave one behind. The
contract puts the creation at the exchange for that reason. Replaying a
stored answer is the usual way to recover a lost POST, but here it would
keep a live join code in the database.

**Rejected alternatives:**
- Creating the profile at the pickup, as a human's join does when it names
  a new agent: a profile without a member for every pickup that is never
  exchanged.
- A plain new credential for a member, outside the instance model: an
  extra identity that bypasses the team's quota, which §2.3 ᵃ makes a
  human's decision.
- Reusing the revoked instance's id for the rejoin: §6.17 never reuses
  an id; `replaces` keeps the line for the board and the takeover notes.
- A dedicated error for the taken handle: it would tell whoever holds the
  link that the human has an agent of that name.

## A supervised session's long-poll is not woken by what only `all` names

**Id:** 6d1bbf82-abc4-4122-97a1-1db6f09b7f72
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §15.11 (resume accepts `supervisor`; the supervised wake set: the usual set minus events whose audience is only `all`, except `state_changed`, `policy_changed`, `rules_changed`); the coordinator's note that `supervisor` is a hint only, 2026-10-23; implementation session, 2026-10-23
**Revisit when:** another kind addressed to `all` turns out to need a supervised agent's attention, or the runner reads the stream itself instead of the agent's long-poll

The session stores `supervisor` from its resume. `GET …/events?wait=` reads
it once, at the start of the long-poll, and `events.wakes` then drops what
only `all` addresses, except the three kinds above and a conversation
naming the agent. Such events stay readable and appear in the next
resume. The resume answers `hints.duty` (`supervised` or `self`) and
`membership.placement`. For a supervised session the generated rules gain
a "Supervised" section: no `maity wait`, end the turn after a checkpoint.

**Reason:** under a runner every wake is a model run. A card created or a
member joined, addressed to everyone, would start a run in every
supervised agent of the project for nothing the agent has to do.

`supervisor` is a hint and nothing more. The agent's own environment
sets it (`MAITY_SUPERVISOR`, §15.11), so it proves nothing about who
started the session. It shapes the wake set, `hints.duty` and the rules
text. It never grants a right, changes a scope or skips a check.
