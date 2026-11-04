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
the message says so instead of claiming an end, since the next cleanup will wait again. Only client
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
