# Events

## The long-poll waits on an asyncio event, never on the database

**Id:** 6310ef59-6010-4fa5-95d5-30f20bc00117
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** review of the hub skeleton, 2026-10-21 (to be recorded before the first long-poll); implementation session, 2026-10-21 (the events slice)
**See:** https://github.com/oliver-zehentleitner/maity — 3dacd29b-bd09-4757-80bb-7f3cfbd9af91 — as of 2026-10-21
**Revisit when:** a second replica runs, or waiting sessions outnumber what one process can hold

`GET …/events?wait=N` is an `async def` endpoint. It reads in the thread
pool, holds no database connection while it waits, and waits on an
`asyncio.Event` of its own in the event loop. `events.transaction()`
announces every committed event to an in-process registry
(`maity_hub.longpoll`), which sets the events of the waiters on that
project with `call_soon_threadsafe`. A woken waiter re-reads; a two-second
re-read is the fallback for anything the signal missed. The registry also
holds "one open long-poll per credential" (a second call supersedes the
first) and the `listening` flag of §5.3.

**Reason:** a waiting agent costs the hub nothing but a coroutine and an
event, so dozens of sessions can listen at once without a connection pool
or a thread each. The signal comes after the commit, so a woken reader
finds the row (`events.transaction`). The project decided against
database-specific notifiers (LISTEN/NOTIFY) to stay portable, so the wake
is in-process, which fits the one replica V1 runs.

**Rejected alternatives:**
- A synchronous endpoint sleeping in the thread pool: every waiter would
  hold one of the pool's 40 threads, and the pool would run out long
  before the sessions did.
- Polling the event table every second for each waiter: simple and
  replica-proof, but a query per waiter per second for nothing in the
  common case.
- PostgreSQL `LISTEN/NOTIFY`: the natural cross-replica signal, refused for
  V1 by the database-agnostic decision; it is the first candidate when a
  second replica comes.

## A runner's stream reads every project it was ever attached to

**Id:** 96643c34-fc6f-4279-8a89-39882e3ab3d8
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation of the runner stream, 2026-10-22; accepted by the contract owner the same day, `docs/api.md` §15.8 (PR #84)

`GET /runner/events` (`docs/api.md` §15.8) scans the events of every
project the runner has an attachment row in, active or detached, and
delivers those whose audience names `runner:<id>`. What the runner
otherwise reads — the projects in the hello packet, its placements —
stays on the projects it is attached to now.

**Reason:** `runner_detached` is written into the project being detached,
at the moment the project leaves the runner's set. A stream limited to
the current set would never deliver it. Reading the old projects as well
exposes nothing: an event names the runner only while it concerns it.

**Rejected alternative:** the stream on the current set only, as the
contract's first text read. The runner would learn of a detachment only
by noticing that a project is missing from its next hello.

**Rejected alternative:** writing the detachment somewhere outside the
project. Every event belongs to exactly one project (§15.10).

## Mention pings are counted in process and given back when the write does not commit

**Id:** 8a5e4c45-edcd-4c23-89c6-2b784b9d3e14
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation of mentions (`docs/api.md` §8.6), 2026-10-22, PR #151 and its review

The limit of 30 pings per membership in 10 minutes is a sliding window in
memory (`mentions.PINGS`, a `ratelimit.Limiter`), charged inside the write's
transaction just before the event is emitted, all pings of one write at
once. A write past the limit is refused as a whole and stores nothing; its
`Retry-After` is the time until every one of its pings fits. A write that
is charged and then does not commit (a later error, a `retrying` attempt,
a lost idempotency race) gives its pings back through
`events.on_rollback`.

**Reason:** like the nonce window and the long-poll registry, it is state of
the one replica (`docs/api.md` §8.3), cheap to check and lost harmlessly on a
restart. Charging before the emit is what lets the over-limit write fail
whole, as the contract asks; giving back on rollback keeps a failed write
from spending budget it never used.

**Known imprecision:** the give-back drops the newest entries of the
member's window, which under two concurrent writes of the same member may
be the other write's; both were charged within the same instant, so the
window's timing is off by that much at most.

**Rejected alternatives:**
- Counting pings from the event table (`mentioned` events and message
  audiences of the last 10 minutes). Exact across restarts and replicas,
  but a query over the event log on every write that mentions someone, for
  a spam guard.
- Charging after the commit. Nothing to give back, but the over-limit
  write would already be stored when the limit refuses it.

**Revisit when:** the hub runs more than one replica.

## Shared environments are computed from live sessions; only announcements are stored

**Id:** 158a2300-873a-41eb-8888-205157b844e6
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation of the shared-environment warning (`docs/api.md` §5.3, contract #132), 2026-10-22

Who shares an environment with whom is computed whenever a member view
asks, from the live agent sessions and the ids their resumes declared.
`environment_overlap` holds one row per pair only to remember what was
announced: when the overlap started, the highest level announced, and
since when the two no longer share an id (`quiet_since`). The rows are
brought up to date when one member's sessions change: on its resume and
on a credential's revocation (which member removal goes through). A pair
that shares again within 10 minutes of `quiet_since` continues its
overlap; later, it is a new one and is announced again.

`shared_environment_detected` names only humans in its audience (the
owners and the human `owner`/`admin` members, never `role:admin`), and
`events.readable_by` refuses it to every agent before the see-all rule of
owners and admins, and before the actor's own events.

**Reason:** the field must be current on every read. The live sessions are
the source of truth, and they are few per project. Storing the overlap
itself would need a writer for every way a session ends. The 10-minute
rule only matters when the next resume decides between "continues" and
"new", so it is evaluated there, without a timer. An agent with the
`admin` role sees every event and would otherwise read the warning about
itself and its peers, which the contract keeps from agents.

**Rejected alternatives:**
- A stored overlap kept current by a background sweep. Exact at any
  moment, but one more worker for a warning, and the view would lag it.
- Audience `role:admin`. It also reaches admin agents, which may not read it.

