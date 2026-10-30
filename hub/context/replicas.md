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
**Source:** the maintainer's goal "simple scaling toward about 200 000 users in two weeks" (inbox, 2026-10-30, seq 15111) as carried by the card; `docs/ops/ovh-prod.md` §12 (#726, managed PostgreSQL); the inventory of process state on `main` 2026-10-30
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

**Reason:** every pod already holds a pool to PostgreSQL, and the managed service of the
production plan (#726) is highly available; a second stateful service would add a failure mode,
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

## Wake-ups cross pods through NOTIFY sent in the writing transaction, one LISTEN connection per pod

**Id:** 387c2409-1c68-4bf8-a9a0-8a56a4002545
**Type:** decision
**Status:** open
**Evidence:** inferred
**Source:** `events.transaction` and `Notifier` (events.py:45-110), `longpoll.Registry` (longpoll.py:35-79), `routes/events.py` (`FALLBACK_SECONDS = 2.0`), `routes/notifications.py` (polls `listing.stamp` every 0.5 s), `listening.py`; PostgreSQL documentation of `NOTIFY` (delivered at commit, never for a rolled-back transaction, payload under 8000 bytes)
**Revisit when:** NOTIFY throughput or the listener connection shows up as a limit in the load test (a transaction that notified takes a database-wide lock on the notification queue at commit, so notifying writers serialise there; the load test measures commit latency for it), or a wake-up is measured late across pods

Today a commit wakes only the waiters of the process that committed (`notifier.notify` after
`engine.begin()`); a waiter on another pod sees the row at its 2-second fallback re-read. The
design:

1. `events.emit` adds `SELECT pg_notify('maity_events', '<project_id>:<seq>')` to the writing
   transaction. PostgreSQL delivers it at commit and drops it on rollback, so a wake-up never
   precedes its row and never announces a row that does not exist. The local `notifier.notify`
   after commit stays, so the writing pod wakes without the round trip.
2. Each pod opens one connection outside the pool that runs `LISTEN maity_events` (and the
   channels below) and feeds `longpoll.registry.notify`. When that connection drops, the pod wakes
   every waiter and reconnects with backoff, so a missed notification costs one re-read, not an
   event. The waiters re-read spread over a random 0–2 s, not all at once: a pod holding 10 000
   waits must not send 10 000 reads in the same instant. The 2-second fallback stays as the safety net and
   can be raised to about 10 s once the load test shows the listener reliable.
3. **Superseding across pods:** a new long-poll of a key (`credential_id`, `session:<cookie>`,
   runner key) sends `pg_notify('maity_supersede', key || ':' || token)` when it starts; a pod
   holding an older wait of that key ends it with `superseded`. The rule of §8.3, "the wait that
   took over owns what came in", holds again across pods. The bell's and the device codes' own
   "newer wait supersedes" maps (`routes/notifications._holding`, `routes/device_codes._holding`)
   move onto the same channel. A closing wait removes only what it owns: its own `wait_id`
   (point 4), never the row or the holder entry of the wait that superseded it, as
   `longpoll.Registry` already checks today in the one process.
4. **The listening registry moves to the database:** an `UNLOGGED` table `long_poll(wait_id,
   listening_key, pod, opened_at)`, one row per open wait, keyed by a fresh `wait_id`, inserted
   when a wait opens and deleted by that `wait_id` when it closes, so two waits of one key (today
   `listening._open` counts them, +1 and −1) never delete each other's row. `listening_key` is
   what `is_listening` is asked with today: the agent session's id, or the runner's listening key;
   superseding (point 3) keeps its own key, the credential or the cookie session. Each pod
   refreshes a heartbeat row `hub_pod(pod, seen_at)` every 15 s, and a wait whose pod has not been
   seen for 45 s does not count. `is_listening` counts the live rows of its key (batched per call
   where `team_wakes` asks for many instances). A crashed pod's rows stop counting after 45 s and
   are removed by the next pod's sweep.
5. **The bell and the device-code waits** (0.5 s and 0.25 s polls of the database per open wait)
   move onto the same wake-up: a notification-relevant write (event, account record, read mark)
   notifies `maity_bell` with the human's id, and a device-code write (`redeem`, `approve`,
   `deny`, `void_open`) notifies `maity_device` with the code's key. With 20 000 open dashboards the 0.5-second poll alone
   would be 40 000 stamp reads a second; on the wake-up it is a read per change.

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
**Status:** open
**Evidence:** inferred
**Source:** `auth/credentials.py:108-129` (`NonceWindow`, its docstring "this moves to the database before a second"), `auth/caller.py:249-277` (`TIMESTAMP_WINDOW_SECONDS` 300, `NONCE_WINDOW_SECONDS` 600, `PROCESS_STARTED`), `idempotency.py` (POST and PATCH of agents and runners need an `Idempotency-Key`)
**Revisit when:** the insert per signed request shows in the load test as a write bottleneck, or the signing scheme changes

A signed request's nonce is claimed with `INSERT INTO request_nonce (credential_id, nonce,
expires_at) VALUES (…) ON CONFLICT DO NOTHING`; no row inserted means a replay, refused as today.
The claim happens after the signature verifies, as now, in its own short transaction. A sweep
deletes rows past `expires_at` (600 s, twice the timestamp window). The table is `UNLOGGED`: no
WAL per request.

An `UNLOGGED` table is emptied by a crash of the database and is not replicated, so it is empty
on a promoted standby after a failover. `PROCESS_STARTED` is therefore replaced by an **epoch
row that vanishes exactly when the nonces do**: a one-row `UNLOGGED` table `nonce_epoch(since)`.
Each check reads it in the same round trip as the claim; when it is missing, the first pod to
notice inserts `now()` (`ON CONFLICT DO NOTHING`, then reads it back), and every request signed
before `since` is refused (`timestamp_skew`), on every pod. A database restart or a failover
thus closes the replay gap at once, and a newly started pod no longer refuses requests that
another pod would take. Reading one row per request takes no lock and stays in the buffer cache.

**Reason:** a replay across pods today repeats a DELETE, a PUT, the exempt paths
(`/api/v1/join/`, `/api/v1/auth/`, `/me/resume`) and any GET within ±300 s, once per pod; only
POST and PATCH are covered by the idempotency store. One primary-key insert per signed request
is the cheapest shared check there is.

**Rejected alternatives:**
- **A logged table:** survives a crash and a failover, so it needs no epoch, but writes WAL for
  state that is worthless after ten minutes; the epoch row covers both cases for one read.
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
**Status:** open
**Evidence:** inferred
**Source:** `registration.DROPPED` (`registration.py:377`, read at `:292`), `ratelimit.Limiter` and its about thirty module-level instances (auth, registration, email links, device codes, joins, runner pairing, second factor and its reset, exports, test mail, invitations, uploads, avatars, mentions, ticker, notes, forge webhook, badges, public pages); `second_factor._wrong_in_session`; `device_codes._breaker`; `registration.BREAKER`; `docs/ops/ovh-prod.md` §12
**Revisit when:** the counter writes show in the load test, or a limit needs exact sliding-window semantics across pods

`ratelimit.Limiter` keeps its interface (`hit`, `give_back`) and gets a shared backend on
PostgreSQL: an `UNLOGGED` table `rate_count(bucket, key, window_start, count)`, incremented with
`INSERT … ON CONFLICT DO UPDATE SET count = count + 1 RETURNING count`, read as a sliding window
approximated by the current and the previous fixed window (weighted by the overlap). `give_back`
decrements. The breakers and `_wrong_in_session` become buckets of the same table, and so does
`registration.DROPPED`: the count of refused registrations an admin reads as
`requests_dropped_last_hour` is the sum over every pod, not the answering pod's. A sweep deletes
windows older than their limit's span. On SQLite and MariaDB the in-process backend stays.

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
**Status:** open
**Evidence:** inferred
**Source:** the fifteen `Worker` classes started in `app.py` (attachments, availability, commitment, images, jour fixe, mail outbox, notification mailer, not-listening and its digest, organisation invitations, probe, registrations, reports, request stats, takeovers) and how each picks its rows; `not_listening_digest.reconcile` (reads `latest()` before the human's lock); `jourfixe` `record_presence` (insert into `presence_minute` without a lock); `probe.Worker` (forge calls every 120 s and 300 s)
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

## The forge budget is shared; forge caches stay per pod

**Id:** 83da2bfa-ee4b-4f35-bfe7-d12d7780f575
**Type:** decision
**Status:** open
**Evidence:** inferred
**Source:** `forge.py:125-126` (`_budgets`: `remaining`, `in_flight`, `until` per token, `LOW` reserve of 5 %), `forge.py:246-250` (`_visible`, `_public`), `github_app.py:182` (`_tokens`), `forge_access.py:62` (`_chosen`), `forge_access.py:258-277` (`_last_via`, `probe_via`, read in `views.py:185` and `releases.py:190`), `forge_links.forget_token`, `ktw.CACHE` and its `forget` at `routes/projects.py:743`, `contract_text`
**See:** keep-the-why.md — f5af1bd9-bb11-4310-b751-334de2668dfe — as of 2026-10-30
**Revisit when:** forge reads per hour approach the token's limit with the probe on one pod, or a cache's staleness across pods is seen by a user

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

**Reason:** with the probe and the image refresh on one pod (entry 24489a9c), the remaining
forge reads come from requests and are bounded by them; sharing every cache would put a database
read in front of each forge read for little gain. The budget is the one value whose divergence
causes errors (403 or 429 from the forge for everyone).

**Rejected alternatives:**
- **Share the caches too:** fewer forge reads, more database reads, and cache invalidation across
  pods for data that expires in minutes anyway.

## Attachments move to S3-compatible object storage

**Id:** a70d7269-a0a9-45aa-94c5-54715f112c10
**Type:** decision
**Status:** open
**Evidence:** inferred
**Source:** `attachment_store.py` (`LocalStore` under `MAITY_ATTACHMENT_DIR`, written whole with `os.replace`), kubernetes.md 9111cb2f (a 10 GiB `ReadWriteOnce` claim, tarred by the backup job), `docs/ops/ovh-prod.md` §12 ("shared file storage or S3-compatible object storage; which one is a decision for that card")
**See:** kubernetes.md — 9111cb2f-89b0-4088-8c92-2fa5c1348ec7 — as of 2026-10-30
**Revisit when:** the coordinator or the maintainer prefers shared file storage, or the object store's latency shows in the load test of uploads and downloads

The store gets a second implementation, `S3Store`, behind the same interface
(`MAITY_ATTACHMENT_STORE=s3`, bucket, endpoint, region, credentials from a Secret), chosen at start.
Downloads stay behind the hub's access checks: the hub streams the object (or answers with a
presigned URL of a minute, a choice for the build card); uploads are written by the hub as today.
The sweep and `remove_stray` keep their project-lock discipline and delete objects instead of files.
Backups stop tarring a volume: the bucket's versioning (and replication to the second location of
the production plan) replaces the attachment tar, and the dump marker stops requiring it.
`LocalStore` stays for one replica and for development.

This is the one entry where the choice is the maintainer's as much as the design's: shared file
storage (`ReadWriteMany`, OVH's file storage) would need no code change in the hub, only in the
chart and the backup job. The recommendation is object storage, for the reasons below.

**Reason:** object storage scales and replicates independently of the nodes, the production plan
already orders a bucket for backups, and it removes the volume from every node's scheduling. A
shared file system brings NFS semantics (locking, latency on many small files) and is one more
piece to keep available; the hub writes files whole and never appends, which fits objects.

**Rejected alternatives:**
- **`ReadWriteMany` shared file storage:** no hub change, but an NFS dependency on the hot path of
  downloads and the tar backup stays.
- **Attachments in the database:** one store for everything, but large binary rows in the dump
  and in the WAL, and the database is the resource this design is trying to spare.

## Connections: a per-pod pool sized to the database, PgBouncer only in session mode until prepared statements are off

**Id:** a83fc8e7-2bcf-4e68-ba41-90df345670a5
**Type:** constraint
**Status:** open
**Evidence:** inferred
**Source:** `db.postgres_options` (the `options` startup parameter, `db.py:71-112, 144`), `db.make_engine` (`pool_size` and `max_overflow` 16 and 16 by default, `pool_recycle` 1800 s, PostgreSQL `statement_timeout` and `idle_in_transaction_session_timeout`), `docs/ops/ovh-prod.md` §12 on the branch of #726 (open when this was written; the figures are that plan's, not checked here) (about 100 connections per 4 GB of the managed service, at most 1000; OVH's PgBouncer in session, transaction and statement modes; psycopg 3 prepares named statements after a few runs)
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
  `MAITY_DIRECT_DATABASE_URL` (the pooler is its own port and database name on the managed
  service; without the setting the listener uses `MAITY_DATABASE_URL`, right for a direct or
  session-mode connection). Nothing else in the design
  needs session state: the workers claim passes in a row (entry 24489a9c), not with advisory
  locks.
- Migrations connect directly, as the production plan says.

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
**Status:** open
**Evidence:** inferred
**Source:** kubernetes.md 5e42eb26 (`replicas` fixed in the template, the values schema refuses unknown keys), `docs/ops/ovh-prod.md` §12 (HorizontalPodAutoscaler on CPU, PodDisruptionBudget, topology spread, hourly autoscaled node pool), routes/events.py (`WAIT_MAX` 55 s)
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
**Source:** the card (k6 or locust, target numbers), `docs/ops/ovh-prod.md` §12 (staging address, 1, 2 and 4 pods, sets node pool, HPA target, database flavor and pool size), `hub/tests/test_load.py` (statement-count load tests of the bell), the request signature (HMAC-SHA256 over a canonical string, `auth/credentials.py:101`)
**Revisit when:** the maintainer gives a concurrency or traffic figure that replaces the assumptions below

**Tool: k6.** It holds tens of thousands of concurrent long-polls per load generator cheaply,
signs requests with `k6/crypto` HMAC-SHA256, and reports percentiles and thresholds that fail
the run. A seeding script creates projects, humans and agent credentials through the API first.
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
database flavor (#726 §12). The statement-count tests of `test_load.py` stay as the per-request
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
5. `S3Store` and the backup change (a70d7269), once the storage choice is confirmed.
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
