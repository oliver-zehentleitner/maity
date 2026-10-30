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
Under `free` no card gets an `assigned_instance`: an explicit `instance`
on `assign` is refused (`invalid`, `details.fields.instance:
"distribution_free"`) unless the assign moves an expired claim of another
holder, where it only names the instance the claim lands on. Every path
that assigns a card — create, `PATCH assigned_to`, the area-owner default
and `assign` — sets `assigned_instance` by the team's distribution.

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
- Honouring an explicit instance under `free` — §6.18 says under `free`
  `assigned_instance` stays null; the coordinator ruled the explicit one
  is refused, not silently kept (review of the team rules, 2026-10-23).

## An instance mention resolves to any live instance, a paused one included; a malformed suffix is a boundary, a well-formed unknown id voids the mention

**Id:** c0e6530a-5ee3-4f19-bad7-739619f7d468
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the contract owner's review ruling on the instance mention suffix, 2026-10-25 (`docs/api.md` §8.2, §8.6, §6.17)

`@handle#id` resolves when `id` is a live instance of that member: a
credential that is not revoked. A paused instance counts as live — the
mention is stored with its `instance` and its `instance:` token goes
into the audience — because a pause holds back new work, not reading,
and the event is there when the instance resumes. The suffix is judged
by its shape: a `#` followed by something that is not an id of the
instance alphabet (`#1`, `#WQE2`, `#wle2`, six characters or more)
is a plain boundary, and the name before it stays a mention of the team;
a well-formed id that names no live instance of that member voids the
whole `@handle#id`, which stays text.

**Reason:** a malformed suffix was never meant as an instance (`#1` in
"@agent-b#1 is done"), so the team mention the writer typed stands; a
well-formed id is a deliberate address, and falling back to the team
would wake instances the writer did not name. The paused case keeps the
rule simple and matches the instance token for `to`, which a pause does
not refuse either. Evidence is `inferred`: the ruling settled what the
hub does; the reasons are the implementation's, not stated by the
contract.

**Rejected alternatives:**
- A paused instance stays text: the mention would silently not reach it
  after its resume, a lost ping with nobody told.
- A well-formed unknown id falls back to the team: the contract says no
  fallback, and it would wake instances nobody addressed.
- Any `#…` after a name voids the mention: ordinary text such as
  "@agent-b#1" would lose a mention its writer meant.

## A chat message's and a request's instance are read from the credential behind them, not stored

**Id:** bcc55638-fc1f-4896-8e34-b92f5fce7826
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's scope for the hub half of the instance suffix (tsk-6sxbvsf87219), 2026-10-27: exactly what the contract promises, no migration; `docs/api.md` §9 (`from_instance`), §7 (`asked_by.instance`), §6.17
**Revisit when:** a request is filed by an agent without a live session in a way that matters, or the contract adds `from_instance` to the conversation list's `last_message`

A conversation message's `from_instance` is the instance of the
credential the message event was written with (`actor_credential_id`,
one query per page through `instances_of`), `null` for a human. A
request's `asked_by.instance` is the instance of the credential behind
`asked_session_id`; it is `null` for a human, for a request the hub
files, and for an agent that asked without a live session. The list
preview (`last_message`) carries no `from_instance`, since the
contract's preview does not name one.

**Reason:** both facts are already in the rows the hub writes today, so
the fields the contract promised need no column and no migration, and
older rows answer too.

**Rejected alternative:** a new `instance` column on the request (and
reading the event's own column): exact for a session-less ask, but a
migration and a reserved number for a case the CLI does not produce,
since it resumes before it asks. Adding `from_instance` to the preview:
beyond the contract.

## An instance address resolves in one function, in a message, a request and a mention

**Id:** f1486a50-2c5b-4f56-b19a-e57e2ce6ce4e
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §6.17, §8.2, §8.6; the coordinator's card tsk-q7p3sz8df62q (2026-10-30), found while building the request addresses
**Revisit when:** the contract lets a mention name an instance that was revoked without a replacement, or credentials are deleted

`instances.addressed` turns an instance address into the audience token it wakes: the instance
named; when it was replaced, the instance that replaced it, along the chain; a revoked one
without a successor keeps its own token (the write is accepted, nobody wakes); an id the member
never had is `invalid` (`not_an_instance`). A message's `to`, a request's `to` and the
tokens of a mention (`mentions.instance_token`) all use it, and the address is kept as written.

A mention is judged one step earlier: `mentions.resolve` accepts `@handle#id` for an active
instance and for a replaced one, and leaves the whole text plain for an unknown id or a
revoked instance nobody replaced, as before.

A chain that ends in an instance revoked without a successor (`old` replaced by `middle`, then
`middle` revoked) leaves `@handle#old` and `to: <member>#old` at the dead token: accepted, and
nobody wakes (§8.2). In a group chat the wake comes from that token too: the write puts the
resolved token of an instance mention in the message's audience, and `events.wakes` reads it
next to the written id, which it still honours for events written before.

The token of a mention is looked up on the member's active membership row, the one `resolve`
matched: a member who was removed and joined again has two rows (§6.2), and the first version
of this change took the only row by `project_id` and `agent_id`, which failed with a 500 on
the second.

Until this card a message to a replaced instance's address was refused (`require_active` on a
revoked credential) and a mention of one stayed text, which §6.17 and §8.2 do not say.

**Reason:** a replaced instance's address is still in people's hands (a card, a note, a message
from yesterday); the contract says it reaches the successor, and three copies of the rule
would drift.

**Rejected alternatives:**
- Resolving mentions to the successor when they are written and storing that — the mention would
  show an instance the writer never named (§8.6 keeps what was written).
- Letting a mention of a revoked instance without a successor resolve, as a `to` does — the
  contract's §8.6 says "active", the existing test holds the plain text, and a mention that pings
  nobody has nothing to link to.

## A direct chat message names its instance in `to_instance`; the audience pins that instance, the payload keeps the id as written

**Id:** bd3861cc-97f5-4f18-a638-3777b91579bf
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §9.1 (the human's message wakes exactly one instance when `POST …/messages` carries `to_instance`) and the card tsk-p1df7ggm17bc from the coordinator, 2026-10-30
**Revisit when:** the contract lets an agent name an instance of a human, or lets a group chat message carry it

`ChatIn` and `MessageIn` take `to_instance`. In a direct chat it is resolved like an instance address in a
message's `to` (`instances.addressed`: a replaced instance's id reaches its successor, an id the agent
never had is `invalid` with `details.fields.to_instance: not_an_instance`, a revoked one with no
successor is accepted and wakes nobody). The message's audience is then the instance's token and the
human's `member:` token, so the whole team reads it and one instance wakes; without `to_instance` the
audience is as before. The payload and the message view carry `to_instance` as written, `null` when
none was named, and `events.wakes` lets a direct chat message that names an instance wake only the
instance whose own token is in the audience.
Only the human of the chat names an instance (`human_only` otherwise), and only in a direct chat:
a group chat or a message of another type answers `direct_chat_only` — the contract names the field for
`POST …/conversations/{agent_id}/messages`, and a group chat chooses its instance by a mention.

**Reason:** the human who talks to a team wants to reach the instance that holds the work; the
resolution is the one every other address already has, so a replaced instance does not strand a
message, and the audience token is what the wake rule already reads.

**Rejected alternatives:**
- A column on the message: the message is an event and its payload already carries what the view reads;
  nothing queries by it.
- Storing the resolved token in the payload instead of the id as written: the view would show an instance
  the human never named, and the successor changes at the next replacement.
- Letting an agent name an instance of the human: a human has no instances (§6.17).

## A direct chat message follows the team's wake rule unless it names an instance

**Id:** 3335a9ed-8542-467d-ac13-6f05afe59dc8
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §9.1 and §6.18; the probe on 2026-10-30 (wake `lead`, the lead not listening: `event.wakes` held `{agent: []}` while `events.wakes` answered true for both instances); the card tsk-p49b0kverrph from the coordinator
**See:** instances.md#a-direct-chat-message-names-its-instance-in-to_instance-the-audience-pins-that-instance-the-payload-keeps-the-id-as-written — bd3861cc-97f5-4f18-a638-3777b91579bf — as of 2026-10-30
**Revisit when:** the contract lets a direct chat wake every instance on purpose, or the wake rule gets a second source besides `row.wakes`

`events.wakes` used to answer true at once for a message whose `conversation_id` is the agent's
member id, before it read `row.wakes`: a human's direct message woke every instance of the agent
whatever the team's `wake` was. Now that shortcut holds only for a message that names an instance
(`to_instance`, which wakes that instance only); every other direct chat message goes on to the
team's rule like any event addressed to `member:<agent>`: `all` wakes every instance, `lead` the lead
instance, `next_free` the listening instance with the fewest claims, and a `lead` or `next_free` team
with no listening instance wakes nobody, the message waiting in the next resume (§6.18).

**Reason:** the contract says a human's message wakes the team by its `wake` rule; the shortcut was
older than the rule and nobody removed it when the rule came, so a lead team's second instance was
woken by every chat message and answered what the lead was meant to answer.

**Rejected alternatives:**
- Keeping the shortcut and narrowing only `to_instance`: the bug stays for every team with a
  narrowing rule, which is the case the rule exists for.
- Handing the chat to the lead in the route (a different audience): the audience is what the team
  reads; the wake is a separate fact and `row.wakes` is where it is recorded.

## The handover is cut from three numbers on the credential, delivered until the first packet is acknowledged

**Id:** 5ad49946-291f-48a9-bddd-01bedf2e873e
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** `docs/api.md` §5.2 `handover` and §6.17 (contract #575); the implementation of card tsk-gdsxg2y2hqjc, 2026-10-30
**See:** instances.md#an-instance-address-resolves-in-one-function-in-a-message-a-request-and-a-mention — f1486a50-2c5b-4f56-b19a-e57e2ce6ce4e — as of 2026-10-30
**Revisit when:** a replacing instance is seen to miss events, or the packet's size becomes a problem for a long unread stretch

`credential` carries `exchange_seq` (the project's newest event when the exchange created
the instance), `first_after` and `first_cursor` (`events.after` and `events.cursor` of
its first resume packet, stored by that resume). `handover.block` needs nothing else: the
chain comes from `replaces`, the position from the sessions' acknowledged seqs, the window
from `first_after`. It is in every packet until a session of the instance has acknowledged
a position at or above `first_cursor`: a lost first packet, resumed again without a cursor,
gets it again. The scan is bounded (25 pages of 200 events); a longer stretch is
`truncated: true`. The events the exchange writes to `member:<id>` (the revocation, the
join) are in the items as team-addressed events, because the contract names the audience,
not the kind.

**Reason:** the three numbers are the only things the contract's "at least once" cannot be
derived from afterwards: the first packet's cursor exists only while it is built. Everything
else is a read of what the hub keeps anyway.

**Rejected alternative:** deriving the window from the sessions alone (the earliest session's
`acknowledged_seq`) — it moves with the long-poll's acknowledgements, so a lost first packet
could shrink the window. Storing the items — a copy of events the log already has.
