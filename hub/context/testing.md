# Testing

## Test matrix: full check on SQLite, the suite again on PostgreSQL 17 and MariaDB 11.4

**Id:** c7d0850a-a677-4f0f-a209-e64da3b0fe8f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's brief for the hub skeleton, 2026-10-21 (SQLite, PostgreSQL and MariaDB in CI); implementation session, 2026-10-21 (job split, versions, shared-database fixture)
**Revisit when:** a user reports a difference between MySQL and MariaDB, or a query relies on behaviour the two engines implement differently
**See:** https://github.com/oliver-zehentleitner/maity — 3dacd29b-bd09-4757-80bb-7f3cfbd9af91 — as of 2026-10-21

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
**See:** testing.md#test-matrix-full-check-on-sqlite-the-suite-again-on-postgresql-17-and-mariadb-114 — c7d0850a-a677-4f0f-a209-e64da3b0fe8f — as of 2026-10-28

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
