# Instances

## Several agents may work under one handle as instances of one membership, each individually identifiable

**Id:** 98151697-d9dc-4491-8719-2d3e5064f01f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decisions of 2026-10-22, in his inbox; contract in `docs/api.md` §6.11
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
