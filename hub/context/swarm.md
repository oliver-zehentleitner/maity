# Swarm

## The window's facts are gathered once and folded per reader

**Id:** 6c51ce44-f209-4ed6-8886-a67334ece18c
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-25 (the swarm page)
**Revisit when:** the hub runs more than one replica (each keeps its own window), or a project's window gets slow to gather

`swarm.window` reads a project's window once into raw facts: each card done
with its last holder and day, each review with its reviewer, each merged pull
request with the members whose cards link it, each duration sample with its
member, each with its UTC day. The window is always the longest one, 90 days,
gathered once per project; `swarm.fold` cuts it to the reader's `days` and
turns it into `members` and `totals`: everyone for members, agents only for
a public page. The raw facts are kept in process for up to an hour and never
past their UTC day; `live` is read on every call. One window per project bounds
the work: a visitor varying `days` reads the same gathering, not ninety.

Since 2026-10-30 (contract #697) the members read the statistics as a section of
the project's Overview, and the public swarm page with its `policy.swarm_public`
is gone. The agents-only fold stays for a public project's page (§16.9, §6.22),
which shows the statistics reduced and comes with the public pages
(tsk-w89mspg3gwx1); until then only members' folds are made.

**Reason:** a public page must recompute the totals and the day series over
agents only, so that a human's contribution appears nowhere on it (§6.22).
Folding the same facts twice keeps both pages consistent and costs one read.
The contract allows the window part to be an hour old; one process keeps one
copy, as the other in-process caches of the hub do.

**Rejected alternatives:**
- A window per `days`: up to ninety cold gatherings per project and hour,
  each reading every merged observation of the project.
- Only a few public windows (7, 30, 90): the contract allows any `days`.
- Two queries per counter, one for each page: twice the reads, and two
  derivations that could drift apart.
- Subtract the humans' share from the full totals: a pull request linked by a
  human's card and an agent's would be subtracted although it counts for
  the agent.

A contribution with no member (a card closed without a holder, a holder gone)
counts in the members' totals and not in the public ones: it is no agent's.
