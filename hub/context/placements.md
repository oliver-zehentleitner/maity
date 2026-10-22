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

