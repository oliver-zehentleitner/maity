# Architecture

## Database-agnostic persistence: PostgreSQL in production, SQLite and MySQL/MariaDB supported

**Id:** 3dacd29b-bd09-4757-80bb-7f3cfbd9af91
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision on the design synthesis, 2026-10-21
**Revisit when:** a feature needs a database-specific capability (LISTEN/NOTIFY, JSON indexing) that cannot stay behind the abstraction

The hub stores its state through a database abstraction (SQLAlchemy Core
with Alembic migrations, or an equivalent that keeps the SQL portable) and
is tested against PostgreSQL, SQLite and MySQL/MariaDB. PostgreSQL is the
production database; SQLite is for local runs and tests. Anything that
needs a notifier — the long-poll wake for agents — runs in-process and
never relies on a database-specific mechanism.

**Reason:** the hub will run next to the maintainer's existing
infrastructure (PostgreSQL on Kubernetes) and must also start on a laptop
with plain Python or Docker without a second service. Supporting the three
common engines keeps self-hosters free in their choice, which matters for
a tool whose point is independence from any platform.

**Rejected alternative:** stdlib `sqlite3` with hand-written SQL and
numbered migration files, no ORM — the design synthesis recommended it
(one process, tiny write volume, one file to back up). Rejected by the
maintainer because production sits on PostgreSQL and the hub should not
dictate the database. Cost accepted: three engines in CI, and atomic
claims written as portable conditional updates (`UPDATE … WHERE claimed_by
IS NULL`) rather than engine-specific locking.
