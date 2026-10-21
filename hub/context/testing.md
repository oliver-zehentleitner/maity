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
before and after each test instead of creating a database per test.

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
