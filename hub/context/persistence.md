# Persistence

## SQLAlchemy Core with Table definitions, no ORM mapping

**Id:** 33ff333e-4985-42ea-88b7-d510a00f6166
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's brief for the hub skeleton, 2026-10-21; implementation session, 2026-10-21
**See:** ../../context/architecture.md#database-agnostic-persistence-postgresql-in-production-sqlite-and-mysqlmariadb-supported — 3dacd29b-bd09-4757-80bb-7f3cfbd9af91 — as of 2026-10-21
**Revisit when:** a part of the hub grows object graphs with identity and lazy relationships that Core queries make hard to read

The hub describes its tables with SQLAlchemy Core `Table` objects on one
`MetaData` (`maity_hub.db.metadata`) and talks to the database with Core
statements. There are no mapped classes, sessions or unit of work.

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
