# Replicas

Design for running several hub processes behind one load balancer (card `tsk-f5jge5aw7ah1`,
step 1: design, no code). Every entry here is a proposal for review: `Status: open` until the
coordinator approves it, then `active` as the build cards land. The inventory it rests on was
read from the code on 2026-10-30 (`main` at `0e190c95`); file and line references are from then.

## Several replicas run on PostgreSQL only, and coordinate through PostgreSQL itself

**Id:** dde08300-c843-4f91-8046-f4638a933efa
**Type:** decision
**Status:** open
**Evidence:** inferred
**Source:** the maintainer's goal "simple scaling toward about 200 000 users in two weeks" (inbox, 2026-10-30, seq 15111) as carried by the card; the maintainer's internal deployment planning (2026-10-30), which runs PostgreSQL as a managed service with failover; the inventory of process state on `main` 2026-10-30
**See:** kubernetes.md — 5e42eb26-9883-49e2-89c0-9fe4e6517c62 — as of 2026-10-30
**Revisit when:** a measured limit of the database (connections, NOTIFY throughput, write load of the shared counters) is reached in the load test below, or an operator needs replicas on MariaDB

The one-pod rule (kubernetes.md 5e42eb26) exists because state the hub's correctness depends on
lives in the process. The inventory finds three kinds:

- **Broken with two replicas:** the long-poll wake-up and its "a newer wait supersedes the older"
  rule (`longpoll.Registry`, `events.Notifier`), the registry of open long-polls that event routing
  and the jour fixe read (`listening._open`, used by `instances.team_wakes`,
  `jourfixe.rounds.selected_instance`), the request-signing nonce window (`auth.credentials.NonceWindow`),
  the breakers and per-session counters that bound guessing (`second_factor._wrong_in_session`,
  `device_codes._breaker`, `registration.BREAKER`), and the attachment files on a
  `ReadWriteOnce` volume.
- **Weaker:** every `ratelimit.Limiter` (about thirty, N times their limit with N pods), the forge
  rate budget (`forge._budgets`), forge and image caches (N times the forge reads), the hourly
  digest's narrow double-write race, and the instance figures counted in memory: the admin's
  `requests_dropped_last_hour` (`registration.DROPPED`, added where a registration is refused,
  read by the registration settings) shows only the pod that answers; and the forge source a
  project's view shows (`forge_access._last_via`, read by `probe_via` for
  `GET /projects/{owner}/{slug}` and the resume packet), learned only on the pod whose probe read
  the project.
- **Safe already:** the mail outbox (claimed by a conditional `UPDATE`), the notification mailer
  (the human's settings row `FOR UPDATE`), and the workers that settle under `lock_project` with
  compare-and-set writes (takeovers, availability, commitment, not-listening, organisation
  invitations, registrations, reports, jour fixe rounds); the idempotency store; the static
  registries filled at import; the read caches with short lives that may differ per pod
  (`swarm.CACHE`, `statistics.CACHE`, `landing_stats._cached`).

Several replicas are offered on PostgreSQL only. SQLite is one file on one node; MariaDB stays
supported with one replica, since what follows uses `LISTEN`/`NOTIFY`, `UNLOGGED` tables and
`INSERT … ON CONFLICT`, and doubling each for MariaDB is work no deployment asks for. The shared
state goes into the database the hub already has, not into a second service.

**Reason:** every pod already holds a pool to PostgreSQL, and a managed PostgreSQL with failover
is highly available already; a second stateful service would add a failure mode,
a backup, a secret and an operator task for state that is small (nonces for ten minutes,
counters for at most a day) and must be as durable as the rows it guards. PostgreSQL has every
primitive needed: `pg_notify` delivered on commit, compare-and-set updates, upserts with `RETURNING`,
`UNLOGGED` tables for state that may be lost on a crash.

**Rejected alternatives:**
- **Redis or Valkey for wake-ups, nonces and limits:** fast and the common pattern, but another
  stateful service with its own HA, and a wake-up published outside the transaction can arrive
  before the row is visible or for a transaction that rolled back.
- **Sticky sessions instead of shared state:** keeps a credential on one pod, but a nonce replay or
  a guessing attacker simply chooses another address, the limits stay per pod, and every scale
  event or pod loss moves users anyway. Stickiness is not needed once the state is shared.
- **Replicas on every supported database:** MariaDB has no `LISTEN`/`NOTIFY`; the wake-up would
  have to poll, which is the load this design removes.

`tests/test_two_processes.py` starts two real hub processes on one PostgreSQL and checks the
wake-up, the supersede rule, a shared rate limit, the nonce window and the worker claim across
them; the unit tests of each piece stand in for the other process.

## Wake-ups cross pods through NOTIFY sent in the writing transaction, one LISTEN connection per pod

**Id:** 387c2409-1c68-4bf8-a9a0-8a56a4002545
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** `events.transaction` and `Notifier` (events.py:45-110), `longpoll.Registry` (longpoll.py:35-79), `routes/events.py` (`FALLBACK_SECONDS = 2.0`), `routes/notifications.py` (polled `listing.stamp` every 0.5 s; on PostgreSQL now held by `wakeups.held`, at the latest every 2 s), `listening.py`; PostgreSQL documentation of `NOTIFY` (delivered at commit, never for a rolled-back transaction, payload under 8000 bytes); points 1 and 2 built in `events.emit`, `wakeups` and `MAITY_DIRECT_DATABASE_URL` (card tsk-kckyhv9vdrrp), 2026-10-31; point 3 built in `wakeups.opened` and `wakeups.supersede` (card tsk-ywss353vk5q2), 2026-10-31; point 4 built in `listening` and migration `20261031125530_long_polls` (card tsk-5mspd6ftkacq), 2026-10-31, its stop dropping the queue in `listening.stop` (card tsk-xz3bxa5cwv4v, review on #1256), 2026-11-03; point 5 built in `wakeups.held` and `wakeups.ring` (card tsk-az67x29mc2yg), 2026-10-31
**Revisit when:** NOTIFY throughput or the listener connection shows up as a limit in the load test (a transaction that notified takes a database-wide lock on the notification queue at commit, so notifying writers serialise there; the load test measures commit latency for it), or a wake-up is measured late across pods, or `pg_notification_queue_usage()` climbs

Today a commit wakes only the waiters of the process that committed (`notifier.notify` after
`engine.begin()`); a waiter on another pod sees the row at its 2-second fallback re-read. The
design:

1. `events.emit` adds `SELECT pg_notify('maity_events', '<project_id>:<seq>')` to the writing
   transaction. PostgreSQL delivers it at commit and drops it on rollback, so a wake-up never
   precedes its row and never announces a row that does not exist. The local `notifier.notify`
   after commit stays, so the writing pod wakes without the round trip; its own notification,
   which comes back through the listener, is skipped (the notifier remembers the last 4096
   events it wrote, taken when the event is written, before the commit), so a write does not
   wake the writing pod's waiters twice, also when the listener hears the notice before the
   commit's own announcement has run; an event rolled back leaves an entry naming no row. The payload
   says where to look, never what happened: the waiter reads the row with its own rights.
2. Each pod opens one connection outside the pool that runs `LISTEN maity_events` (and the
   channels below) and feeds `longpoll.registry.notify`. When that connection drops, the pod wakes
   every waiter and reconnects with backoff, so a missed notification costs one re-read, not an
   event. The waiters re-read spread over a random 0–2 s, not all at once: a pod holding 10 000
   waits must not send 10 000 reads in the same instant. The 2-second fallback stays as the safety net and
   can be raised to about 10 s once the load test shows the listener reliable.
3. **Superseding across pods:** a new long-poll of a key (`credential_id`, `session:<id_hash>`,
   runner key) announces itself when it opens, in a short transaction of its own:
   `pg_notify('maity_supersede', '<sha256 of kind:key>:<start>')`, the start read from the
   database's `clock_timestamp()` in microseconds (`wakeups.opened`). A pod holding a wait of that
   kind and key that started earlier ends it with `superseded`; a wait that started later, or the
   announcing wait itself when its own notice comes back, stays. The rule of §8.3, "the wait that
   took over owns what came in", holds again across pods. The bell's and the device codes' own
   "newer wait supersedes" maps (`routes/notifications._holding`, `routes/device_codes._holding`)
   use the same channel, each as a kind of its own (`bell`, `device`, `events` for agents and
   runners). A closing wait removes only what it owns: its own `wait_id` (point 4), never the row
   or the holder entry of the wait that superseded it, as `longpoll.Registry` already checks in
   the one process. Built with two departures from the first wording, `key || ':' || token`:
   - **The start on the database clock, not a token:** with a token alone, two waits of one key
     opening almost together on two pods can each receive the other's notice after opening, and
     both end, leaving the client without a wait. The order decides instead, read from the one
     clock every pod shares; the pods' own clocks differ, so a start each pod reads for itself
     was rejected too.
   - **The key's hash, not the key:** the channel then carries no credential or session id, and
     every notice has the same length. The raw key was rejected for that reason.
   A wait is held from the moment its start is read, before its notice commits, so a newer
   wait's notice arriving in between still finds it. Only a wait that started strictly earlier
   ends: two starts in the same microsecond end neither, where `<=` would end both, the case the
   order exists to prevent. A notice that arrives while the listener is disconnected is lost
   and not caught up: the older wait then stays open until its own timeout (at most 55 s), as
   before this point existed. Catching up would need the waits in a table, which point 4 brings.
   Each opening wait costs that one transaction on PostgreSQL; SQLite and MariaDB announce nothing.
4. **The listening registry moves to the database:** an `UNLOGGED` table `long_poll(wait_id,
   listening_key, pod, opened_at)`, one row per open wait, keyed by a fresh `wait_id`, inserted
   when a wait opens and deleted by that `wait_id` when it closes, so two waits of one key never
   delete each other's row. `listening_key` is what `is_listening` is asked with: the agent
   session's id, or the runner's listening key; superseding (point 3) keeps its own key, the
   credential or the cookie session. Each pod refreshes a heartbeat row `hub_pod(pod, seen_at)`
   every 15 s, and a wait whose pod has not been seen for 45 s does not count; each heartbeat also
   removes the rows of pods gone longer. Built in `listening` (card tsk-5mspd6ftkacq):
   - The writes go through one thread per process, so opening a wait, which happens on the
     event loop, never waits for the database; this process's own waits count at once from
     memory, another pod's from the moment its thread has written the row. Rejected: writing
     the row synchronously when the wait opens and closes, which would put a database round
     trip on the event loop (or a worker thread) of every long-poll, twice per wait, and make a
     slow database slow every long-poll; the queue costs a short delay before another pod sees
     the wait, which the 45-second staleness already tolerates. A failed heartbeat (the
     database gone, a failover) is tried again after a whole interval, not at once.
   - Every moment in the registry is the database's (`now()`): `seen_at`, `opened_at` and the
     staleness compared in `which` and in the sweep. Pods whose clocks differ by more than a
     heartbeat would otherwise count each other as gone. In SQL it is `timezone('UTC', now())`:
     the columns hold UTC without a zone, and a bare `now()` compared with them is shifted by
     the server's `TimeZone` (a server on `Europe/Vienna` made a live pod an hour stale).
     `now()` is the start of the caller's transaction, so `which` inside a long transaction
     compares with a slightly older moment; against 45 seconds of staleness that is harmless.
   - `which(keys, conn)` answers for many keys in one read, on the caller's connection: the
     member views, the instance lists, the team wakes, the jour fixe and the statistics ask it
     once per call instead of once per instance.
   - **UNLOGGED, and empty after a crash:** a crash or a failover of PostgreSQL empties both
     tables. That loses nothing worth keeping: a wait lives on its HTTP connection, and the
     heartbeat, which compares the rows it finds with the waits open in its process, writes them
     again within 15 s; until then those agents read as not listening, the same as a pod that
     has just started. In exchange no write of the registry costs WAL, and a long-poll opens and
     closes many times an hour per agent.
   - SQLite and MariaDB, which run one replica, create the tables as ordinary ones and never
     write them; the registry stays in the process there.
   - **A stop drops what is still queued** (tsk-xz3bxa5cwv4v, #1256 and its follow-up): each
     writer ends on its own signal, after the write it is in, and the opens and closes still in
     the queue are dropped, since the stop deletes the pod's rows right after anyway. Rejected:
     working the queue off before the writer ends, which makes a stop wait for a database that
     may be the very thing holding the writer (a lock, a failover); and leaving the rest to the
     next writer, which in tests wrote one app's waits into the next app's database. In
     production a stop only comes with a pod's shutdown.
5. **The bell and the device-code waits** (0.5 s and 0.25 s polls of the database per open wait)
   move onto the wake-ups on PostgreSQL (`wakeups.held`, `Held.pause`): a held wait sleeps until
   something wakes it, at the latest `FALLBACK_SECONDS` (2 s), and then compares its stamp or
   status as before. With 20 000 open dashboards the 0.5-second poll alone would be 40 000 stamp
   reads a second; on the wake-up it is a read per change plus one per wait every 2 s.
   - **The bell rides on the event wake-ups:** it registers in `longpoll.registry` with the
     human's member projects, so every event in them wakes it, locally and across replicas
     (`maity_events`, point 1). That wakes more bells than needed, every event of the project
     and not only those that make an item for this human; the stamp comparison absorbs it, at
     a few aggregate reads per wake. `maity_bell` (the SHA-256 of the human id) is rung only by
     the human's own rows that no event announces: a new account record (`records.write`), a
     mark read (`listing.mark`) and a chat read mark (`routes/events.remember_read`).
     Rejected: ringing `maity_bell` for every reached human on each `emit`, as first written,
     which would resolve every audience twice, once to store the event and once to ring it.
   - **The device codes:** `redeem`, `approve`, `deny` and `complete` ring `maity_device` with
     the SHA-256 of both waits' keys, the creator's (`code:<session_hash>`) and the redeeming
     browser's (`pending:<pending_hash>`). `void_open`, rare (a method switched off, a session
     ended), and expiry, which nothing writes, are left to the fallback.
   - What wakes nothing, such as a membership that changes the bell's projects (written in many
     places), shows at the fallback, at most 2 s late. SQLite and MariaDB keep the polls.
   - Built in card tsk-az67x29mc2yg, 2026-10-31.

**Constraint:** PostgreSQL keeps notices in one queue (8 GB by default) until every listening
session has read them. A session that listens and stops reading, such as a listener whose
connection died half-open, holds the queue; once it is full, every commit that notifies fails,
which here is every write with an event. The listener's connection therefore sets TCP keepalives
(`db.LISTENER_KEEPALIVES`, a dead connection noticed after about a minute, then a new one), and
the server's own keepalive ends the dead session. What is left to watch is
`pg_notification_queue_usage()`, which the operator's monitoring should alert on well before 1.

**Reason:** `NOTIFY` inside the transaction makes the wake-up exactly as durable as the write;
one listener per pod costs one connection, and fan-out to the waiters stays in memory as today.
Polling is what the in-process notifier was built to avoid, and with many pods every idle waiter
would read the database every 2 seconds.

**Rejected alternatives:**
- **Shorter fallback polling instead of NOTIFY:** no new moving part, but the read load grows
  with the open waits (tens of thousands), and a wake-up still takes the poll interval.
- **NOTIFY after commit from the application:** simpler to place, but lost when the process dies
  between commit and send, and it would need its own connection round trip per commit.
- **A table of pending wake-ups that pods poll:** durable, but polling again, and rows to delete.

## Nonces in an UNLOGGED table claimed by INSERT … ON CONFLICT DO NOTHING

**Id:** 1c65bb74-d5a1-41ff-8741-dafd80ce449f
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** `auth/credentials.py:108-129` (`NonceWindow`, its docstring "this moves to the database before a second"), `auth/caller.py:249-277` (`TIMESTAMP_WINDOW_SECONDS` 300, `NONCE_WINDOW_SECONDS` 600, `PROCESS_STARTED`), `idempotency.py` (POST and PATCH of agents and runners need an `Idempotency-Key`); built in `auth/nonces.py` and migration `20261030180344_request_nonces` (card tsk-s7b80az2s0wm), 2026-10-30
**Revisit when:** the insert per signed request shows in the load test as a write bottleneck, or the signing scheme changes

A signed request's nonce is claimed with `INSERT INTO request_nonce (credential_id, nonce,
expires_at) VALUES (…) ON CONFLICT DO NOTHING RETURNING nonce`; no row returned means a replay,
refused as today (the driver reports `rowcount` -1 for such an insert, so it is not read). The
claim happens after the signature verifies, as before, in the short transaction that
authenticates and commits before the route runs (`deps._resolve`): a request refused later in
that same transaction leaves its nonce unspent, and replaying it is refused the same way. Every
thousandth claim of a process deletes the rows past `expires_at` (600 s, twice the timestamp
window). The table is `UNLOGGED` on PostgreSQL: no WAL per request. SQLite and MariaDB create
both tables but keep the window in the process, as before (`auth.nonces.shared`).

An `UNLOGGED` table is emptied by a crash of the database and is not replicated, so it is empty
on a promoted standby after a failover. `PROCESS_STARTED` is therefore replaced by an **epoch
row that vanishes exactly when the nonces do**: a one-row `UNLOGGED` table `nonce_epoch(since)`.
The migration writes it; each signed request reads it before the signature check; when it is
missing, the first pod to notice inserts `now()` (`ON CONFLICT DO NOTHING`, then reads it back),
and every request signed before `since`, in whole seconds as `PROCESS_STARTED` was, is refused
(`timestamp_skew`), on every pod. The request that sets it may itself have been signed in the
second before and is then refused once; the client signs again with the `server_time` it gets.
The epoch takes the database's clock (`timezone('UTC', now())`), not the replica's: a replica
whose clock runs behind could otherwise put the boundary before nonces another replica spent
just before the loss.

Both the claim and the setting of the epoch rely on READ COMMITTED, the hub's isolation level
(`db.make_engine`): `ON CONFLICT DO NOTHING` waits for a competing transaction that is still open,
and the `SELECT` after it takes a new snapshot and sees the committed epoch. Under REPEATABLE
READ that `SELECT` would not see it and the claim would fail with a serialisation error, so the
authenticating transaction stays READ COMMITTED. A refusal that rolls the authenticating
transaction back takes a freshly set epoch with it; the next request sets it later, which only
refuses more, never less. A database restart or a failover
thus closes the replay gap at once, and a newly started pod no longer refuses requests that
another pod would take. Reading one row per request takes no lock and stays in the buffer cache.

**Reason:** a replay across pods today repeats a DELETE, a PUT, the exempt paths
(`/api/v1/join/`, `/api/v1/auth/`, `/me/resume`) and any GET within ±300 s, once per pod; only
POST and PATCH are covered by the idempotency store. One primary-key insert per signed request
is the cheapest shared check there is.

**Rejected alternatives:**
- **A logged table:** survives a crash and a failover, so it needs no epoch, but writes WAL for
  state that is worthless after ten minutes; the epoch row covers both cases for one read.
- **Setting the epoch under an advisory lock:** one more round trip for the same effect as the
  conflict-free insert.
- **The database's start time (`pg_postmaster_start_time()`), read once per pod:** misses a
  database restart while the pods keep running (their cached time is old) and a failover (the
  promoted standby keeps its own, older start time), so a request signed in the last 300 s could
  be replayed once in either case.
- **Pin each credential to a pod (consistent hashing at the ingress):** depends on the ingress,
  breaks on every scale event, and an attacker with a captured request sends it anywhere.
- **Shorter timestamp window instead:** narrows the replay, does not close it.

## Rate limits, breakers and guess counters count in one shared table

**Id:** 2bd65fec-3b02-4b68-bf2c-c0ae63b4679e
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** `registration.DROPPED` (`registration.py:377`, read at `:292`), `ratelimit.Limiter` and its about thirty module-level instances (auth, registration, email links, device codes, joins, runner pairing, second factor and its reset, exports, test mail, invitations, uploads, avatars, mentions, ticker, notes, forge webhook, badges, public pages); `second_factor._wrong_in_session`; `device_codes._breaker`; `registration.BREAKER`; the maintainer's internal deployment planning (2026-10-30); built in `shared_counts` and migration `20261031011834_rate_counts` (card tsk-j4k2gc4efnz6), 2026-10-31; review findings of #822 (the window of a give-back, `blocked`, a count over the limit, the second connection, the sweep) built in card tsk-kckyhv9vdrrp
**Revisit when:** the counter writes or the sweep show in the load test, the pool runs out while requests hold a second connection for a count, or a limit needs exact sliding-window semantics across pods

`ratelimit.Limiter` keeps its interface (`hit`, `take`, `place`/`release`, `blocked`,
`reset`; `give_back` gave way to `place` with a count, below) and gets a shared backend on PostgreSQL (`shared_counts`): an `UNLOGGED`
table `rate_count(bucket, subject, window_start, count)` (`subject` is the limit's key; `key` is
a keyword on MariaDB), incremented with `INSERT … ON CONFLICT DO UPDATE SET count = count + n`,
read as a sliding window approximated by the current and the previous fixed window (weighted by
the overlap). A take over the limit is subtracted again, so a refusal records nothing, as in the
process; two takes at once may both be refused where one would have fitted, the strict side.
A small limit (`EXACT_UP_TO`, 20 or fewer attempts) keeps a row per attempt instead, keyed by its
moment, and counts exactly as the process does: the take reads the attempts inside the window
under a per-key advisory lock (`pg_advisory_xact_lock`), writes its row only when it fits, and
the wait is the moment the oldest attempts that must go leave the window. The estimate assumes
attempts spread evenly, which a handful do not: with a limit of one, the attempt still weighs on
the next fixed window until its end, so one export in ten minutes waited up to twenty (`Retry-After`
1006 in #822's CI). The rows stay until the sweep (two days), those released to zero included,
not only while their window is read: a login limit of 10 a minute keeps up to 10 rows a minute
per address where the estimate keeps one per window. The bound sits at 20 because the limits up
to there are the guessing bounds and the per-account courtesy limits, few attempts per key,
where the estimate's error is a large share of the limit; above it are the per-address limits
of 60 a minute on public endpoints and the upload volume, whose traffic would be a row each.
Rejected:
capping the estimate's wait at the window, which names a moment the retry is refused again; an
exact row per attempt for every limit, which for the per-address limits of 60 a minute keeps
every request's row until the sweep.
For the larger limits the wait a refusal names (`Retry-After`) follows the estimate: when the current window alone
is over the limit it runs into the next window, where this window's attempts count as the
previous ones and fall by weight. The estimate assumes the attempts spread evenly over the
window, so the wait can differ from the exact answer in the process either way: longer when the
attempts came early in the window (621 s instead of 600 s for the mentions test), shorter when
they came late (29 pings at 594 s of 600, then 2 more: 27 s instead of 600 s). It is no
conservative bound; what each backend names is the moment its own take fits again.
Work that does not happen after all gives its attempts back with `release` and the mark
`place` returned, which is the window the attempts were counted in (for an exact limit their
own row): `give_back` subtracted from
whichever window was current when the work failed, a later window's count, so it is gone, and
every caller now holds the mark. `take` and `place` refuse a count over the limit
(`ValueError`): it never fits, and no `Retry-After` would be true; no caller passes one (a write
pings at most 10 members per field against 30, an upload counts at most the volume limit). Every `Limiter` now has a
`name`, its bucket (`<module>.<variable>`). The breakers keep their "shut until" as a row of the
same table (`set_until`, `until`), `_wrong_in_session` counts the current and the previous window
of the session's five minutes (at least every wrong code, never fewer), and
`registration.DROPPED` is a bucket too: the count of refused registrations an admin reads as
`requests_dropped_last_hour` is the sum over every pod, not the answering pod's. A key that is
long or holds a NUL (an address paired with a source) is stored as its SHA-256. Each count is
its own short transaction, apart from the request's, as the counts in the process were never
rolled back either. Inside a request's transaction (a wrong second-factor code in
`second_factor.verify`, the mentions, notes, ticker and avatar charges) that means a second
connection from the same pool for the moment of the count; a pool held entirely by such requests
makes the counts wait for `pool_timeout` instead of failing at once, which the pool's overflow
(16 by default) keeps far away. Rejected: the count on the request's own connection, which a
refused request's rollback would undo, a wrong code included. That transaction is exempt from `write_guard` (`write_guard.exempt`): it
changes nothing of an account, and taking the human's shared `account_lock` there would wait for
the request's own transaction, which may have just made that row (a hang `create_invitation`
showed in the tests). Rejected: a second engine for the counts without the guard's hook, which
would bring a second pool per replica for the same database. Every thousandth add of a process deletes windows older than two days, inside that add's
transaction: the one request that makes it waits for a scan of the table, since the primary key
starts with `bucket`, not `window_start`. Two days of windows keep that small; an index on
`window_start` or a timed sweep apart from the requests are the moves if the load test shows it. On
SQLite and MariaDB, and until `create_app` configures it, the in-process backend stays.

Two things stay per pod on purpose: the concurrency caps that protect the pod itself (`avatars._slots`,
`passwords._SLOTS`, the bell's `AT_ONCE`), and the statistics line (`request_stats`), which reports
the pod.

**Reason:** with N pods every limit is N times its value, and the guessing bounds (second factor,
device codes, registration) are security properties, not courtesy. Keeping the interface means no
caller changes. An exact sliding log per request would cost a row per hit; the two-window estimate
is the standard trade-off and errs by at most the previous window's share.

**Rejected alternatives:**
- **Divide each limit by the pod count:** wrong whenever the load is uneven or the count changes,
  and a breaker would still trip on one pod only.
- **Keep the courtesy limits per pod and share only the security ones:** two backends to reason
  about per limit; with one cheap upsert there is no reason to split.

## Each worker's pass is claimed once per interval in a shared row, whichever pod is first

**Id:** 24489a9c-6035-41d0-9236-9eb0e04fc902
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the sixteen `Worker` classes started in `app.py` (attachments, availability, commitment, images, jour fixe, mail outbox, notification mailer, not-listening and its digest, organisation invitations, probe, registrations, public pages, the public snapshot, reports, takeovers) and how each picks its rows; `not_listening_digest.reconcile` (reads `latest()` before the human's lock); `jourfixe` `record_presence` (insert into `presence_minute` without a lock); `probe.Worker` (forge calls every 120 s and 300 s)
**Revisit when:** one worker's pass takes longer than its interval on the one pod that holds it, so that it has to be split across pods

Every worker keeps running in every pod, so any pod can take over at once, but a pass starts only
after claiming it in a shared row, `worker_run(name, started_at, pod, lease_until)`, with one
compare-and-set:

```sql
UPDATE worker_run SET started_at = now(), pod = :me, lease_until = now() + :lease
 WHERE name = :name AND started_at <= now() - :interval AND lease_until < now()
```

One row updated means this pod runs the pass; none means another pod ran it within the interval
or still holds it. Ticks are per process and offset between pods, so the interval check, not
mutual exclusion alone, is what keeps a sweep to once per interval across N pods. A pass longer
than its lease renews it between its own transactions (`UPDATE … SET lease_until = … WHERE pod =
:me`); a pass whose renewal finds another pod's name stops before its next write. A pod that dies
leaves a lease that simply expires. No session or advisory lock is involved, so nothing depends
on a connection staying open, and it works behind PgBouncer in any mode (entry a83fc8e7).

The claim is about cost, not correctness: the workers that settle under row locks (mail outbox,
mailer, takeovers and the others above) stay correct without it. The two that are not get their
own fix as well: the digest takes the owner's lock before it reads `latest()`, and the jour fixe's
presence insert becomes `ON CONFLICT DO NOTHING`. The request stats reporter stays per pod and
claims nothing. Probe jobs queued by a webhook on the pod that took the request stay there: their
writes are deduplicated already (`dedupe_key`), and the next sweep catches what a dying pod
dropped.

**Reason:** one rule for all workers is easier to review than a proof per worker, and a skipped
pass costs nothing where the next pod runs it seconds later. A row with a lease survives the loss
of any connection and of any pod, and it carries the "last ran" time that the interval needs.

**Rejected alternatives:**
- **A separate worker Deployment with one replica:** clean split, but the one-pod problem moves
  there (no takeover while it restarts), and two images or entrypoints to operate.
- **Leader election through Kubernetes leases:** ties the hub to Kubernetes; the hub also runs
  under Docker Compose.
- **Rely on each worker's row locks alone:** correct for most, but not for the digest and the
  presence insert, and the forge calls stay N-fold.
- **`pg_try_advisory_xact_lock` at the start of a pass:** a transaction-level lock ends with its
  transaction, before the pass runs its own; and with ticks offset between pods each pod still
  runs the pass once per interval, one after the other.
- **A session advisory lock on a dedicated connection:** holds across the pass, but is lost when
  that connection drops while the pass goes on through the pool, needs a direct connection past
  PgBouncer, and still lacks the "last ran" time.

Built (`worker_runs.claim`): the claim is an `UPDATE`, then an `INSERT … ON CONFLICT DO NOTHING` for a
worker's first pass, on the database's clock. Only PostgreSQL writes the row; on the other
databases every pass runs, as they run one replica. A finished or failed pass releases its lease,
since a lease of five minutes would otherwise decide the next pass of a worker with a shorter
interval. `Claim.is_set` is what a pass asks between two transactions: stopping, or another pod
has it, and asking renews the lease once a minute. The passes that loop over many transactions
ask it (probe, images, mail, notification mail, public pages, attachments, digest); the others are
short, and one that outlives its lease costs a second run, not a wrong result. The hourly digest
claims with half an hour, not an hour: pods look at the clock at different seconds, and with the
full hour a pass that began at 10:00:30 would refuse the pod that looks at 11:00:05. On a restart
within the interval the probe's first sweep is refused like any other. The digest's lock before
`latest()` was already in place when this was built (`reconcile` takes it); only the presence
insert changed.

## The forge budget is shared; forge caches stay per pod

**Id:** 83da2bfa-ee4b-4f35-bfe7-d12d7780f575
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** `forge.py:125-126` (`_budgets`: `remaining`, `in_flight`, `until` per token, `LOW` reserve of 5 %), `forge.py:246-250` (`_visible`, `_public`), `github_app.py:182` (`_tokens`), `forge_access.py:62` (`_chosen`), `forge_access.py:258-277` (`_last_via`, `probe_via`, read in `views.py:185` and `releases.py:190`), `forge_links.forget_token`, `ktw.CACHE` and its `forget` at `routes/projects.py:743`, `contract_text`
**See:** keep-the-why.md — f5af1bd9-bb11-4310-b751-334de2668dfe — as of 2026-10-30
**Revisit when:** forge reads per hour approach the token's limit with the probe on one pod, or a cache's staleness across pods is seen by a user, or the forge answers 403 or 429 while the shared row shows the reserve intact, or the budget's two statements show as pool waits in the load test

The budget per token (`remaining`, the reset time) moves to a small shared row updated from each
response's headers, so every pod sees what the others spent and the 5 % reserve holds; `in_flight`
stays per pod (it bounds that pod's concurrency). The caches (visibility, installation tokens, the
Keep the Why reads, contract texts, image gates) stay per pod: each is keyed on what it reads and
expires within minutes, so N pods read the forge up to N times more often for them, not
wrongly. `forget_token`, a refused installation and a project's changed `repository_url`
(today `ktw.CACHE.forget(project.id)` on the answering pod only) are also sent on a
`maity_forget` channel, so no pod keeps using a token that was removed or a family read of the
old repository.

`probe_via` is the one cache that is shown, not used: with the probe claimed by one pod per
interval (entry 24489a9c), the others never learn it. The source the last choice found is
therefore written beside the project's other probe facts when it changes (one small column or
row per project, written only on a change), and views read it from there.

Built so far: the budget (`shared_budget`, table `forge_budget`). Each answer merges into the row by
the rules a process already had (the lowest `remaining` within a window, a later reset replaces
it, the later hold counts), and each read and `retry_at` merge the row into what the process
knows. A database that does not answer costs the sharing, never a forge read: the budget guards
the forge, and a read refused because the database is down would turn one outage into two.

Two limits of that. `in_flight` stays with the process, so the reserve can be overrun by the reads
the other pods have under way before their answers reach the row; with GitHub's 5000 an hour and a
reserve of 250 that takes more parallel reads than a hub has. And each forge read costs one read of
the row before and one upsert after, each on a second connection, often from a request that holds
one already: with a full pool a forge read waits up to `pool_timeout`, then goes on unshared, the
same pattern as the shared limits (entry on limits above).

The notice on `maity_forget` (`wakeups.forget_token_everywhere`, `forget_repository_everywhere`)
carries only ids, in the writing transaction. This process forgets at once, as before, not at
commit: a token being removed is not read with again from here on, even if the removal rolls back,
which costs one more mint. A listener whose connection dropped forgets every token and every Keep
the Why read when it is back: a lost notice could otherwise leave a removed token in use for up to
an hour, and asking the forge again costs a read.

A dropped connection forgets at once as well, since no notice arrives until it is back, and that
includes a first attempt that fails. A first connection that succeeds does not forget: nothing was
cached yet beyond the moments of its start, and clearing there would empty what a starting process
has just read. A link not `active` never
trusts a token held from before: only a mint that succeeds may turn it `active` again, or a replica
that missed the notice would undo what another one found. `removed` is final in `set_status`: a
listing that minted before the removal overwrites it neither with `active` nor with `suspended`,
which would also write the account's record in the wrong order. Listing a link mints like any other
read, so a mint that succeeds there turns it `active` as well; otherwise a link nobody reads through
would stay `suspended` beside its repositories and mint on every listing.

The stored source is a column of `project` (`none` when a choice found none, NULL before any), read
with the row every view has already, so no list reads it per project. A forge read often runs inside
a request that holds that project's row, and a second connection waiting for it would wait forever,
out of the database's sight. So the write takes the row `FOR UPDATE SKIP LOCKED` and leaves it to
the next choice when it is taken: the value is only shown. That holds for the pod that chose as
well: `probe_via` reads the column first, so its newer `_last_via` counts only when the next choice
has written. `_last_via` before the column would let a pod's old memory hide a fresher column.

**Reason:** with the probe and the image refresh on one pod (entry 24489a9c), the remaining
forge reads come from requests and are bounded by them; sharing every cache would put a database
read in front of each forge read for little gain. The budget is the one value whose divergence
causes errors (403 or 429 from the forge for everyone).

**Rejected alternatives:**
- **Share the caches too:** fewer forge reads, more database reads, and cache invalidation across
  pods for data that expires in minutes anyway.
- **The first connection of a process forgets too:** only the start window gains, and it would empty
  what a starting process has just read.
- **A held token may turn a link that is not `active` back to `active`:** a replica that missed the
  notice would undo what another one found.

## Attachments move to S3-compatible object storage

**Id:** a70d7269-a0a9-45aa-94c5-54715f112c10
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision for object storage instead of a shared `ReadWriteMany` volume (card tsk-enpbgadqgmbr, 2026-11-03), the coordinator's request of 2026-11-03 to record that with versioning a deletion becomes final only through a lifecycle rule, the build plan the coordinator accepted for it (2026-11-03: boto3 at runtime, no presigned URLs, hub and chart in separate pull requests), the maintainer's rule of 2026-11-03 that every setting keeps its single-server default; `attachment_store.py` (`BlobStore`, `LocalStore`, `S3Store`), kubernetes.md 9111cb2f (a 10 GiB `ReadWriteOnce` claim, tarred by the backup job)
**See:** kubernetes.md — 9111cb2f-89b0-4088-8c92-2fa5c1348ec7 — as of 2026-10-30
**See:** attachments.md#a-download-past-one-mebibyte-streams-and-holds-its-last-piece-back-until-the-digest-matches — 81f57cb5-f48a-43c7-9729-1d4e4de696b7 — as of 2026-11-03
**See:** attachments.md#the-blob-is-written-before-the-row-and-removed-when-the-row-never-commits-or-is-gone — 7dcd4850-9dc4-4b4a-9148-e156c8e11718 — as of 2026-11-03
**See:** replicas.md#the-volume-moves-into-the-bucket-by-a-copy-the-hub-runs-compared-by-the-digest-it-writes — 99360a7a-0de1-453f-88eb-9be12100c9c5 — as of 2026-11-03
**Revisit when:** the object store's latency shows in the load test of uploads and downloads

The store has two implementations behind one interface (`attachment_store.BlobStore`): `LocalStore`,
the default, for one replica, a laptop or a self-hosted hub, and `S3Store`, opt-in with
`MAITY_ATTACHMENT_STORE=s3` and the `MAITY_ATTACHMENT_S3_*` settings, chosen at start. Nothing about
the single-server setup changes: unset, the store is `local`, and `s3` is never a default.
`attachment_store.shared(settings)` says whether every replica sees the same bytes, true only for
`s3`; the several-pods check reads it rather than the setting's name.

`S3Store` talks to the bucket through boto3, one client per process. Downloads stay behind the hub's
access checks: the hub streams the object in 64 KiB pieces and checks its digest on the way; no
presigned URL leaves the hub. An upload is one `PutObject`, so a reader sees the old bytes or the new
ones, written before the upload's transaction and outside the project's lock (attachments.md
7dcd4850); the sweep and `remove_stray` keep their lock discipline and their grace, and delete
objects instead of files. Every error of the
client becomes a `StoreError` that names the operation and the service's error code, never a
credential, and the client's own loggers are held at `INFO`, since botocore logs each request's
headers at `DEBUG`. The chart renders the store and the bucket's settings (`attachments.store`,
`attachments.s3.*`, the credentials by Secret reference), and `maity-hub attachments copy-to-s3`
moves an existing volume into the bucket (99360a7a). With the bucket's versioning on, which is what
replaces the volume's tar as the backup, a deletion by the hub only adds a delete marker: the bytes
are gone for good only once a lifecycle rule expires the noncurrent versions, so a deployment with
versioning needs that rule for a deleted attachment to be deleted. The backup job without the
volume's tar follows once no deployment mounts the volume any more.

**Reason:** object storage scales and replicates independently of the nodes, a bucket is the usual
home for off-site backups anyway, and it removes the volume from every node's scheduling. A shared
file system brings NFS semantics (locking, latency on many small files) and is one more piece to keep
available; the hub writes files whole and never appends, which fits objects. boto3 is the client
every S3-compatible service is tested against, and its retries and request signing are not code the
hub has to keep.

**Rejected alternatives:**
- **`ReadWriteMany` shared file storage:** no hub change, but an NFS dependency on the hot path of
  downloads, and the tar backup stays.
- **Attachments in the database:** one store for everything, but large binary rows in the dump
  and in the WAL, and the database is the resource this design is trying to spare.
- **A client of the hub's own (SigV4 signing over the HTTP library it has):** no new dependency,
  but signing, retries and the differences between services become the hub's to get right.
- **Presigned download URLs:** less traffic through the hub, but a link that works for anyone who
  holds it for its lifetime, outside the hub's access checks and its digest check.

## The volume moves into the bucket by a copy the hub runs, compared by the digest it writes

**Id:** 99360a7a-0de1-453f-88eb-9be12100c9c5
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the card's scope (tsk-enpbgadqgmbr: "a command or documented step that copies the existing files from the volume into the bucket, idempotent"), the coordinator's request of 2026-11-03 for a one-off copy that checks the digest, the operator's question of 2026-11-03 whether the hub would read through instead, the reviews of #1282 on 2026-11-03 (an overwritten object, an unreadable folder, deleted attachments copied back, what the check after a put compares, a deletion while the hub still serves from the volume); `attachment_store.copy_local_to_s3`, `cli._copy_to_s3`
**Revisit when:** a deployment's volume is too large to copy while the hub serves, or a second migration (between buckets) is needed
**See:** replicas.md#attachments-move-to-s3-compatible-object-storage — a70d7269-a0a9-45aa-94c5-54715f112c10 — as of 2026-11-03

`maity-hub attachments copy-to-s3` reads `MAITY_ATTACHMENT_DIR` and writes every blob into the
bucket of the `s3` settings under the same key; without `--apply` it only counts. `S3Store` writes
each object with its SHA-256 as metadata (`x-amz-meta-sha256`), and the copy skips an object whose
metadata matches the file, so it runs as often as needed: once while the hub still serves from the
volume, once more after the store is switched, for the uploads in between. It never changes the
volume. An object the hub wrote with another SHA-256 is not overwritten but counted as different
(exit 1); only a missing object or one without the metadata is written. A file whose attachment
has no row, or a deleted one, is skipped: under `s3` the hub deletes only in the bucket, so the
volume still holds the files of redacted and expired attachments, and a later run would put them
back (with versioning on, as one more noncurrent version each time). The live ids are read once
per project, and right before and right after each put the copy asks again for that one row.
Before, it saves the write when the attachment was deleted since the ids were read, the usual
case. After, it closes the race with the deletion of a hub that already serves from the bucket:
the hub commits a deletion before it removes the bytes, so a deletion during the put is either
seen there and the object removed again, or its own removal comes after the put. In a versioned
bucket that race leaves one noncurrent version, which the lifecycle rule for noncurrent versions
expires (a70d7269). While the hub still serves from the volume, its deletions remove only the
file there, and an object the copy put earlier stays current in the bucket. So each run with
`--apply` ends with the sweep's removals against the bucket, without expiring rows (the hub's
own sweep does that): the object of a tombstoned row, and an object no row names once it is
older than `BLOB_GRACE`, the same bound that protects an upload in flight under `s3`. A run without
`--apply` counts these removals and deletes nothing, like the copy itself. What is
deleted after the last run stays in the bucket until the switch; from then on the hub's own
sweep removes it within its interval. A staging that is given up or rolled back leaves the bucket as
the last run left it: one more run with `--apply` cleans it, or the bucket's prefix is emptied. A pending
upload past its 24 hours that the sweep has not removed yet still has its row and is copied;
once the hub's sweep has expired the row, the object has no row and goes like any other. After each put one HEAD
compares the size and the metadata the put wrote, not the bytes: reading every object back would
double the traffic. Each file is read whole, at most `FILE_CAP` like an upload. A folder or
file the pod cannot read (`lost+found` on an ext4 volume) counts as failed, and the copy goes on.
There is no copy back: after the switch, uploads exist only in the bucket. The chart renders the bucket's settings whenever a bucket is set, also with `local`, so the
command finds them in the pod before the switch, and the claim may stay mounted under `s3` for the
second run.

**Reason:** the copy runs where both stores already are (the hub's pod, its settings, its
credentials), and needs no tool of the operator's. The digest it compares is the one the hub
checks on every download only while the file is intact: keys are immutable attachment ids, so other
bytes under a key the hub already wrote mean the file changed, and once the store is switched the
bucket is what the hub serves.

**Rejected alternatives:**
- **The hub reads through (from the volume when the bucket has no object):** two stores on the hot
  path of every download, for as long as the volume is mounted, and a volume still pinned to one node.
- **Overwriting an object whose digest differs from the file:** the first version of the copy did,
  and a file changed on the volume after the first run replaced good bytes in the bucket.
- **Copying every file and leaving deleted ones to the sweep:** the first version did. The sweep
  removes them again, but with the bucket's versioning on each run leaves the redacted bytes
  behind as one more noncurrent version.
- **Checking the bytes after each put** (reading the object back, or the store's own SHA-256
  checksum on the put): reading back doubles the traffic of the move, and not every
  S3-compatible store takes the newer checksum headers. The client checks the transfer itself.
- **Deleting in both stores while the hub still serves from the volume:** the hub would need the
  bucket's settings and credentials, and a working bucket, before the switch, and every deletion
  path two removals; the copy's own clean-up reaches the same state at each run.
- **Comparing by the ETag:** it is an MD5 of the bytes only for a single-part upload without
  server-side encryption by a managed key, which not every bucket guarantees.

## Connections: a per-pod pool sized to the database, PgBouncer only in session mode until prepared statements are off

**Id:** a83fc8e7-2bcf-4e68-ba41-90df345670a5
**Type:** constraint
**Status:** open
**Evidence:** inferred
**Source:** `db.postgres_options` (the `options` startup parameter, `db.py:71-112, 144`), `db.make_engine` (`pool_size` and `max_overflow` 16 and 16 by default, `pool_recycle` 1800 s, PostgreSQL `statement_timeout` and `idle_in_transaction_session_timeout`), the maintainer's internal deployment planning (2026-10-30) (a managed PostgreSQL whose connections are limited by its size, with its own pooler port in session, transaction and statement modes); psycopg 3 prepares named statements after a few runs
**Revisit when:** the load test sets the pool size, or `prepare_threshold=None` is in and tested behind PgBouncer's transaction mode

With N pods the hub asks for N × (pool + overflow) + N listener connections + health checks.
The chart sets `MAITY_DB_POOL_SIZE` and `MAITY_DB_MAX_OVERFLOW` per pod so that at the HPA's
maximum the sum stays under the service's limit with room for migrations and the backup. Behind
PgBouncer:
- **Session mode** works as is.
- **Session timeouts:** the hub sets `statement_timeout` and `idle_in_transaction_session_timeout`
  through the `options` startup parameter (`db.postgres_options`, used by `make_engine` and
  `make_health_engine`). PgBouncer refuses an unknown startup parameter unless it is listed in
  `ignore_startup_parameters`, and then it is ignored. Behind PgBouncer the timeouts move to the
  database role (`ALTER ROLE … SET`), and the hub stops sending `options` when told it is behind a
  pooler.
- **Transaction mode** needs `prepare_threshold=None` on the psycopg connection (a small setting
  the build adds and tests), and it cannot carry `LISTEN`: the listener connection of each pod
  (entry 387c2409) connects directly to PostgreSQL, past the pool, through an optional
  `MAITY_DIRECT_DATABASE_URL` (a managed pooler usually has its own port and database name; without the setting the listener uses `MAITY_DATABASE_URL`, right for a direct or
  session-mode connection). Nothing else in the design
  needs session state: the workers claim passes in a row (entry 24489a9c), not with advisory
  locks.
- Migrations connect directly, never through the pooler.

**Reason:** the connection limit is the first wall a horizontal scale-out hits on a managed
database; writing the arithmetic and the PgBouncer constraints down keeps the chart's defaults
from silently exceeding it.

**Alternatives:** none in contention; the numbers come from the load test.

## Rolling updates without downtime need expand/contract migrations; until then a release with a migration stops the hub

**Id:** 36157878-6d20-4270-adf7-c7cba965bcbb
**Type:** decision
**Status:** open
**Evidence:** inferred
**Source:** `app.require_current_schema` and `/api/v1/health` (`schema_outdated` when the database is not at the hub's own head), kubernetes.md cc9f37de and d295eb2a (the hook Job, `helm-upgrade.sh` stopping the hub)
**See:** kubernetes.md — cc9f37de-1684-41f1-b090-a2dc344a3673 — as of 2026-10-30
**Revisit when:** the first release that needs a breaking schema change after rolling updates are on

A release **without** a migration rolls with `RollingUpdate` (`maxUnavailable: 0`, `maxSurge: 1`),
which becomes safe once the entries above are built: old and new pods share every piece of state
through the database. A release **with** a migration keeps today's path (`helm-upgrade.sh`: stop,
migrate, start), a short gap.

Rolling over a migration is a second step: a migration declares itself `expand` (adds tables,
nullable columns, indexes; nothing the old version reads changes) or `contract` (removes what no
running version reads any more, shipped one release after the code stopped using it). A hub serves
on its own head **and** on any later head reached only by `expand` migrations, so old pods keep
serving while the hook expands and new pods start; `contract` migrations keep the stop path. The
`schema_outdated` readiness check becomes "not at a head I can serve on".

**Reason:** the 200 000-user goal makes a gap per release more expensive than it is today, but
the gap is seconds and only on releases with migrations; making every migration safe for two
versions at once is a discipline for every author, so it comes after the shared state, as its own
card, once the load test says the platform holds.

**Rejected alternatives:**
- **Rolling updates over every migration now:** an old pod writing against a contracted schema
  breaks, as the deadlock of 0060 already showed in the other direction.
- **Blue/green with two databases:** no schema overlap, but data written during the switch must be
  copied; out of proportion here.

## The chart offers replicas, an autoscaler, a disruption budget and spread only with what they need

**Id:** 2e7de08a-31ab-40ee-bfb8-7fc362562964
**Type:** decision
**Status:** superseded
**Superseded by:** ec91fe03-1e12-4fb6-8c8e-f09ae8528e5d
**Evidence:** inferred
**Source:** kubernetes.md 5e42eb26 (`replicas` fixed in the template, the values schema refuses unknown keys), the maintainer's internal deployment planning (2026-10-30) (HorizontalPodAutoscaler on CPU, PodDisruptionBudget, topology spread, an autoscaled node pool), routes/events.py (`WAIT_MAX` 55 s)
**See:** kubernetes.md — 5e42eb26-9883-49e2-89c0-9fe4e6517c62 — as of 2026-10-30
**Revisit when:** the load test shows CPU is not the signal that tracks load (open long-polls or connections instead)

The chart gets `replicas` (default 1), `autoscaling` (min, max, CPU target), a
PodDisruptionBudget (`minAvailable: 1` when more than one), topology spread over nodes, and
requests and limits from the load test. The values schema refuses `replicas > 1` and autoscaling
unless the database URL is PostgreSQL and the attachment store is `s3` (or a `ReadWriteMany`
claim), so a chart cannot start a second pod that would be unsafe. The strategy becomes
`RollingUpdate` for those releases (entry 36157878). No session stickiness at the ingress. A
draining pod already answers its long-polls at once (kubernetes.md 3194a790); clients re-poll and
land on another pod.

**Reason:** the one-pod rule's revisit condition is met by entries 387c2409, 1c65bb74 and
2bd65fec; the chart should then make the safe shape easy and the unsafe one impossible.

**Rejected alternatives:**
- **Scale on open connections or requests per second:** closer to what long-polls cost, but needs
  a metrics adapter; CPU first, the load test decides whether it is enough.

## Load test plan: k6 against 1, 2 and 4 pods, with targets set before the run

**Id:** cac80c88-8f31-4e98-96cb-23f66cda02b8
**Type:** decision
**Status:** open
**Evidence:** inferred
**Source:** the card (k6 or locust, target numbers), the maintainer's internal deployment planning (2026-10-30) (a staging address, 1, 2 and 4 pods; the run sets node pool, HPA target, database size and pool size), `hub/tests/test_load.py` (statement-count load tests of the bell), the request signature (HMAC-SHA256 over a canonical string, `auth/credentials.py:101`); the maintainer's answers to req-6cw5xwfpyeva (production, throwaway accounts) and req-gjzkcdtbg7t2 (a second confirmation for production), and req-3efa9j1v8ez2 (purge deletes every row), and req-zx1nhgy5r6ab (a second balancer for the run)
**Revisit when:** the maintainer gives a concurrency or traffic figure that replaces the assumptions below

**Tool: k6.** It holds tens of thousands of concurrent long-polls per load generator cheaply,
signs requests with `k6/crypto` HMAC-SHA256, and reports percentiles and thresholds that fail
the run. A seeding script (`hub/loadtest/seed.py`) creates projects, humans and agent credentials directly
in the test system's database first: the API's limits on logins and on agents per human are what
the run measures, and seeding through it would have to lift them. It refuses every database not
named by host, port and database, SQLite too: a hub may run on SQLite in earnest, and a host called
`db` says nothing. It takes one plain URL and refuses a query, several hosts and a missing host: the
driver takes the target from all of them and they win over the part a reader looks at. "Plain" covers the database name too: libpq reads a name containing
`=` as a connection string, and the URL's path is decoded into it, so it is one plain name. A list of
those cases was rejected, as reviews kept finding another; so was a list of production names alone,
as a database host is rarely named after the product.

Changed on 2026-11-02: the maintainer decided that the run goes against production while there is
no test system, with throwaway accounts there (req-6cw5xwfpyeva), and that the scripts stay closed
to `maity.team` unless `LOADTEST_CONFIRMED_PRODUCTION` names the host, then only through its
balancer (req-gjzkcdtbg7t2). The seed became `maity-hub loadtest seed`, in the hub's package: it
runs where the hub runs, on the hub's own database, since nobody connects to production's database
from outside, and a checkout's `tests/factory.py` is not in the image. That made the database URL
rules above moot: the name checked is the host of the hub's own `MAITY_PUBLIC_URL`, never a guessed
one. Accounts are `lt-<n>`, without a mail address or a password, so that nothing the run does
sends a mail; they are found by the prefix together with the password marker, not by the prefix
alone (see the purge paragraph below).

Changed on 2026-11-02, again: `maity-hub loadtest purge` deletes the accounts afterwards, every row
in every table (req-3efa9j1v8ez2, the maintainer chose this). The account deletion of §2.9 was the
other option and lost: it revokes every key but keeps the account as a tombstone with its handle
taken, needs the projects archived first and keeps them with their events, since the hub has no way
to delete a project. `purge` follows the foreign keys from the humans, projects, agents and
memberships until nothing new turns up, adds the few tables that name an account without one, and
is refused when an account shares a project or a row with anyone else. It takes only humans with
both the name and the seed's password marker: `lt-<n>` is not a reserved handle, and a real person
who signed up as `lt-7` with a project of their own would otherwise pass every refusal and be
deleted (found in the review of the purge). Reserving the prefix was the other option; it changes
the contract's reserved words and was left for its own change, and the marker is needed even then,
for an account made before the reservation. Its test reads every table
after a purge for the accounts' ids, keys and handles, so a new table that keeps one fails there.

Changed on 2026-11-02, the third time: production may be reached through more than one name. One
balancer in front of production carries fewer held connections than the half of the plan, and the
maintainer added a second one for the run, reached under a name of its own (req-zx1nhgy5r6ab);
the full plan stays off production. `LOADTEST_CONFIRMED_PRODUCTION` became a list, and `run.js`
takes exactly one target for each name in it, production never beside another system and no
target twice. The rule it replaces, one production target, kept k6 off the pods one by one; a
name cannot tell a balancer from a pod, so the names the operator confirms are what is allowed,
and a name confirmed but not targeted is refused as well, as a sign the two lists were not set
together. Connecting to both balancers under the one production name, through k6's `hosts`
option, was the other way; k6 maps a name to one address, so it would not have spread the load
(inferred, not tried). The seed reads the same variables as lists too, so that one setting serves
both, and takes the host as `run.js` does: a trailing dot is refused, since `maity.team.` is
production and would otherwise have passed as a test system's name (found in the review). Twice
means the same host and port as reached (`https://a` and `https://a:443`); another port on one
host stays another target, as a test system's pods may be port-forwards on one machine.

Changed on 2026-11-04: the prefix is now reserved (tsk-ch8nt5dfgmp7). A person or an organisation
may not take a handle of the form `lt-` followed by digits; an agent's handle is not held to it.
The seed still creates `lt-<n>` by writing the rows itself, not through the check that refuses the
handle. `purge` still requires the password marker, for accounts made before the reservation.
Whoever already holds such a handle keeps it: nothing is migrated or renamed.

The 60 000 held connections are spread over several generator pods with their own source
addresses: one source address has about 64 000 ephemeral ports, and the run must measure the
hub, not the generator's port exhaustion.

**Assumptions** (the user count does not give a concurrency; these are stated so they can be
replaced): of 200 000 registered humans, 10 % online at the peak hour, each with one dashboard
(bell long-poll) and two agents in `maity wait`; one write per agent per minute on average; 2 %
of the humans signing in during the peak hour. That is 20 000 bell waits, 40 000 event waits,
about 670 writes a second and about 1.1 logins a second.

**Scenarios**, each at 1, 2 and 4 pods, ramped to 25 %, 50 % and 100 % of the assumed peak:
1. **Idle waits:** 40 000 event long-polls and 20 000 bell long-polls held, re-polling at
   55 s. Measures memory and connections per pod and database reads per second while nothing
   happens.
2. **Wake-up across pods:** writes through pod A, waiters on pods B and C; the time from the
   write's commit to the waiter's answer.
3. **Mixed traffic:** the writes above (messages, card moves, reports) with their wake-ups, plus
   bell pages and board reads at one read per waiter per minute.
4. **Limits and replays:** login and join-exchange bursts spread over all pods; one captured
   signed request replayed on every pod, and again after a restart of the database and after a
   failover of the managed service.
5. **Pod loss and rollout:** one pod killed under scenario 3; a `RollingUpdate` without a
   migration under scenario 3.

**Targets** (thresholds the run must meet at 100 % with 4 pods):
- wake-up across pods p95 under 1 s, p99 under 2 s;
- API p95 under 300 ms for writes, under 200 ms for reads; no 5xx except during scenario 5's kill
  (where clients' retries must succeed within 10 s);
- every rate limit exact to within one window's share across all pods; a replayed request accepted
  zero times after its first, also across a database restart and a failover;
- the probe's and the image refresh's forge reads per interval the same at 1, 2 and 4 pods;
- commit latency of notifying writes p95 under 50 ms at the peak write rate;
- database connections under 70 % of the service's limit; CPU per pod under the HPA target at the
  planned replica count;
- with the in-process wake-up gone, database reads while idle grow with changes, not with waits.

The run's numbers set the node pool's maximum, the HPA target, the pool size per pod and the
database size. The statement-count tests of `test_load.py` stay as the per-request
guard in CI.

**Reason:** a plan with thresholds fixed before the run makes the result a pass or a fail, not an
interpretation; the scenarios are exactly the behaviours the entries above change.

**Rejected alternatives:**
- **locust:** Python like the hub, but one gevent worker holds far fewer concurrent long-polls,
  so 60 000 waits need a fleet of workers.

## Build order: one card per entry, the shared state first

**Id:** 8ebcc11b-85cf-48bf-9af5-5371d3a33f14
**Type:** decision
**Status:** open
**Evidence:** inferred
**Source:** the card's step 2 ("build cards from the design"); the dependencies between the entries above
**Revisit when:** the coordinator orders the cards differently

1. Nonces in the database (1c65bb74), with the epoch row replacing `PROCESS_STARTED`.
2. Shared limits, breakers and guess counters (2bd65fec).
3. NOTIFY wake-ups, cross-pod superseding and the listening table (387c2409), including the bell
   and device-code waits and their superseding.
4. The `worker_run` claim with its interval and lease, the digest's lock order and the presence
   upsert (24489a9c); the shared forge budget, the forget channel and the stored `probe_via`
   (83da2bfa).
5. `S3Store` (a70d7269, built), then the chart values and the backup change.
6. Chart: replicas, autoscaling, disruption budget, spread, values gate, `RollingUpdate` for
   releases without migrations, pool sizing, the `prepare_threshold` setting, the timeouts on
   the role and `MAITY_DIRECT_DATABASE_URL` (2e7de08a, a83fc8e7); kubernetes.md 5e42eb26 is
   superseded then.
7. The load test (cac80c88) on staging, then the sizes.
8. Expand/contract migrations (36157878), after the load test.

Each of 1 to 4 is testable on one process against PostgreSQL with two engines standing in for two
pods, as the race tests of `hub/tests` already do with two connections.

**Reason:** 1 to 3 are the conditions of the one-pod rule's revisit; nothing about replicas is
safe before them, and each is small enough to review alone.

**Alternatives:** none in contention.

## The newer start decides which wait of a key stays, inside a process too

**Id:** 7c2e91d4-5b0f-4a63-8e17-2f6ad0c4b915
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-yze5b0bvbewn; `test_a_superseded_wait_reads_nothing_and_keeps_the_cursor` failed on `hub-postgresql` once (PR #1018)

`Registry.enter` compares the waits' starts on the database clock, as `wakeups.supersede` does, and an older wait that arrives
after a newer one ends itself. A wait takes its start in `wakeups.opened` and reaches `enter` only after that, so two requests
can arrive in the opposite order. When arrival decided in the process and the clock across replicas, each wait ended the other,
and both answered `superseded` with no items. No event was lost; it cost one more wait. At the same start, or without a clock on
SQLite, the later arrival still takes over.

**Rejected alternatives:**
- Entering before the announcement, so that arrival and start share an order: the start comes from the database, and the wait
  would have to hold a key it has no start for.

## Several workers per pod: uvicorn's supervisor, each process a replica of its own

**Id:** 4e24abd8-ab64-4844-897b-629bfa211f6d
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-hnp19jx1ajvx; the maintainer's rule for the scaling cards (2026-11-03): the single-server hub (one process, SQLite, local attachments) stays the default and keeps working, every scaling path is opt-in; `serving.py`, `cli._serve_workers`, `tests/test_workers.py`; uvicorn 0.54 `supervisors.multiprocess`
**Revisit when:** uvicorn's `Multiprocess` changes how it builds a worker's `Server`, or the load test shows that more workers per pod buy less than more pods

`MAITY_WORKERS` (chart: `config.workers`) sets how many processes `maity-hub serve` runs on one
socket. The default is 1, and 1 is the hub as it always was: one process, no supervisor, any
database. More than one is refused at start on anything but PostgreSQL, since the processes share
wake-ups, nonces, limits and worker passes only through it. Each process is a replica in every
sense the entries above use: its own `listening.POD`, its own LISTEN connection, its own
`hub_pod` row, its own claims in `worker_run`. Nothing in the coordination knows about pods,
only about processes.

- **The pool is the hub's total.** `MAITY_DB_POOL_SIZE` and `MAITY_DB_MAX_OVERFLOW` keep their
  meaning for the operator; each process holds its share, rounded down, so raising the workers
  never adds to the connections asked of the database (entry on connections above). A share
  below two pooled connections is refused at the start: a request may hold its transaction's
  connection while a shared count or the forge budget takes a second from the same pool (entry
  2bd65fec), and a process with one waits on itself until the pool's timeout. The listener
  connections (one per process) and the readiness probe's come on top.
- **The checks and the one-time work of a start run in the parent** before any worker is
  spawned: the startup checks (schema, secrets, mail, reserved holders, a required dashboard
  directory), then `app.start_once` (the generated text, the public pages, the sign-in
  switches). Each worker checks again at its own start but does no one-time work, so N
  processes starting together do not race each other. Pods starting together still run
  `start_once` each: its steps take a lock (`db.xact_lock`, a transaction-level advisory lock
  that works behind PgBouncer in any mode) or are claimed under one, and the public pages are
  rendered again page by page, never cleared first, so a sibling serving meanwhile finds the
  old page or the new one. A worker that fails to build its app exits with uvicorn's start
  failure, so the supervisor stops and `serve` exits non-zero instead of starting it again and
  again.
- **A stop releases the open waits** in every worker, as in one process: the supervisor's
  processes use the hub's own `Server`, which hands the release to the loop on SIGTERM.
- The request stats line names its process (`pid=`), since each process counts its own.
- **What stays per process** is what stays per pod (the "Weaker" list at the top): caches,
  `registration.DROPPED`, the forge budget's in-flight count, the stats. An isolation ends the
  isolated agent's waits at once in the process that ran it; a wait held by another process
  ends at its next read, within the two-second fallback.
- A worker that dies leaves its `hub_pod` row until it goes stale, as a dead pod does; the
  supervisor starts a new one. uvicorn's SIGTTIN adds a process past `MAITY_WORKERS` and past
  the pool's split: not a way to scale the hub.
- **Memory** grows with the processes (about 130 MB each when idle): the chart's memory limit
  has to grow with `config.workers`.

The opt-in default is the maintainer's rule (confirmed); the reasons below are inferred.

**Reason:** a pod with several cores served one event loop; a second process per pod uses them
without a second pod, its own scheduling and its own share of node memory. The coordination for
replicas was already per process, so workers needed no new shared state.

**Rejected alternatives:**
- **Gunicorn with uvicorn workers:** a second server to install and configure for what uvicorn's
  own supervisor does, and one more dependency in the image.
- **Several workers on SQLite:** each process would wake only its own waits and count its own
  nonces and limits; the refusal keeps the single-server setup on the path that is correct.
- **The pool per process:** simpler to explain, but the database's connection limit would then
  depend on two settings multiplied, and a raised `MAITY_WORKERS` could exhaust it.

## Several pods: `replicas` in the chart, opt-in, refused where the pods would not share

**Id:** ec91fe03-1e12-4fb6-8c8e-f09ae8528e5d
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-fnff0s1n0zpg; the maintainer's rule for the scaling cards (2026-11-03): the single-server hub stays the default and keeps working, every scaling path is opt-in; entries 2e7de08a, 36157878 and a83fc8e7 above; `serving.refusal`, `serving.connections`, `app.warn_on_connection_budget`; `deploy/helm/maity-hub` (`replicas`, `templates/pdb.yaml`); `tests/test_two_processes.py` (two pods, one or two workers each)
**Revisit when:** attachments get a shared store other than S3 (a `ReadWriteMany` claim), the load test sets requests, limits or the pool per pod, or expand/contract migrations let a release with a migration roll

The chart's `replicas` (default 1) sets the Deployment's pods and `MAITY_REPLICAS`. One replica
is the hub as before: `Recreate`, no disruption budget, no spread, any database the hub
supports. More than one:

- **Refused where pods would not share.** The hub refuses to start with `MAITY_REPLICAS` above 1
  on anything but PostgreSQL, or with a local attachment directory (each pod's volume holds only
  the files it took). The chart refuses `attachments.existingClaim` with `replicas` above 1
  before anything is installed. The database URL lives in a Secret the chart never reads, so
  that refusal is the hub's alone; it can only trust what the deployment states, since nothing
  off PostgreSQL could count the pods.
- **Rolled one at a time** (`RollingUpdate`, `maxUnavailable: 0`, `maxSurge: 1`) for a release
  without a migration. A release with a migration still goes through
  `deploy/scripts/helm-upgrade.sh`, which scales to 0 and, after a successful upgrade, leaves
  the replicas the release renders (Helm resets a scaled Deployment to the chart's value, and a
  changed `replicas` must not be undone), also when the rollout check after Helm fails (the way
  back is `helm rollback`); when it ends before Helm or Helm fails, it scales back to the
  replicas it found (entry 36157878), until migrations are expand/contract. A hub found at 0 stays at 0.
- **A PodDisruptionBudget** with `minAvailable: 1`, rendered only with more than one replica: for
  one pod it would block every node drain.
- **Spread over nodes** (`kubernetes.io/hostname`, `maxSkew: 1`, `ScheduleAnyway`), replaceable
  through `topologySpreadConstraints`; `ScheduleAnyway` so a single-node cluster still starts
  every pod.
- **The connection budget** is pods × (workers × (pool share + overflow share + 1) + 1): each
  worker holds its share of the pod's pool and overflow (`serving.per_worker`, rounded down)
  plus its LISTEN connection, and each pod one more for the readiness probe. With more than one
  replica, pods counts the surge pod of a rolling update too (replicas + 1). The chart sets the pool per pod (`database.poolSize`, `.maxOverflow`). At its start the
  hub warns when the sum exceeds `max_connections` less the reserved connections; only a
  warning, because behind a pooler the server's limit is not the one that counts.

The opt-in default is the maintainer's rule (confirmed); the shape of each point above is inferred.

**Reason:** the shared state the entries above built is what makes a second pod safe; the
chart makes that shape one value and the unsafe shapes fail before or at the start, while the
single-server setup changes in nothing.

**Rejected alternatives:**
- **The chart deciding from the database URL:** the URL is in a Secret Helm does not read, and
  reading it in a template would put it into the rendered manifests.
- **A refusal of the connection budget:** a managed pooler in front reports the pooler's limit,
  not the server's, and the hub cannot tell which it reached.
- **An autoscaler in this step** (entry 2e7de08a): left for after the load test, which decides
  whether CPU tracks load; `replicas` is the manual setting it would later drive.
