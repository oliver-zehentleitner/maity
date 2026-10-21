# Testing

## Test matrix: full check on SQLite, the suite again on PostgreSQL 17 and MariaDB 11.4

**Id:** c7d0850a-a677-4f0f-a209-e64da3b0fe8f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's brief for the hub skeleton, 2026-10-21 (SQLite, PostgreSQL and MariaDB in CI); implementation session, 2026-10-21 (job split, versions, shared-database fixture)
**See:** https://github.com/oliver-zehentleitner/maity — 3dacd29b-bd09-4757-80bb-7f3cfbd9af91 — as of 2026-10-21
**Revisit when:** a user reports a difference between MySQL and MariaDB, or a query relies on behaviour the two engines implement differently

CI has three jobs: `make check` (black, ruff, mypy strict, pytest) on
SQLite, and pytest alone against a PostgreSQL 17 and a MariaDB 11.4
service container. The suite picks the database from
`MAITY_TEST_DATABASE_URL`; without it every test gets its own SQLite
file. On a server database the fixture downgrades to the empty schema
before and after each test instead of creating a database per test.

**Reason:** lint and types do not depend on the database, so they run
once; the tests are what differs per engine. PostgreSQL 17 is the
production engine. MariaDB stands in for the MySQL family: the
migrations use only `op.*` operations and the queries only portable
Core, where the two engines behave alike, and MariaDB is the one most
self-hosters on the MySQL side run. Downgrading to the empty schema
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
