# Persistence

## SQLAlchemy Core with Table definitions, no ORM mapping

**Id:** 33ff333e-4985-42ea-88b7-d510a00f6166
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's brief for the hub skeleton, 2026-10-21; implementation session, 2026-10-21
**Revisit when:** a part of the hub grows object graphs with identity and lazy relationships that Core queries make hard to read
**See:** https://github.com/oliver-zehentleitner/maity — 3dacd29b-bd09-4757-80bb-7f3cfbd9af91 — as of 2026-10-21

The hub describes its tables with SQLAlchemy Core `Table` objects on one
`MetaData` (`maity_hub.db.metadata`) and talks to the database with Core
statements. There are no mapped classes, sessions or unit of work. Core
without the ORM was set by the coordinator's brief; the reason and the
rejected alternative below are the implementation session's reading of
why it fits the hub.

**Reason:** the hub's writes are small and deliberate — an atomic claim is
one conditional `UPDATE … WHERE claimed_by IS NULL` whose row count
decides the outcome, an event is one `INSERT` into an append-only table.
Core writes exactly that statement on every engine. An ORM's identity map
and flush order would sit between the code and the statement that carries
the guarantee, and make the generated SQL harder to check against the
contract. The `Table` metadata is still what Alembic compares against, so
autogenerate keeps working.

**Rejected alternative:** the SQLAlchemy ORM (declarative models,
`Session`). It would give convenient objects for the API layer, but the
hub's correctness lives in single statements whose effect must be the
same on PostgreSQL, SQLite and MySQL/MariaDB, and the ORM adds a layer
that decides when and how those statements run.

## Migrations run only on `maity-hub migrate`; `serve` refuses an outdated schema

**Id:** ce7a3627-d04d-4708-bac9-ed0c7d64cfe4
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's brief for the hub skeleton, 2026-10-21 (explicit `migrate`, never implicit); implementation session, 2026-10-21 (refusal at startup, the one-shot Compose service, portability rules)

Schema changes are Alembic revisions shipped inside the package
(`maity_hub/migrations`, no `alembic.ini`), applied only by `maity-hub
migrate`. `maity-hub serve` compares the database's revision with the
head and exits with a message naming `maity-hub migrate` when they
differ; `/api/v1/health` answers 503 in the same case. Docker Compose
runs a one-shot `migrate` service the hub waits for. Revisions are written
to run and downgrade on all three engines; the rules for that are in
`hub/README.md` ("Migrations"). That migrations are explicit came from the
coordinator's brief; refusing to serve, the Compose service and shipping
the migrations in the package were decided in the implementation session.

**Reason:** a migration is a change to the production database and
should happen when the operator decides, not as a side effect of a
restart — with several replicas on Kubernetes, migrating at startup would
also race. Refusing to serve instead of serving on an old schema is the
loud failure: a hub that starts on the wrong schema fails later, on some
request, with an error that no longer points at the cause. Shipping the
migrations in the package makes `maity-hub migrate` work from a wheel or
the image without a checkout.

**Rejected alternatives:**
- Migrate automatically when `serve` starts — the usual convenience for
  small self-hosted tools. Rejected for the race between replicas and
  because an upgrade would change the database without anyone asking.
- Start anyway and only warn on an outdated schema — keeps a hub up
  during a forgotten migration, but serves requests against tables that
  may not match the code.
- `alembic.ini` and `migrations/` beside the package, run with the
  `alembic` command — the Alembic default, but it needs the source tree at
  run time and a second tool in the operator's hands.

## "At most one" as a True-or-NULL column under a unique constraint, not a partial index

**Id:** 6f948103-e687-411e-a17f-22e7c6a5f1b8
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-21 (the data model for the V1 contract)
**Revisit when:** MySQL/MariaDB support is dropped, or one of these rules needs a condition a single marker column cannot express

Two rules of the contract are "at most one row of a kind": one live
session per credential, and one release card in flight per project. Each
is a nullable boolean — `agent_session.live`, `card.release_in_flight` —
set to true on the one row the rule is about and to NULL on every other,
under a unique constraint with its scope (`credential_id, live`;
`project_id, release_in_flight`). Ending a session or closing a release
sets the marker back to NULL in the same statement.

**Reason:** all three engines allow any number of NULLs in a unique
constraint and refuse a second true, so the database enforces the rule
under concurrent writers on every engine, with the constraint named and
visible in the schema.

**Rejected alternatives:**
- A partial unique index (`WHERE ended_at IS NULL`) — the textbook
  form on PostgreSQL and SQLite, but MySQL and MariaDB have no partial
  indexes.
- Checking in the application before the insert — races between two
  requests, exactly the case the rule exists for.
- A pointer column on the parent (`credential.session_id`) — enforces
  "one" too, but makes the session and credential tables reference each
  other, a circular foreign key that complicates every migration and
  insert order.

## Value sets are checked by the API; the schema constrains only invariants

**Id:** 7322ba9d-27f6-4642-83f4-12a1139012f2
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-21 (the data model for the V1 contract)

States, statuses, kinds, roles, classes and priorities are plain
`VARCHAR` columns; the API layer validates their values. The database
carries constraints only for the invariants the server relies on: keys,
foreign keys, uniqueness (handles, versions, the at-most-one markers), a
membership naming exactly one principal, a join naming an agent, no
self-edge between cards.

**Reason:** `docs/api.md` lets `v1` gain values without notice. With the
value sets in the schema, every added value would be a migration on three
engines, and on SQLite a table rebuild, for a check the API performs
anyway before it writes.

**Rejected alternatives:**
- A `CHECK (status IN (...))` per enumerated column — keeps a direct
  database write honest, at the price of a migration for every new value;
  nothing but the hub writes to this database.
- Native enum types (`CREATE TYPE` on PostgreSQL, `ENUM` on MySQL) — not
  portable, and changing them is the hardest migration of all.

## Ids: a readable prefix and 60 random bits, generated by the hub

**Id:** ef9e39c5-82a9-4ea6-ad10-72f8cf639f32
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-21 (the data model for the V1 contract)

Every id the API shows is a prefix naming the kind (`hum`, `agt`, `prj`,
`crd`, `ses`, `tsk`, `rel`, `ctr`, `req`, `join`) and twelve random
Crockford base32 characters: `tsk-7k2m9q4xw1bd`. Ids are unique across
the instance and the primary key of their table; memberships and events
use integer keys inside the database, because the API addresses them
through the principal's id and the sequence number.

**Reason:** the contract makes ids opaque and hub-chosen, and a reader
of a log or a message benefits from seeing what kind of thing an id
names. Random ids need no counter and no lock, and do not leak how many
cards or requests a project has.

**Rejected alternatives:**
- Numbers per project (`tsk-0004`, as in the contract's examples) —
  friendlier in conversation, but they need a counter row locked on every
  insert, and the same id would exist in two projects, so the key would
  have to include the project everywhere.
- UUIDs — no prefix, and 36 characters in every message and log line for
  uniqueness this volume does not need.

## Nested values as JSON columns; tables only where the server queries or constrains

**Id:** c0e833f1-b49c-48e8-94ad-3bc436ba1cf0
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-21 (the data model for the V1 contract)
**Revisit when:** reading events for a member gets slow enough to matter, or a JSON value has to be queried or constrained by the database

Values the API returns as nested objects and the server reads and writes
whole — a membership's areas and capabilities, a card's checkpoint,
report, contract and release data, a request's options and answer, an
event's audience and payload, project settings — are SQLAlchemy `JSON`
columns. Relations the server queries or constrains are columns and
tables: claim holder, assignee, addressee and asker as membership
foreign keys, card edges as rows, the release version and the
conversation id as plain columns with their own indexes.

**Reason:** the nested values follow the contract's shapes, which grow
within `v1`; as JSON they grow without a migration, and `JSON` maps to a
native type on all three engines. The audience of an event is filtered
in Python after the read by project and sequence number: one project
produces a few thousand events a week, and the long-poll reads only what
is newer than the cursor.

**Rejected alternative:** normalising every list — an `event_audience`
table, `membership_area`, `request_option`. It would let the database
filter audiences and areas, at the cost of a join on every read and a
multi-row write for every event, for a volume where the scan is cheap.
