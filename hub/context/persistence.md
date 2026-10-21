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
