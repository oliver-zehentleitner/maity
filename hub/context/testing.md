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
database empty. The
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
