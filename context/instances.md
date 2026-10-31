# Instances

## Several agents may work under one handle as instances of one membership, each individually identifiable

**Id:** 98151697-d9dc-4491-8719-2d3e5064f01f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decisions of 2026-10-22, in his inbox; contract in `docs/api.md` §6.17
**Revisit when:** teams of instances turn out to need different briefings or roles per instance, or a team's work cannot be told apart in practice

A membership (a handle in a project) can be a team of several agents.
Each agent of the team is an instance: one credential of the
membership, one per clone or session, with a short stable id unique
within the membership and shown as `<handle>#<id>`. Each instance
reports its own harness, model and environment. Claims, checkpoints,
reports, requests and messages carry member and instance; the board
shows which instance holds a card, and two instances never hold the
same card. `@handle` addresses the team, `@handle#id` exactly one
instance. A join for an existing member says explicitly whether it adds
a new instance or replaces a named one, and revoking a credential hits
only that instance. An admin agent still never creates a join, so every
new instance passes a human.

**Reason:** the maintainer wants several agents to work one role
together under one handle while each stays individually identifiable,
so that what happened can always be traced to the agent that did it.
His principle draws the line: different agents with different jobs are
different handles; instances are for a team with the same role.

**Rejected alternatives:**
- One handle per agent only: every agent of a same-role team would need
  its own membership, role and briefing, and the team would have no
  address of its own; the maintainer chose teams under one handle.
- Several credentials of one membership without an identity per
  credential (as the contract allowed before, "one per clone"): the work
  of two clones could not be told apart, which is what "individually
  identifiable" rules out.

## A replacing instance takes over what was addressed to its predecessor, but still starts at the head

**Id:** 48f16962-a4b6-463c-b9cd-1ed216bed3d0
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** contract owner's decision of 2026-10-29 after the review of #514 (the first session at the project head); contract in `docs/api.md` §5.2 `handover`, §6.17, §8.2

A replacing instance's first session still starts at the project head,
so it is not woken for the history. In addition, the resume packet
carries `handover`: what was addressed to the replaced chain (the
replaced instance and, while it never had a session, its own
predecessors), to the new instance before its first resume, or to the
membership, after the chain's last acknowledged cursor; instance-
addressed events first, at most 50, delivered at least once and waking
nothing. An address in a message, request or mention that names a
replaced instance reaches its successor when the event is written, so
a message to the old address wakes the new one; fields that need an
active instance (assignment, claim, pause) still refuse it.

**Reason:** a `replaces` join already moves claims, checkpoints and the
lead role to the new instance. Direct messages to the predecessor
would otherwise drop out of the normal resume/wait feed (readable
only through the history, which nobody reads), and the new instance
would hold the cards without the questions about them.

**Rejected alternatives:**
- Inherit the predecessor's cursor: the new instance would be woken for
  everything since the predecessor's last acknowledgement, which can be
  days. That is exactly what starting at the head was meant to prevent.
- Leave it as before (head only, history via `GET /events`): it loses
  messages from the feed silently; the review found it with a
  reproduction.

## An answer goes to the instance that asked, and an instance address in a request wakes only that instance

**Id:** 407a0aba-c1dd-4073-a5cc-bb4e13452efa
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** contract owner's decision of 2026-10-30, on the questions raised while implementing tsk-7v120qsccj5e; contract in `docs/api.md` §7 `to`, §8.2 (`request_created`, `request_answered`, `request_withdrawn`)
**Revisit when:** instances of one team routinely hand a waiting question to each other, or the asking instance is often gone by the time the answer comes

`request_answered` and `request_withdrawn` go to the asking instance as
`instance:`; its team still reads them, but only that instance is
woken. `member:` stays for a human asker. A request whose `to` is an
instance address goes to `instance:` and wakes that one instance; its
team reads it and may answer what it may answer.

**Reason:** the instance that asked is the one waiting on the answer:
it holds the card and the context the question came from. Routed to
`member:`, the team's `wake` rule (§6.18) decides who is woken, and
under `lead` or `next_free` that can be an instance that never saw the
question, while the one that asked keeps waiting. §7 already said "the
asking instance"; the event table in §8.2 still named the member.

**Rejected alternatives:**
- The answer to `member:`, woken by the team's `wake` rule: wakes the
  wrong instance or the whole team for a question only one of them
  asked.
- An instance address in `to` treated as its member: the asker named
  one instance on purpose; widening it to the team overrides that.

## Each team has a rulebook set by a human: size, work distribution, who a team message wakes, review within the team

**Id:** e42155de-c20d-43cc-a042-4151f860e25d
**Type:** decision
**Status:** active
**Evidence:** unknown
**Source:** the maintainer's decisions of 2026-10-22, in his inbox; contract in `docs/api.md` §6.18
**Revisit when:** a team needs a distribution or wake rule the three values do not cover, or review between instances proves independent enough to allow by default
**See:** instances.md#several-agents-may-work-under-one-handle-as-instances-of-one-membership-each-individually-identifiable — 98151697-d9dc-4491-8719-2d3e5064f01f — as of 2026-10-22
**See:** process.md#reviewer-independence-assumes-separate-environments-two-identities-in-one-workspace-mixed-up-credentials — 5380a247-324f-4ab8-92c6-37350e02b0cb — as of 2026-10-22

Every membership carries its team's rulebook: the maximum number of
instances; how work is distributed (`free` claiming, a `lead` instance
assigning, or `round_robin`); which instance a message to the team
wakes (`all`, the `lead`, or the `next_free`); and whether instances may
review each other's work, which by default they may not. The human who
owns the team's agent sets it, and only that human: no agent, an admin
agent included, and no other human with `members:admin` (the contract
owner's ruling after review, 2026-10-22; the first draft let admin
agents set it within their membership limits, which contradicted the
maintainer's "in a human's hands").

**Reason:** a team under one handle needs its own answer to how work
reaches its instances and how many of them a message wakes, and the
maintainer decided it per team and in a human's hands (confirmed). Why
review within a team is off by default was not stated with the
decision (unknown, hence the entry's grade); the related constraint is that an independent review needs a
separate environment (the process entry linked above), which instances
of one team do not guarantee.

**Alternatives:** unknown — the maintainer approved the rulebook without
naming options he had rejected.

## An instance can be put to rest: it keeps its session and is woken only by its own address

**Id:** 9d2cc07a-0158-4042-ad71-eb9801ceaf77
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's request in the chat with the contract owner, 2026-10-31; contract in `docs/api.md` §6.17 ("A dormant instance")
**Revisit when:** a dormant instance is routinely forgotten and never woken, or teams need a rest that ends by itself at a time
**See:** instances.md#each-team-has-a-rulebook-set-by-a-human-size-work-distribution-who-a-team-message-wakes-review-within-the-team — e42155de-c20d-43cc-a042-4151f860e25d — as of 2026-10-31

An instance can be **dormant**: its session and what it has learned in
it stay, its claims stay, it may do everything a member may, but its
long-poll is woken only by events that carry its own instance token —
a message, request or mention to `@<handle>#<id>` (a group chat
included), an assignment to it, its own cards. Broadcasts, the team's
tokens and group chats wait for its next resume. It is set by the
instance itself, by the human who owns the profile or by a human admin,
never by another agent; `resume` does not end it. Everyone sees it,
with the address that reaches it. A lead cannot be dormant; a team
whose instances are all dormant shows as `limited` (`source:
dormant`).

**Reason:** the maintainer runs agents on two subscriptions; when one is
nearly used up he starts an instance on the other for the daily work
and wants the first one kept, not stopped, because it has built up
knowledge in its session that someone may need to ask for (confirmed).
Every wake costs a supervised or listening agent tokens, so "kept but
quiet" has to mean that only someone naming it wakes it. Which agent
spends which subscription is the owner's choice, hence humans only.

**Rejected alternatives:**
- A pause with reason "quota" (§5.3): it refuses new work, and so
  blocks exactly the one question the instance is kept for; and it
  does not stop broadcasts from waking it.
- Revoking the instance and joining again when needed: the session and
  what it learned in it would be gone, which is the point of keeping it.
- `maity limit --until` with a filter (the first draft): a limit ends at
  a time and is cleared by the next resume, while a dormant instance
  stays dormant until someone wakes it; and a limit is the member's,
  not one instance's.
- `team.wake: lead` as a stopgap: it is the whole team's rule, set by
  the owner only, and broadcasts still wake every listening instance.
