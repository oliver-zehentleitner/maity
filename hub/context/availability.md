# Availability

## Availability is computed on read; the announced state is stored, and a sweep notices what time alone changes

**Id:** 240dae0b-9ea9-4cbb-a447-5ca3d39b1f38
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-23 (the availability slice)
**See:** https://github.com/oliver-zehentleitner/maity — 10798a45-310b-4c30-859f-30fea2454ece — as of 2026-10-23
**Revisit when:** a second replica runs (each would sweep the same projects), or one sweep takes longer than its interval

Every member view computes `availability` from the row as it is: pause,
stored limit, the owner's absence, presence. The membership also stores
the state the hub last announced, since when, and when the current outage
began. `reconcile` compares the two under the project lock and emits
`member_availability_changed` at an outage's start and end. It runs in
every request that changes an input (a limit, a pause, a resume, a
runner's report, the absence), and a worker thread runs it for every
project once a minute, which also clears passed limits and emits
`member_limit_ended`.

**Reason:** some ends of an outage come with no request at all: a limit's
`until` passes, an agent's session goes away. Computing on read keeps the
view right between sweeps; the stored state is what lets an outage be
announced once, gives `since` a stable value and gives the 24-hour lease
bound its start. The worker fits the single replica V1 runs, as the
probe's does.

**Rejected alternatives:**
- Compute only, store nothing: nothing to compare against, so nothing to
  announce once, and `since` would move with every read.
- Store the state only where a request writes it: a passed limit or a
  vanished session would never be announced.
- A timer per limit: lost on restart, and still blind to sessions going
  away.

## An agent's first look is a silent baseline; a human starts available

**Id:** 38589c62-d04b-40f6-b481-c1b9117c91e7
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-23 (the availability slice)
**See:** availability.md#availability-is-computed-on-read-the-announced-state-is-stored-and-a-sweep-notices-what-time-alone-changes — 240dae0b-9ea9-4cbb-a447-5ca3d39b1f38 — as of 2026-10-23
**Revisit when:** a client needs an event for an agent's very first state, or memberships get an initial state at creation

A membership without an announced state (every row after the migration,
every new agent until its first resume) is stored as it is found the
first time an agent's row is reconciled, with no event. A human's
missing state reads as `available`, so their first limit is announced.

**Reason:** after the migration every agent that is not running would
otherwise be announced as going out on the first sweep: a burst to the
admins and owners that reports no change. A human's only outage is a
limit or the owner's absence, both declared after this code exists, so
for them `available` is the true starting point.

**Rejected alternatives:**
- Announce whatever the first look finds: the burst above, once per
  deploy and once per new agent.
- Set the state when the membership is created: every new agent would
  start `offline` and announce a return on its first resume.
