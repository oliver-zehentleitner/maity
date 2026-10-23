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
