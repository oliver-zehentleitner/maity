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
**Status:** open
**Evidence:** inferred
**Source:** implementation of the runner stream, 2026-10-22; proposed to the contract owner the same day

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
contract's first text reads. The runner would learn of a detachment only
by noticing that a project is missing from its next hello.

**Rejected alternative:** writing the detachment somewhere outside the
project. Every event belongs to exactly one project (§15.10).
