# Testing

## Test matrix: full check on SQLite, the suite again on PostgreSQL 17 and MariaDB 11.4, a subset on MariaDB 11.8

**Id:** c7d0850a-a677-4f0f-a209-e64da3b0fe8f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's brief for the hub skeleton, 2026-10-21 (SQLite, PostgreSQL and MariaDB in CI); implementation session, 2026-10-21 (job split, versions, shared-database fixture); card tsk-5cah3a82dv63 (the subset on MariaDB 11.8, #2022)
**Revisit when:** a user reports a difference between MySQL and MariaDB, or a query relies on behaviour the two engines implement differently
**See:** https://github.com/oliver-zehentleitner/maity — 3dacd29b-bd09-4757-80bb-7f3cfbd9af91 — as of 2026-10-21
**See:** persistence.md#a-name-mysql-or-mariadb-reserve-is-quoted-with-quotetrue-not-renamed — e70b5933-72f5-4951-b024-b92fe22dc521 — as of 2026-11-20

CI runs `make check` (black, ruff, mypy strict, pytest) on SQLite with
an editable install, pytest alone against a PostgreSQL 17 and a MariaDB
11.4 service container, pytest against the built wheel installed
non-editable on Python 3.13 with the source tree removed, and a job that
builds the image and migrates with it. The suite picks the database from
`MAITY_TEST_DATABASE_URL`; without it every test gets its own SQLite
file. On a server database the fixture downgrades to the empty schema
before and after each test instead of creating a database per test. Since 2026-10-28 a test that needs the schema keeps it from the test before
(rows deleted), and each parallel worker has its own database: see the entry on
the parallel suite below.

Which engines run in CI — SQLite, PostgreSQL and MariaDB — came from
the coordinator's brief; the job split, the versions and the fixture were
decided in the implementation session.

Since 2026-11-20 `hub-mariadb` also runs a subset on MariaDB 11.8 LTS: the
migrations, the schema checks and the notification tests. 11.7 reserved
`vector`, a column name of the hub, and 11.4 alone could not show it (the
entry on reserved names in `persistence.md`). The full suite stays on 11.4.

**Reason:** lint and types do not depend on the database, so they run
once; the tests are what differs per engine. An editable install tests
the source tree, not what ships: a file the wheel leaves out (a migration,
`help.md`) or a broken image would pass, so the wheel and the image have
jobs of their own; the wheel job also backs "Python 3.12 or newer". PostgreSQL 17 is the
production engine. MariaDB represents the MySQL family because the brief
names it; that this is enough rests on the hub using only `op.*`
migrations and portable Core queries, where the two engines behave
alike. Downgrading to the empty schema
needs nothing beyond the one database a CI service or a developer's
container already provides, and doubles as the test that every
migration downgrades.

**Rejected alternatives:**
- A fourth job on MySQL 8 — the closest match to "MySQL supported", but
  another service container on every push for a difference the portable
  subset does not reach; added when the revisit condition fires.
- One job with all three databases as services and a loop — fewer jobs,
  but one engine's failure hides the others' results and every run pays
  for all three containers.
- A fresh database per test (`CREATE DATABASE`) — the cleanest isolation,
  but it needs administrative rights on the test server and is slow on
  MariaDB.

## Races are tested on two real connections, on PostgreSQL and MariaDB only

**Id:** 0326b02f-c73b-44c5-88dd-98fe9fd19710
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-25 (the limit expiry's race test)
**Revisit when:** the hub runs on a database whose isolation differs from both again, or SQLite gets concurrent writers

`tests/concurrency.py` opens two connections, each in its own transaction,
and runs their steps in a fixed order; a step that must wait for the other
runs in a thread, and the test asserts it is still blocked before releasing
it. The helpers skip on SQLite, so these tests run in CI's PostgreSQL and
MariaDB jobs.

**Reason:** a compare-and-set or a lock is only shown to work by a second
writer that reads, waits or loses at the right moment. SQLite serialises all
writers, so the same test there would pass without proving anything. Both
server databases run under READ COMMITTED (`db.make_engine` sets it), but
they lock rows and resolve a conditional UPDATE each in their own way, which
is what such a race exercises.

**Rejected alternatives:**
- Simulate the second writer by changing the row between two calls on one
  connection: it shows the comparison, never the waiting on a lock.
- Run the race on SQLite as well: a green result there means nothing.

## The suite runs in parallel, one database per worker, and the wheel job runs a marked subset

**Id:** 081792e2-758e-4202-84f7-c2957459665e
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-ta0xcr6s4qwg (the coordinator's proposal after hub jobs took 60 to 90 minutes, 2026-10-27); implementation session, 2026-10-28 (local before/after measurement)
**Revisit when:** a test needs state shared between workers, or the CI runners change their core count
**See:** testing.md#test-matrix-full-check-on-sqlite-the-suite-again-on-postgresql-17-and-mariadb-114-a-subset-on-mariadb-118 — c7d0850a-a677-4f0f-a209-e64da3b0fe8f — as of 2026-10-28

`make test` runs pytest with `-n auto` (pytest-xdist). On SQLite each test
still gets its own file, but a migrated one is copied from a template that
each process migrates once, instead of replaying every revision per test, and
the teardown no longer downgrades a file that goes away with the test. On
PostgreSQL and MariaDB each worker gets a database of its own next to the
configured one (`<name>_gw0`, …), created through
`MAITY_TEST_ADMIN_DATABASE_URL` (MariaDB: root, which also grants the test
user). Inside it a test that needs the schema (`migrated`, `client`) finds it
at head from the test before and only has its rows deleted (`TRUNCATE`); a
test that needs no schema gets it downgraded, and the session leaves the
database empty. Every such downgrade deletes the rows first: the test before
leaves its rows at head, some of them a migration refuses to downgrade (a
project an organisation owns, 0089), and which test ran before is up to the
workers. The
hub-wheel job runs only the tests marked `wheel` (package data, the entry
point, the migrations the wheel carries); the whole suite already runs in
hub-sqlite.

**Reason:** the hub jobs took 60 to 90 minutes and every hub merge waits for
them. Most of a test's time was spent migrating and downgrading through every
revision, on every engine: on PostgreSQL a subset took 112 s with a downgrade
and a migration per test and 75 s with the schema kept. The wheel job's value is that the installed package works, not a
second run of the suite. No test was removed: every test still runs at least
once per engine.

**Rejected alternatives:**
- Run the whole suite again in hub-wheel — the same tests on the same engine
  for 60 to 87 minutes, to prove what a handful of tests prove.
- Parallel workers on one shared server database — the fixture downgrades
  the schema, so one worker would drop another's tables.
- A template database per engine (`CREATE DATABASE … TEMPLATE` on PostgreSQL)
  to skip migrating on the servers too — not tried: it differs per engine and
  could only be checked in CI; the parallel workers come first.

## A cleanup held by a leaked connection fails one test and ends the holder, instead of hanging

**Id:** 210f3def-e846-4f72-ad22-2ad911ec3bf2
**Type:** decision
**Type:** incident
**Status:** active
**Evidence:** inferred
**Source:** card tsk-xz3bxa5cwv4v; hub-postgresql run 41477804762 cancelled after hours at 99 %; review on #1256 (reproduction with `pg_stat_activity` and `pg_blocking_pids`); faulthandler stacks of the diagnosis run on #1255 (job 125615090292), 2026-11-03; `hub/tests/test_test_database.py`; review on #1264 (the first holder lookup ended any session with a table lock in the database), 2026-11-03; review on #1289 (a lock on an owned sequence alone was no longer found; the tables were looked up only in `current_schema()`), 2026-11-03
**Revisit when:** the test database stops being the suite's alone (hub/README.md), the per-worker databases go, or the cleanup stops using `TRUNCATE`
**See:** testing.md#the-suite-runs-in-parallel-one-database-per-worker-and-the-wheel-job-runs-a-marked-subset — 081792e2-758e-4202-84f7-c2957459665e — as of 2026-11-03

A test connection is closed by its test (`with engine.connect() as conn:`, or `close()` in a
`finally`). On PostgreSQL a connection left open stays *idle in transaction* and keeps its locks,
and the `TRUNCATE` that empties a worker's database before the next test waited for them without
end: the hub-postgresql job hung at 99 % until GitHub cancelled it (a test in `test_swarm.py`
passed `migrated.connect()` as an argument). `_empty_the_tables` therefore sets `lock_timeout`
(`TRUNCATE_LOCK_TIMEOUT`, 60 s) for the `TRUNCATE`; when it runs out, it names the sessions that
hold a lock on one of the tables it empties or on a sequence those tables own (`serial` or
identity, through `pg_depend`: `RESTART IDENTITY` locks them too, and a session that only drew a
number holds the `TRUNCATE` up; the tables resolved as the unqualified `TRUNCATE` resolves them,
quoted and through `search_path`, not only in `current_schema()`), with state and last statement from `pg_stat_activity`, ends them
with `pg_terminate_backend` and fails that one test with `LeakedConnection`. When it finds none,
the message says so instead of claiming an end, since the next cleanup may wait again (unless that
session ends first). Only client
sessions of the suite's own role in this database count; one that cannot be ended is named with
the reason, and the others are still ended. The next
test's cleanup goes through.

**Reason:** a hang shows nothing: no failing test, no message, only a cancelled job hours later.
Failing one test with the leaked statement in the message points at the test that leaked it.
Ending a holder is safe because the test database is the suite's alone (hub/README.md) and only
the sessions that hold the `TRUNCATE` up are ended: a lock on another table, a session of another
database or role, and the server's own background processes are left alone. A per-worker
database alone did not make it safe: without `-n` the configured database is used directly, and
the first lookup (any session with any table lock there) would have ended whatever else ran in it.

**Rejected alternatives:**
- Only a time limit on the CI job (`timeout-minutes`): a hang still costs the whole limit and
  ends without a stack or a failing test.
- `lock_timeout` alone, as first built on #1256: the cleanup no longer hangs, but the leaked
  connection stays, so every later test of that worker fails again after 60 s, and a worker with
  many tests left runs into the job's limit anyway; the error names neither the lock nor its
  holder.
- `idle_in_transaction_session_timeout` on the test engine: it would end a leaked connection
  without naming the test or failing it; whether a shorter timeout would also cut legitimate
  long transactions in tests was not examined.

Which reasons are confirmed and which inferred: the hang, its cause and the second alternative's
weakness are confirmed (reproduced in review, stacks from CI, counter-checks in
`test_test_database.py`); the weighing of the first and third alternatives is the author's
reasoning, not measured.

## `NOT_ROUTED` lists one entry per line, sorted, its reason on the line

**Id:** 3b8a32d7-5bde-4c3a-abcb-49bd22750c7f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-6jwjdwftq6cm (option 1, lotse's go, 2026-11-04); implementation session, 2026-11-04 (merge reproduction in scratch repositories)
**Revisit when:** `NOT_ROUTED` moves out of `hub/tests/test_contract_routes.py`, or the contract index is checked another way

`NOT_ROUTED` in `hub/tests/test_contract_routes.py` holds one `(method, path)` per line, sorted
by method and then path, each with its reason as a comment on the same line (the card that brings
the route, where there is one). An entry is added at its sorted place and removed with its line.
The set is the same as before the change; the test's behaviour is unchanged.

**Reason:** every card that adds a contract route without a route yet, or the route for one,
changes this set, and several run at once. With entries grouped under shared comments and new
ones added at the end, two such pull requests changed the same lines and conflicted: reproduced
by two branches each adding one entry to the old form (conflict) and the same two entries to
the new form (clean merge). Two pull requests still conflict when they change neighbouring
lines (reproduced as well); sorting only makes that rare.

**Rejected alternatives:**
- Keep the grouped form — every parallel entry conflicts at the end of the set.
- Move the entries to a data file next to the test — the same conflicts in another file, and the
  reasons leave the code that checks them.

## Pytest keeps a test's temporary directory only when the test failed

**Id:** a986378a-5387-4cc0-88ef-88e8b7cd1bb3
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-eyw44pwjx03d; CI run 41875042289, job hub-sqlite 126732121254, 2026-11-04
**Verification:** corroborated — that job's log, the measurement step after `make check`
**Revisit when:** the suite stops copying a database file into `tmp_path`, or pytest changes what `failed` retains
**See:** testing.md#the-suite-runs-in-parallel-one-database-per-worker-and-the-wheel-job-runs-a-marked-subset — 081792e2-758e-4202-84f7-c2957459665e — as of 2026-11-04

`hub/pyproject.toml` sets `tmp_path_retention_policy = "failed"` (pytest 9.1.1; the
option exists since pytest 7.3, whose default is `all`). A passing test's
`tmp_path` is removed, and a green session removes its basetemp. The directory
stays only when the test itself fails. A failure in fixture setup or teardown,
such as copying the template, loses it. `-o tmp_path_retention_policy=all`
keeps everything for local debugging.

A green `hub-sqlite` run on a GitHub-hosted runner left the copies in place.
Counting rule, from that job's own log after `make check`: `du -sh` of
`/tmp/pytest-of-runner`; `find` of `hub.db` under it, and the same find limited
to a `template` path; `ls -lh` of one template file; `df -h /tmp`. Job
126732121254 (run 41875042289, 4 xdist workers, 5732 passed and 107 skipped)
reported the directory at 6.4G, 4642 `hub.db` files of which 4 are the workers'
templates and the rest copies of that 1.4M file (`du -ch` of every `hub.db` was
6.3G). The runner disk was 145G with 81G free afterwards. The `hub-sqlite` job
still prints `du -sh /tmp/pytest-of-*` after the suite (the command tolerates
no match) so that size stays visible.

**Reason:** `failed` drops the passing tests' copies, about 6.4G on that run,
and keeps the directory only when the test itself fails. A failure in fixture
setup or teardown, such as copying the template, loses it. The earlier
`OSError: [Errno 122] Disk quota exceeded` while copying the template, and the
following `sqlite3.OperationalError: disk I/O error`, on pull requests #1324
(run 41819769733 attempt 1, job hub-sqlite 126539773241) and #1320
(run 41839052855 attempt 1, job hub-sqlite 126605831245) were not reproduced on this run.
The measurement does not show that those failures were this retention, and this
decision does not claim to fix them.

**Rejected alternative:** `tmp_path_retention_policy = "none"`. A red run then has no
directory left to debug from.

**Rejected alternative:** leave the default `all` and delete `/tmp/pytest-of-*`
from the workflow only. The copies still exist for the whole suite, which is
the disk the measurement found, and a local run keeps them too.

## `test_public_why` starts no public-pages worker: the renders it reads come from the app's start and from `touch`

**Id:** 2be5f10f-49f7-4dae-80c4-bf72205aa584
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-tb5a42f4r5dj, pull request #1453 (b2ec5b31) and its review; the fixture comment in `hub/tests/test_public_why.py` (`world`)
**Revisit when:** a test of that file needs the worker's own re-render, or `public_pages.configure` also reaches a running worker

The `world` fixture patches `public_pages.Worker.start` to a no-op. A worker
renders with the settings its app started with, and these tests change them
through `public_pages.configure` alone; a worker's start-up render, late on a
loaded runner, wrote the Why page back as the old settings showed it, and the
test read that page (flaky, reproduced in #1453).

**Reason:** what the tests check is the page as the current settings render it,
and that render comes from the app's start and from `touch`; the worker adds
only a second, late writer with stale settings.

**Rejected alternatives:**
- Updating `Worker.hub` after `configure`: a test-only path into the worker's
  state, and still a race with a render already under way.
- Waiting for the worker before reading: the late render can start after the wait.
- Marking the test `xfail`, or retrying it: both hide a real failure; the card
  ruled them out.

## GET answers are checked against hand-listed contract keys, each anchored to a line of docs/api.md

**Id:** 4e114a53-b5e1-417d-a29d-62af96440a74
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** jour fixe of 2026-11-08 (round jfx-x83wyff3vxm0, adopted by the maintainer as req-7y4mfywt9cmn); card tsk-x4c4v639trrv and its plan note, approved by the lead, 2026-11-08; `hub/tests/test_contract_shapes.py`
**Revisit when:** docs/api.md gives every answer's shape in one machine-readable form, or `PENDING` is empty and the hub gains response models

`hub/tests/test_contract_shapes.py` holds, per GET route, the top-level keys the contract
names for its answer, and an anchor: a line of docs/api.md after which, before the next
heading, each key must be named. A real answer from the test client on a fresh project must
carry every listed key. Every GET route under `/api/v1/` is in `SHAPES`, in `PENDING` (one per
line, sorted) or in `OUTSIDE` with its reason (`/openapi.json`); a new route in none of them, an
entry that is no route, and an entry in two fail. The routes come from the app's router, its
included routers and their prefixes walked, not from the OpenAPI document, so a route left
out of the schema (`include_in_schema=False`) counts too.
A key the contract names and the hub does not send yet goes into `KNOWN_GAPS` with the card
that adds it; the test fails once the hub sends it, so the entry leaves with that card.

Only missing keys fail. Keys the hub sends beyond the contract, nested shapes, types and
values are not checked. The anchor check runs one way: a listed key must be named in the
contract, but a key the contract names that the list leaves out is not found by the test; the
list is kept whole by hand, from the anchor's whole section (in #1499's review the project's
list first lacked `public_page` and `public_about`, which §6.1 names below its example).

**Reason:**
- `GET …/roles` answered `custom` only, while the contract promised `builtin` too, and no
  test noticed. A test per route that compares the keys catches that kind of gap.
- docs/api.md gives shapes as JSON examples, as braces in a sentence and as tables. A parser
  would have to guess which of these is the answer of which route. A hand-kept list with an
  anchor that must still be in the contract, and keys that must be named after it, fails when
  the contract drops or renames a listed key.
- `web/tools/hub-shapes.json` records the hub's own answers for the dashboard's fixtures. It
  says what the hub sends, not what the contract promises, so it cannot find this gap.

**Rejected alternatives:**
- Parsing the shapes out of docs/api.md: three forms, and no marker of which route an
  example belongs to.
- Comparing key sets for equality: the contract does not list every key the hub sends (the
  account deletion on `GET /me` is named in a table elsewhere), so equality would fail on
  documentation gaps of the other direction first; that direction is a later step.
- Fixing the roles gap in the same change: it is product work (descriptions, guides per
  §6.28, scopes) with its own card.

## The conftest resets every limiter it finds in the hub's modules, not a hand-kept list

**Id:** 4debb183-43cc-4ae5-8730-d2b4e8e03fc5
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-knmx8yw3s1xa (the flake on #1717 and #1723, CI run 43405647189) and its reproduction; implementation session, 2026-11-13; `process_limiters` in `hub/tests/conftest.py`
**Revisit when:** a limiter is held deeper than one attribute below a module, or the in-process limiters move into a registry of the hub's own

Between tests, `_fresh_process_state` resets every `Limiter` that a module
of `maity_hub` holds as an attribute, or one attribute further down (a
`RequestLimits` of three). On SQLite and MariaDB the limiters count in the
test process, and the suite comes from one source address and a few fixed
addresses: the hand-kept list had missed 24 of the 44, among them the
sign-in link's pair limit (3 per 15 minutes), so a fourth link for
`ada@example.com` on one worker was answered `202` with no mail, and a test
that waited for the mail failed now and then (reproduced in one process:
red on main, green with the reset).

**Reason:** a limiter added later is reset without anyone remembering a line
for it, which is the very gap that caused the flake; the search costs about
2 ms per test.

**Rejected alternatives:**
- Adding the missing limiters to the explicit list (the first plan for
  the card): fixes today's 24, and the next new limiter leaks again.
- A fresh limiter per test file, as `test_email_sign_in.py` swaps in: the
  leak is between files, so every file that reaches a limit would need it.
- A registry of every limiter in `ratelimit`: a change to the hub for the
  tests' sake, where a search from the tests finds the same set.

## A cost test counts only the statements of its own call, marked by a context variable

**Id:** 6063bcb5-a218-452d-9b8d-b7a9faeca1b0
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-dbnh1nhcjrc4 (main's hub-postgresql red with `(51, 53)` on 5abda036); approach agreed by the lead (lotse, seq 135104) and the review lead (a4xv, seq 135111); `hub/tests/statements.py`, `hub/tests/test_statements.py`
**Revisit when:** the app hands database work to a thread it starts itself (`threading.Thread`) and that work is part of a request's cost, or a test client stops running a request in the sending thread's context

The tests that say a call costs the same statements for more rows count with
`tests/statements.py`. Its listener hangs on the engines as before, but counts a
statement only while a context variable holds the marker the counting block set.
The test thread sets it; a test client's request runs in a copy of that context
(the portal's task), and so does every thread or task the request hands work to:
FastAPI's threadpool for a sync route, `run_in_threadpool`, `anyio.to_thread`,
`asyncio.create_task`, the async engine's greenlet. The app's background workers
run on threads started before the block, without the marker, so a tick of theirs
during the call is no longer counted. `test_notifications`, `test_requests` and
`test_view_batching` had copies that listened on the whole engine; they use the
helper now, on the sync engine only (`async_engines=False`), as before.
`test_statements` holds the rule: a call through a sync route and through both
thread hand-offs counts exactly, a worker thread sending during it counts nothing,
and an app request counts more than zero.

**Reason:** the background workers wake every 30 or 60 seconds and write their
claim rows (`worker_run`) and read; one landing in a measured call added two
statements to one of the two counts (reproduced by making the workers tick every
0.2 s: the tests failed every run, with the marker they pass). Counting what the
call itself sends keeps the test exact, so a statement per row the route adds still
fails it (checked with a read injected per 50 requests: 4 of 4 tests red).

**Rejected alternatives:**
- Stopping the workers in these tests: a fixture per test that must know every
  worker, and a new worker would bring the flake back.
- Counting by thread id: the request's statements run in the threadpool's
  threads, not the test's, so it counts nothing of the route (the self-test fails
  with it: on SQLite 2 counted instead of 8).
- Tolerating a few statements, or retrying: hides a real extra statement.
- Counting per connection (`conn.info`): a request may open several connections,
  from the pool, which a worker uses too; the connection does not say whose
  call it serves.

A thread started with `threading.Thread` begins with an empty context: a test that
starts its own threads in the call hands each `contextvars.copy_context().run`
(`test_load.held_statements`). The app starts such threads only for background
reads that are by design no request's cost (the maintenance frame).

## Every list route has a 3-versus-30 statement test, claimed by `@flat_rows` and found by a guard

**Id:** 8f5ec285-3aa8-452a-9321-2fe2fa9f8269
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-xdn21ph67js9 (item 15 of the list in `context/performance.md`, the lead's go of 2026-11-18: a statement-count test per list route, 3 rows against 30 in the style of `test_view_batching`, a guard that fails a list route without one, a route that grows becoming its own card); implementation session, 2026-11-20 (how the routes and the claims are found); the review of #2039 (2026-11-20: lists under a key other than `items`, an enrollment list measured with empty rows); `hub/tests/list_rows.py`, `hub/tests/test_list_rows.py`
**Revisit when:** the hub gains response models (a list could then be known from its type), or the `GROWING` list is empty and could become a hard rule with no exceptions
**See:** https://github.com/oliver-zehentleitner/maity — f81ab39d-1f35-40e2-bf25-aea0fa6fb102 — as of 2026-11-20
**See:** testing.md#get-answers-are-checked-against-hand-listed-contract-keys-each-anchored-to-a-line-of-docsapimd — 4e114a53-b5e1-417d-a29d-62af96440a74 — as of 2026-11-20

A test claims the list routes it measures with `@flat_rows("/path/{}")` (`tests/list_rows.py`).
The guard, `tests/test_list_rows.py`, reads those decorators from the source of every
`tests/test_*.py` and takes the GET routes under `/api/v1/` from the app's router, walked as
`test_contract_shapes` walks it. Every route is claimed by a test, or is in `NOT_LISTS` (no
list), `ITEMS_INSIDE` (its code names `items` in a part, with the reason) or `CATALOGS` (a list
from the hub's own code, no rows); a route in none, an entry that is no route, and an entry in
two fail. A list is a list of rows under any top-level key, not only `items` (`/me`'s
`projects`, the jour fixe's `series`): its test counts the rows under that key (`rows=`). Each
`NOT_LISTS` entry says what the route answers. To find a list put into `NOT_LISTS` by mistake,
the guard does two things. It looks for `"items"` in the route's function and in the hub
functions it calls, four calls deep by the names they call; a `NOT_LISTS` route that names it
fails. And it reads every `NOT_LISTS` route as a small project's owner and as its agent: an
answer with a list at the top under a key `LIST_KEYS` does not name for that route fails.
`LIST_KEYS` names the lists that are bounded by something other than a table's rows (a
catalog, one object's own parts, a setting). The new tests measure with `same_for_3_and_30`: one call
first (so a first read's one-time write is not row cost), then 3 rows and 27 more, the list
showing exactly 27 more rows, the statements on the sync engine the same both times. SQLite's
`PRAGMA query_only`, which `db.read_transaction` switches on a pooled connection whose last use
was a write, is not counted: which connection the pool hands out decides it, not the rows
(seen with a minute between the two counts). A seed must reach the code that runs per row:
an enrollment with an empty `attach` reads no project names, so that test attaches one. And
its first 3 rows must already hold every kind the 30 hold: a view reads each kind once, so a
kind that comes only with the 27 adds a statement that is no row cost. The overview's reports
picked their reporter (the owner or one of three agents) by a counter shared by the file's
tests, so whether the 3 held the human depended on the tests before it: it counted 11
against 12 on PostgreSQL in CI, and recording the statements on PostgreSQL showed the extra one
reading the reporting humans; a 13 against 14 on SQLite once under load was most likely the
same. The counter now starts
again in every test, and the reporters follow the test's own rows. The
older tests that already measured a list (`test_view_batching`, the requests, the bell, the
chat lists, the memory, the admin's users) only gained the decorator and keep their own
numbers (2 against 8 chats, 5 against 30 requests, 3 against 20 entries).

A route whose cost grows today is in `GROWING` with what it reads per row; its test asserts
that the cost grows, so the entry fails and leaves once the fix lands. 25 of the 59 list
routes grew when the guard came (2026-11-20; 21 first, on SQLite and PostgreSQL, four more
after the review, on SQLite), plus `…/jour-fixe/rounds` for two readers of an owner circle
(27 `GROWING` entries); each is to become a card of its own, and none was fixed in this
change. A route whose cost depends on who reads it is measured once per reader, each with a
`case`; a `GROWING` entry `<route> [<case>]` names only that reader, so the route's other
tests stay flat. The jour fixe's rounds are flat for a project-wide series and for an owner
circle read by its owner, and grow when the moderator or one of the owner's agents reads an
owner circle (`circle.reads`, review of #2039): a growing reader would otherwise have taken
the flat claim of the whole route along, or the flat reader its exception.

**Reason:** the card asks for the cost of every list to stay flat after the performance cards.
3 and 30 are the counts the 2026-11-08 measurement and `test_view_batching` used: 27 rows
apart, so a read per row shows as 27 statements more, and 30 fits one page of every list. A
claim on the test keeps the route and the test that measures it in one place, and a pull
request that adds a list and its test touches no shared table. The "names `items`" search
cannot prove that a route is no list (a deeper helper, a key built at run time), but it
catches the common case, a route whose own code builds `{"items": …}`; `ITEMS_INSIDE` keeps
its false hits explicit. The read of every `NOT_LISTS` route catches a list under another
key, which no search of the source finds (`{"series": shown}`), but only for the routes the
owner or the agent of a small project can read with 200; a route that needs more set up (an id
of its own) is checked by its entry's reason alone. A `GROWING` test that asserts the growth keeps the exception honest
in both directions.

**Rejected alternatives:**
- A central map from route to test name in the guard: it goes stale when a test is renamed,
  and parallel pull requests adding lists would all change it.
- Calling every GET route at run time to decide which is a list: 136 routes, many with ids
  to set up first; a route the read cannot reach would be classified by nothing. The read is
  kept as a second check on `NOT_LISTS`, where an entry already says what the route is.
- Reading the lists from docs/api.md: the same three forms of shape and no marker of route,
  as in 4e114a53.
- Fixing the growing routes here: the card keeps this change to tests and CI; each fix is its
  own card.
- A tolerance of a few statements: hides a real read per row, as in 6063bcb5.

## A test with fixed dates pins the hub clock the code under test reads

**Id:** 571c40ee-8ef0-45b0-bd4a-413a5da59261
**Type:** constraint
**Type:** incident
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-1z1h4rwyz0qf, pull request #2126 (main red on 2026-11-23) and its review A2173; card tsk-2s1bwwsvqy9h; `_test_clock` in `hub/tests/test_backfill_public_merges.py`, `_fresh` in `hub/tests/test_swarm.py`
**Revisit when:** `swarm.window` or `swarm._Cache.get` stops reading `clock.now()`, or the conftest stops resetting the clock after each test

A test that writes fixed times (a module `NOW`, a calendar string) and asserts on anything cut
by a window, an expiry or a retention against `clock.now()` pins `clock.set_source` to the same
`NOW` in its own module, as an autouse fixture. Importing another test module's helpers does not
bring that module's autouse fixture along: `test_backfill_public_merges` imported `public_prs`
and `ticker_merge` from `test_swarm` but not its `_fresh`, which pins the clock, and so ran on
the wall clock. Its ticker items are dated `NOW` − 1 day (2026-10-24), and the swarm window is
cut by UTC day at `clock.now()`'s day − 29 (`swarm._window_days`), so they left it on
2026-11-23, 29 days after `NOW`, and main turned red for every pull request. The conftest resets
the clock after each test (`clock.reset()` in `_fresh_process_state`), so the pin needs no
teardown. A module that needs only another module's clock pin repeats the one-line fixture
rather than importing that module's fixture, since `test_swarm`'s `_fresh` also clears
`swarm.CACHE` and resets `listening`.

**Reason:** a pin on `maity_hub.clock` moves every time read through `clock.now()` together: on
this test's path the swarm window (`swarm.window`) and the swarm cache's age and day
(`_Cache.get`), so the test gives the same answer on every future date. It does not move the
times the hub reads elsewhere, among others the database's `now()` (for example `listening`,
`shared_budget`), a module's own `datetime.now(UTC)` (`listening`, `shared_counts`), the epoch
from `time.time()` (`forge`, `attachments`) and monotonic clocks (`ktw`, `images`,
`contract_text`, `ratelimit`). A dated test that asserts on one of those freezes that module's
own clock instead, as `test_mentions` does with `shared_counts._now` and `ratelimit.time`.

**Rejected alternatives:**
- Making only the stored dates relative (`merged_at` from `NOW`, the card's first proposal): the
  window reads the event's own `at` against the clock, never `merged_at`; with that change alone
  the test still failed (`assert None == 1`).

## Background workers in test clients: `test_outside_reads` starts no probe and no public-pages worker

**Id:** 8b631cbc-3da6-481f-973c-f0e93d3a2ff4
**Type:** decision
**Type:** incident
**Status:** active
**Evidence:** inferred
**Source:** card tsk-9j767pr11k1a (the flake in hub CI on #2129 and locally under `-n 4`, and its reproduction with a sweep delayed by a test plugin); implementation session, 2026-11-23 (the same reproduction on the whole file, and a second worker found by a run with the probe already off); `probe.Worker._run`, `probe.observe_visibility`, `public_pages.Worker._run`, `public_project_views.prepare_why`; the `make_client` fixture in `hub/tests/test_outside_reads.py`
**Revisit when:** a test of that file needs either worker's own pass, another worker that starts with the app reaches the forge within a test's time, or either worker stops working at once on start
**See:** testing.md#a-cost-test-counts-only-the-statements-of-its-own-call-marked-by-a-context-variable — 6063bcb5-a218-452d-9b8d-b7a9faeca1b0 — as of 2026-11-23
**See:** testing.md#test_public_why-starts-no-public-pages-worker-the-renders-it-reads-come-from-the-apps-start-and-from-touch — 2be5f10f-49f7-4dae-80c4-bf72205aa584 — as of 2026-11-23

Every test client starts the app's background workers in its lifespan. They
run on threads of their own, beside the test, and can call a test's fakes
while the test measures them. The probe worker sweeps at once on start: it
asks the forge whether each public page's repository is public
(`observe_visibility`, through `Forge.for_project`) and stores the answer as
`repository_public`. In `test_outside_reads` that sweep went through the
`WhyForge` fake and added an `asked`, a `"repos"` event and a `bound`
project; landing after a test had taken its counts, it failed
`test_the_why_is_not_found_to_an_outsider_where_the_instance_token_does_not_serve`
with `assert (2, 4) == (1, 4)`. The public-pages worker does the same on
start: `prepare_why` reads the Why of every served project for its pages
through a `ktw.Cache` that binds (`Forge.for_project`), which in this fake adds
a `bound` project, file reads and the owner's grant; with the probe already
off, it failed `test_an_outsiders_why_reads_never_ask_the_projects_source`
(`assert ['prj-…'] == []`) and the test above (`assert (0, 4) == (0, 0)`, four
file reads). A fake that counts calls must leave the workers' calls out, or the
test must keep the workers from running; this file keeps them from running:
its `make_client` patches `probe.Worker.start` and `public_pages.Worker.start`
to no-ops for every client, as `test_probe`, `test_forge_access`,
`test_contract_text` do for the probe and `test_public_why` (2be5f10f) for the
public pages.

Which part stands how: both races are reproduced. With the probe's sweep
delayed 0.1 s and 0.2 s by a test plugin, the whole file fails with that first
assert; with the probe off and the sweep delayed 0.5 s, the public-pages
worker failed the bound check once; with its preparation delayed 1 s, the
four-file-reads assert fails both cases of that test. With both workers off
the file passes under each delay. That a late sweep would also turn the stored
visibility false after a test sets `why.private` is read from
`observe_visibility`, not seen in a run. That no third worker reaches the forge
within a test's time is read from the code too (the image worker waits its
600 s interval before its first sweep, the notification mailer is off in the
conftest).

**Reason:** the probe's sweep does more than count. It writes the fake's
answer into the project row, which the outsider's gate reads, so a sweep after
`why.private = True` could refuse an outsider by the stored value where the test
means the live answer. Not starting the workers removes every such effect, and
no test in the file needs their passes: the tests read the forge through
requests and set `repository_public` themselves (`_repository`), and the
public pages they read are rendered at the app's start and by `touch`.
6063bcb5 rejected stopping the workers for the cost tests, since there every
worker's statements counted and a new worker would bring the flake back; here
only the workers that reach the forge fake matter, and two do within a test's
time.

**Rejected alternatives:**
- The fake leaving calls from the `maity-probe` thread out of `asked`, `events`
  and `bound`, or recording them apart (the card's proposal): it would have
  missed the public-pages worker, a second thread that reaches the fake, and the
  sweep would still store the fake's answer as `repository_public`.
- Stopping `app.state.probe` in every client a test measures (the card's
  alternative): the first sweep starts as the client enters its lifespan, before
  a test can stop it, so a sweep already under way still lands; and every client
  of the file (the world's and a test's own) would need the stop.
