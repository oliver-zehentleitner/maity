# Agent instances

## A claim no instance can be named for is taken by the team's first caller

**Id:** 631e9211-e4e9-4352-88d2-426bec37b5d9
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-23 (agent instances, `docs/api.md` §6.5, §6.17)
**Revisit when:** the contract defines how a claim for a team with no resolvable instance lands, or `assign` takes its `instance` field (§6.18)

The hub stores the holding instance on the card (`card.claim_instance`,
the short id, not the credential id). Where a claim goes to an agent
member without a named instance and the team's rules do not resolve one
(the team has no active instance, or an expired claim moves to an
assignee under `free` with several instances), `claim_instance` stays
null and the first instance of that team to make any call takes it.
An admin's `claim` with a bare member id that leaves the choice open is
refused with `instance_required` instead, as §6.5 says.

**Reason:** the contract says a card is held by exactly one instance,
but before `assign` names instances some paths have no instance to
name. Taking it on the first call keeps the old behaviour of a claim
made on a member's behalf ("the holder's next call moves it to its
session") and never leaves a card held by nobody.

**Rejected alternatives:**
- Refuse those moves with `instance_required` — a team that lost all its
  instances could then not be given its own expired card back.
- Bind such a claim to the oldest active instance — a choice the hub
  would make for the owner, with no rule in the contract behind it.

## The team rulebook is set through the member PATCH with `team` alone, open to a non-member owner

**Id:** 90c28969-4f1b-4533-a0cd-62549d674cab
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-23 (`docs/api.md` §6.18)

`PATCH /projects/{slug}/members/{id}` with `team` is dispatched at the
top of the handler, before the member check, to `instances.patch_team`:
the human who owns the agent profile may call it without being a member
of the project; anyone else who is no member gets `not_found` as for any
project they cannot see; every other caller is `forbidden` with
`details.reason: humans_only`. A body that mixes `team` with other
fields is `invalid` (`details.fields.team: "alone"`) and changes nothing.

**Reason:** §6.18 makes the rulebook the owner's alone and lets an owner
who is no member set it, while every other field of the PATCH is a
project admin's. One endpoint carries both, so the membership check
cannot run first for every body. Keeping the path in `instances.py`
leaves the member PATCH itself to the hub's owner, who is restructuring
it for admin agents.

**Rejected alternatives:**
- A separate `…/members/{id}/team` endpoint — simpler routing, but the
  contract names the member PATCH.
- Applying a mixed body under both checks — it would half-apply when one
  of the two refuses, and the contract does not ask for mixing.

## A replacement moves the claims and the lead before the old credential is revoked

**Id:** 6eb3689f-e233-454b-b88e-3638d9ef219c
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-23 (`docs/api.md` §6.17)

In a `replaces` exchange the new credential is written, the replaced
instance's claims, assignments and place as lead move to it, and only
then is the old credential revoked (`revoked_reason: replaced`). The
shared revocation path clears `lead_instance` when the revoked instance
was the lead.

**Reason:** revoking first would clear the lead and emit a
`member_updated` with `lead_instance: null` just before the new
instance takes it, which a team under a `lead` rule would read as having
no lead.

**Alternatives:** none other was considered.
