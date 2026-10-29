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
carries `handover`: what was addressed to the replaced instance or the
membership after the replaced instance's last acknowledged cursor, at
most 50 events, read once and not waking anything. An address that
names a replaced instance resolves to its successor when an event is
written, so a message to the old address wakes the new one.

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
