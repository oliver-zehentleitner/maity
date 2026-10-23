# Agent instances

## An agent's claim always names its instance; one that names none is held by nobody

**Id:** 9b49f9d7-20a6-4605-a4ef-a2fc19e2455a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** review of the agent-instances change, 2026-10-23 (`docs/api.md` §6.5, §6.17, §6.18)

Every path that gives an agent member a claim names the instance or
refuses: an admin's `claim` with a bare member id, and an `assign` that
moves an expired claim to a team, both resolve the instance (the named
one, the team's only one, or its lead under `distribution: lead`) and
otherwise answer `instance_required`, also for a team with no active
instance. `assign` takes the `instance` field of §6.18 for this.
`cards.holds()` fails closed: an agent holds a card only when
`claim_instance` is its own instance. A claim the upgrade could not
bind to an instance stays held by nobody until a human reassigns it.

**Reason:** the contract says a card is held by exactly one instance.
Letting the first sibling to call take an unbound claim meant any
sibling could take it silently — even a plain read bound it — and no
event named the instance that got it.

**Rejected alternatives:**
- The first caller of the team takes the claim (631e9211) — silent, and
  any sibling wins it with any call.
- Binding such a claim to the oldest active instance — a choice the hub
  would make for the owner, with no rule in the contract behind it.

## A claim no instance can be named for is taken by the team's first caller

**Id:** 631e9211-e4e9-4352-88d2-426bec37b5d9
**Type:** decision
**Status:** superseded
**Superseded by:** 9b49f9d7-20a6-4605-a4ef-a2fc19e2455a
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
`details.reason: humans_only`, an agent before any other check. A body
that mixes `team` with other fields is `invalid`
(`details.fields.team: "alone"`) and changes nothing. An owner who is no
member gets `204` without a body, since a non-member sees nothing of the
project; a member gets the member view, with the briefing only when it
holds `members:admin`.

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

## Upgrading to instances: what a rollback and old join links do

**Id:** 437034ac-37a4-4e69-a635-16b01596e7d7
**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** review of the agent-instances change, 2026-10-23 (migration `agent_instances_and_team_rules`)

The migration gives every existing credential a new random instance id.
A downgrade drops the ids, so a downgrade followed by an upgrade gives
every instance a new id; an address someone noted before the rollback
no longer resolves. A join link created before the upgrade carries
neither `new_instance` nor `replaces`; when it is for an existing member,
its exchange is refused with `instance_quota`,
which is harmless because join codes live one hour at most.

**Reason:** ids are never reused within a membership, and the migration
cannot know which id a credential had before a rollback; keeping the old
ids would need them stored outside the schema the downgrade removes.


## The team wake is chosen when the event is written and stored per team

**Id:** 7d24afac-b6b5-4d71-9211-517aa5821e64
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-23 (`docs/api.md` §6.18, §8.2)

`emit` picks the instances a `lead` or `next_free` team wakes and stores
them on the event as `wakes`: `{member id: [instance ids]}` for each
team the audience reaches by `member:` or `role:` whose rule narrows it,
an empty list when nobody of that team listened, and null when no team
was narrowed. A reader's instance is woken through `member:`/`role:`
only when its team is absent from `wakes` or it is in its list. The
project row carries `team_wake`, true while one of its teams has a rule
other than `all`, and only then does `emit` run the lookup.

**Reason:** §8.2 says the choice is made when the event is written and
recorded on it. Keying it by team lets a reader tell "my team was
narrowed and I am not chosen" from "my team wakes all" without reading
the team's current rule, which may have changed since. The event table
is the largest one and most projects have no narrowing team, so null
instead of an empty map and the project flag keep their cost at zero.

**Rejected alternatives:**
- Choosing at read time from the team's current rule — two instances
  polling at once could both be "next free".
- A flat list of addresses only — cannot express "narrowed, nobody
  listening" for one team next to an unnarrowed one.
- Looking up the project's teams on every emit — one more query per
  event for every project.

## `PATCH /me` pauses the calling instance; the resume shows the team's or its own pause

**Id:** a430ae96-2c24-439d-8cb9-d4646483fd77
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-23 (`docs/api.md` §5.2, §5.3, §6.17)

An instance's own pause is stored on its credential row, in the same
three columns as the membership's. `PATCH /me` sets it for the calling
instance only, also on a team of one; `PATCH …/members/{id}` with
`instance` sets or lifts one instance's pause, without it the
membership's. The resume packet's `membership.paused` shows the
membership's pause, or else the calling instance's own, so an agent of
a team of one sees what it saw before. A member's `presence` is the best
of its instances', an instance paused on its own counting below one that
is offline.

**Reason:** §5.3 says `PATCH /me` declares the calling instance's pause
and its siblings carry on. The contract names `membership.paused` as
where the agent learns of its pause but has no separate field for the
instance's own; showing either there keeps the CLI's pause notice
working unchanged.

**Rejected alternatives:**
- Keeping `PATCH /me` on the membership for a team of one — the same
  call would mean different things depending on the team's size.
- A new `me.paused` field — not in the contract.

## `instance_assigned` applies to cards assigned to the team, and an unset instance is refused only under `lead`

**Id:** 1476dae7-eac9-4e29-9f42-151978322677
**Type:** decision
**Status:** open
**Evidence:** inferred
**Source:** implementation session, 2026-10-23 (`docs/api.md` §6.5, §6.18, error table)
**Revisit when:** the contract settles whether `round_robin` refuses a claim while `assigned_instance` is unset

An instance's claim is checked against `assigned_instance` only when
the card is assigned to its own team. It is refused when
`assigned_instance` names another instance, and under
`distribution: lead` while it is unset unless the caller is the lead. An
admin's claim on a team's behalf names its instance and is not checked.

**Reason:** the error table refuses an unset instance under `lead` only;
§6.5 says that under `lead` and `round_robin` an instance claims only
cards assigned to itself. Under `round_robin` the hub sets the instance
on every assign, so an unset one only remains when no instance was free;
refusing it then would leave a card nobody of the team can claim. The
distribution rule describes "cards assigned to the team", so a card
assigned elsewhere or to nobody is claimed as before.

**Rejected alternatives:**
- Refusing an unset instance under `round_robin` too, as §6.5 reads —
  open until the contract says which text wins.
