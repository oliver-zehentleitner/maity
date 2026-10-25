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

Three rules of the contract are "at most one row of a kind": one live
session per credential, one release card in flight per project, and one
active membership per principal and project (a removed membership keeps
its row, §6.2, and the principal may join again). Each is a nullable
boolean — `agent_session.live`, `card.release_in_flight`,
`membership.active` — set to true on the one row the rule is about and
to NULL on every other, under a unique constraint with its scope
(`credential_id, live`; `project_id, release_in_flight`;
`project_id, agent_id, active` and `project_id, human_id, active`), and a
CHECK that the marker is never false, since false would be a second value
the constraint lets through. Ending a session, closing a release or
removing a member sets the marker back to NULL in the same statement.

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

**Reason:** `docs/api.md` §1.6 lets `v1` gain fields without notice; that
values may be added the same way is this entry's own reading. With the
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
columns, with `none_as_null`: an absent value is SQL NULL, never the
JSON literal `null`, so that `IS NULL` finds it. Relations the server
queries or constrains are columns and
tables: claim holder, assignee, addressee and asker as membership
foreign keys, card edges as rows, the release version and the
conversation id as plain columns with their own indexes.

**Reason:** the nested values follow the contract's shapes, which grow
within `v1`; as JSON they grow without a migration. The type is JSONB on
PostgreSQL, native JSON on MySQL, a validated `LONGTEXT` on MariaDB and
text on SQLite. The audience of an event is filtered in Python after the
read by project and sequence number: one project is expected to produce a
few thousand events a week, and the long-poll reads only what is newer
than the cursor.

**Rejected alternative:** normalising every list — an `event_audience`
table, `membership_area`, `request_option`. It would let the database
filter audiences and areas, at the cost of a join on every read and a
multi-row write for every event, for a volume where the scan is cheap.

## Timestamps: aware UTC in Python, naive UTC with microseconds in the database

**Id:** f6041871-9416-4565-b3dc-c5af45c4528b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-21 (the data model for the V1 contract)

Every timestamp column is `maity_hub.types.UtcDateTime`: it refuses a
naive `datetime`, converts an aware one to UTC and stores it without a
zone, and returns it with `tzinfo=UTC`. On MySQL/MariaDB the column is
`DATETIME(6)`.

**Reason:** the hub's time is the only clock in the system
(`docs/api.md` §1.2), so one zone everywhere is enough, and refusing naive
values keeps a local time from slipping in. MySQL's `DATETIME` drops
fractions by default, which would make lease ends, `updated_at` ordering
and the server time's milliseconds engine-dependent.

**Rejected alternative:** `DateTime(timezone=True)` — `timestamptz` on
PostgreSQL, but MySQL has no zone-aware type and SQLite stores text, so
the three engines would hand back different kinds of values.

## On MySQL and MariaDB every table is utf8mb4 with the binary collation

**Id:** ae5662be-59b8-4f99-a4cc-665ce4aedc6a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** review of the data model, 2026-10-21 (the finding: case- and accent-insensitive uniques on MariaDB); implementation session, 2026-10-21 (table-wide instead of per column; the MariaDB dialect's own option prefix)

Every table carries `utf8mb4` and `utf8mb4_bin` as its charset and
collation on the MySQL family (`maity_hub.types.MYSQL_TABLE`, with both the
`mysql_` and the `mariadb_` option prefix, since SQLAlchemy's MariaDB
dialect reads only its own). Text then compares and is unique byte for
byte, as on PostgreSQL and SQLite.

**Reason:** without it a table inherits the server's defaults: `latin1`
on many installations, and on MariaDB 11.4 the accent- and
case-insensitive `utf8mb4_uca1400_ai_ci`. A release version `0.1.0-rc1`
would then collide with `0.1.0-RC1`, and an idempotency key with its
upper-case twin, on one engine and not on the others. Handles and slugs
are lower case by validation, so nothing the hub sorts for people loses
by a binary order.

**Rejected alternative:** a binary collation only on the columns where
uniqueness must be exact (release version, idempotency key, observed
ref), as the review proposed. It is narrower, but every future unique
text column would have to remember the variant, and one forgotten column
would bring the inconsistency back.

## File SQLite runs in WAL mode with a five-second busy timeout

**Id:** 0d122efc-ffd8-4c2e-9115-9ea8ce24579e
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** review of the hub skeleton, 2026-10-21 (the suggestion, deferred to the first write path); implementation session, 2026-10-21 (applied with the authentication slice)
**Revisit when:** a SQLite hub is reported to fail with "database is locked", or SQLite is used on a network file system

Every SQLite connection to a file sets `journal_mode=WAL` and
`busy_timeout=5000`; an in-memory database keeps its own journal mode.

**Reason:** from the authentication slice on, every authenticated call
writes (presence, leases), so readers and writers overlap constantly.
In the default rollback journal a reader blocks the writer and a second
writer fails at once with "database is locked"; with WAL readers and the
one writer proceed side by side, and the timeout turns a collision
between writers into a short wait instead of a 500.

**Rejected alternative:** the default journal with retries in the
application — more code in every write path for what SQLite offers as
one pragma.

## Concurrent writes touch rows in one order, and a deadlock is run again a few times

**Id:** 308ec265-2ca6-463a-9006-6d149c5b0b79
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-21 (the join slice; a CI failure on MariaDB, reproduced locally under load)
**Revisit when:** a transient conflict still reaches a client as 503, or a second replica changes how often they happen

Writes that run beside every authenticated call touch the agent's rows in
the order the authentication side effects use: credential, membership,
session, cards — the resume packet was reordered to match. Each whole
transaction of authentication, resume, the join exchange and the
idempotent writes runs through `maity_hub.db.retrying`: on a deadlock or
serialisation failure (SQLSTATE `40001`, `40P01`, MySQL `1213`, `1205`) it
is run again, at most four times, with a short randomised backoff.

**Reason:** InnoDB answers a lock cycle between two transactions with a
deadlock and rolls one back; under twelve concurrent resumes of one
credential about 60 % failed with `40001` on MariaDB, while PostgreSQL had
none. The reordering removes the cycle between authentication and resume
(zero failures afterwards); the retry covers the cycles nobody has found
yet, since InnoDB's next-key locks make them hard to rule out by reading.
The error handler logs the driver's code (never its text) so that the
next one is identifiable.

**Rejected alternatives:**
- Retries alone — reduced the failures to about 3 % under the same load,
  but left the cause in place.
- Locking the project row at the start of every authenticated call —
  removes every cycle, but serialises all calls of a project, reads
  included.

## READ COMMITTED on every server engine

**Id:** 87b08f1e-c12c-48a6-adaf-f7bd93d5c32b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-21 (the cards slice; concurrent claims failed on MariaDB only); review of the cards slice, 2026-10-21 (SQLite, decisions under the lock)
**Revisit when:** a write path needs a consistent snapshot across several reads, or a second replica brings stricter isolation into question

The engine opens PostgreSQL and MySQL/MariaDB connections at isolation
level `READ COMMITTED`. SQLite has one writer; every SQLite transaction
starts with `BEGIN IMMEDIATE` and so holds the write lock before its first
read, which is what `lock_project` gives the server engines. A MySQL
server with `binlog_format=STATEMENT` refuses writes at `READ COMMITTED`;
`ROW` (the default) and `MIXED` are fine.

**Reason:** the hub's writers serialise on the project row
(`events.lock_project`) and then read the rows they change. On
PostgreSQL, whose default is `READ COMMITTED`, those reads see what the
writer before them committed. InnoDB's default `REPEATABLE READ` keeps the
snapshot of a transaction's first read instead. Six concurrent claims of
one card then answered 500 on MariaDB: the losers waited for the lock, read
the card as still unclaimed, and the conditional update matched no row.
One isolation level on every engine makes the same code mean the same
thing everywhere.

Decisions that depend on the project (state, policy, lease length) are
taken from the row `lock_project` returns, read under the lock, never from
a read before it.

**Rejected alternatives:**
- Locking reads (`SELECT … FOR UPDATE`) on every row a writer reads after
  the project lock — correct on InnoDB too, but every future read would
  have to remember it, and one forgotten read would bring the stale
  snapshot back.
- pysqlite's own transaction start for SQLite — it sends `BEGIN` only at
  the first write, so the reads before it ran unlocked: two crossing
  `depends_on` changes stored a cycle, and a claim racing a cancel
  answered 500.

## `maity-hub quickstart` migrates only a new, empty SQLite database

**Id:** 83d063d3-b56c-46fe-b6b4-20751f9a6b0f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's approval of the quickstart command proposal, 2026-10-25 (empty database only, SQLite only, the address as the last line); docs/install/quickstart.md
**Revisit when:** quickstart is asked to upgrade an existing personal hub, or to run on a server database

`maity-hub quickstart` is `migrate`, `owner create` and `serve` in one, for
a personal hub. It runs `migrate` only on a database with no tables at
all. Having no schema version is not enough: a file that holds tables but
no version is refused and left as it is, because only `migrate` may decide
what to do with it. A database behind the current schema is refused with
the same message as `serve`. The first account is created only while there
is no human. The check and the insert are one statement, so an account that
another process creates while the password is being typed stops
quickstart instead of producing a second admin. Any database URL other
than SQLite is refused. This narrows ce7a3627, the rule that migrations run only on
`maity-hub migrate`. It does not replace it: an upgrade of a hub that
holds data is still a deliberate `maity-hub migrate`.

**Reason:** the five-minute path should be one command, and ce7a3627's
reasons do not hold for a database that is still empty. Nothing in it can
be changed without anyone asking, and one local process cannot race a
replica. Restricting it to SQLite keeps the shortcut off the servers
where ce7a3627 matters.

**Rejected alternatives:**
- Migrate whatever schema it finds: a restart after `pipx upgrade` would
  change a hub with data on its own, which is what ce7a3627 rules out.
- No single command, only the three steps: correct, but three more steps
  where the quickstart promises five minutes.

## SQLite migrations run with foreign keys off, then check them, then switch them back on

**Id:** 84988fb8-49b5-4b1d-8783-c90a8676deed
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-22 (migration 0003, the briefing columns)
**See:** persistence.md — ce7a3627-d04d-4708-bac9-ed0c7d64cfe4 — as of 2026-10-22
**Revisit when:** SQLite support is dropped, or Alembic's batch mode alters columns in place on SQLite

On SQLite, `migrations/env.py` sets `PRAGMA foreign_keys=OFF` on the driver
connection before the migration transaction begins. After the revisions
have run, it checks `PRAGMA foreign_key_check` and fails the migration on
any dangling reference. In a `finally` it switches the pragma back on, so
the pooled connection goes back to the hub as it came. The other engines
are untouched.

**Reason:** SQLite cannot drop or change most columns in place. Alembic's
batch mode rebuilds the table (copy, drop, rename), and with foreign keys
on the drop of a referenced table fails: `membership` and `credential` are
referenced from half the schema, and the first `drop_column` on one of
them (0003's downgrade) failed. The pragma has no effect inside a
transaction, hence the driver connection before the begin. The check
afterwards keeps the guarantee foreign keys give, for the moment they are
off.

**Rejected alternatives:**
- Writing downgrades without `drop_column` on referenced tables: every
  later migration would have to work around SQLite, and the rule that
  every revision downgrades would bend for one engine.
- Native `ALTER TABLE … DROP COLUMN` (SQLite 3.35+): Alembic's SQLite
  dialect still goes through batch mode for it, and columns with
  constraints cannot be dropped natively anyway.

## The board's card order is sorted in Python, not by the database

**Id:** 4e61c371-33b4-4ae4-8bb1-cb8fa974acb3
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation of card order (`docs/api.md` §6.4, contract #135), 2026-10-23
**Revisit when:** a project's board grows to thousands of cards, or a client reports paging through a board that does not finish while cards keep moving

`GET …/tasks` reads a project's cards that match the filters and sorts them
in Python by `ranks.board_key`: the columns in board order, then within
one by rank, then by `created_at`, then by `id`, and closed cards by
`closed_at` newest first, then by `id`. A page's cursor names the last
card it showed and the first card it did not show, each with its sort
key, and the ids the page showed in the last card's column; it is bound
to the list's filters and order. The next page goes on after the last
card shown where it still sits in its column. When that card has left
the column, it goes on from the first card not shown, but only if that
card's key is unchanged (it has not moved); otherwise it starts the
column again from the top without the cards the page showed. Following
a key, or a card that moved, can lose cards that never moved: a move
ranks the cards before its target, so their keys change kind, and a
card that moved elsewhere takes the page with it (both found in
review). A restart may repeat a card from an earlier page, but never
skips one that did not move.
When that card moves itself, the cards it passed may be skipped or
repeated; the contract says so. Nothing bounds the repeats: while cards
keep moving, a client can page on with restarts and repeats and has no
guarantee of reaching the end until the moves stop. A board of a few
hundred cards read 200 at a time rarely meets that, so no snapshot or
version token was added for it.
`order=updated` keeps the old keyset paging by `updated_at`, now bound to
the filters as well. A rank is a string over digits and lower-case letters
that never ends in `0`. A move keys between its ranked neighbours, a
fractional index, and spreads the column out to short keys when one would
grow past 24 characters, or when the column's ranks are not strictly
increasing: every empty column starts at the same key, and a rank travels
with a status change. A move changes neither `updated_at` nor the
history: it is layout, not an edit.

**Reason:** the contract compares ranks bytewise and orders across states
with keys of different kinds. PostgreSQL compares text by its locale, so
SQL would need a collation per engine and a `CASE` per state on all three
engines. Python compares the ASCII ranks bytewise everywhere, and a
board is a few hundred cards; the board asks for 200 at a time.

**Rejected alternatives:**
- Keyset paging in SQL with `COLLATE "C"` on PostgreSQL and a `CASE` for
  the closed columns. It is exact for very large boards, but the order
  logic would be spread over three dialects and the cursor would carry
  the whole sort tuple.
- Paging by position (the next item's index). Every move, creation or
  status change before the cursor shifts the list, so cards were skipped
  and repeated between pages (found in review).
- A keyset on the sort key alone. A move ranks the unranked cards before
  its target on the way, so their keys change kind (unranked keys sort
  after ranked ones) while their order stays: a cursor holding such a key
  sorts after the whole column and the next page loses it. A spread
  rewrites every key the same way. The order of the cards that did not
  move is what lasts, so the cursor follows the last card shown.
- Integer positions renumbered on every move. They are simple to compare,
  but a move rewrites every card after it, and each of those is an event.


## Admin-set instance settings in one table with a registry in code, admin-set secrets sealed in a table of their own

**Id:** e689f915-bca1-41c1-97d5-bdc125cbd9b3
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the hub owner's ruling on the mail and sign-in settings (`maity say`, card tsk-bjmkt2akq5dn), 2026-10-23; docs/api.md §2.6.6, §16.2; the implementation in PR #255, 2026-10-23
**Revisit when:** a section needs a setting per project or per human, or a second kind of admin-set secret appears

`instance_setting(name, value, updated_at, updated_by)` holds what the
instance admin set, one row per name (`mail.host`, `sign_in.device_code`);
no row means the environment's value or the default. Every name has an
entry in the registry of `maity_hub.instance_settings`, which its section
fills with a validator and a default; a write checks against it, and a
stored row without an entry (left over after a downgrade or a rename) is
ignored and logged, never served. Whether the environment wins is
decided in one place, `instance_settings.effective`. A secret the admin
may set (today only the SMTP password, §16.2) is never a setting: it has
its own registry and lives sealed with `maity_hub.secretbox` in
`instance_secret`, so nothing that reads settings can serve it: no
route or view returns the sealed value or the plaintext, and only the
mail sender opens it, in memory, per send. The signing key and the
instance key stay environment-only. A sealed value the current
`MAITY_SECRET_KEY` cannot open (the key changed or is missing) is loud:
logged at startup and `smtp_password_unreadable` in the admin view,
counted as not set, never replaced by another source silently. The
re-key path is to set the password again (or remove it) after the key
changed. A downgrade past the migration drops the tables, and the admin
sets the values again.

**Reason:** the hub owner wanted one table with a fixed registry rather
than one per section, so a new section needs no migration and every
name is checked in one place. The admin-set SMTP password is allowed by
the contract and the maintainer's decision. Its own table keeps "no
secret in the settings" a property of the schema rather than of each
reader.

**Rejected alternatives:**
- One table per section (`mail_setting`, `sign_in_setting`): the same
  shape twice, a migration for every section.
- The sealed password as one more row of `instance_setting`: a reader
  of settings could serve it by mistake.
- The SMTP password from the environment or a file only: contradicts
  §16.2, which lets the admin of a single local install set it.
