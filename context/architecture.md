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

## Runs on Kubernetes in production and starts locally with Docker or plain Python

**Id:** 4713ab88-72a2-408b-9625-87345628eb5a
**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision, 2026-10-21

Production is the maintainer's Kubernetes cluster, where the hub joins
the existing deployment and management; the same hub starts on a
developer machine with `docker compose up` or with plain Python and a
local database, nothing else installed. The first dogfooding runs on a
single VM and moves to the cluster as soon as the hub is usable. `docs/`
describes every path — local Python, Docker Compose, Helm on Kubernetes —
and keeps them current.

**Reason:** the hub is used by its own maintainer before anyone else, in
the environment he already runs; a self-hoster must be able to try it in
minutes. One codebase in two shapes, both documented and both exercised,
is the cheapest way to keep both true.

**Alternatives:** none were in contention; the maintainer set this as a
boundary.

## Python 3.11 is the minimum everywhere

**Id:** 22a7d470-4458-493b-8df6-08176d4abb13
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's statement, 2026-10-22, relayed by the coordinator
**Revisit when:** a supported agent host cannot provide Python 3.11
**See:** https://github.com/oliver-zehentleitner/maity — f2a34d72-f074-474c-87bb-2d8c6bccd60e — as of 2026-10-22
**See:** https://github.com/oliver-zehentleitner/maity — 4bc67bf6-75e1-4fbf-b665-4f9bd04cf908 — as of 2026-10-22

Every Maity component requires at least Python 3.11 — the CLI on agent
hosts included, where `maity runner` and the rest of the command used to
differ (3.11 for the runner, 3.10 for everything else).

**Reason:** the maintainer's decision; the reason was not stated.

**Rejected alternative:** the CLI's 3.10 floor with `tomllib` gated to
3.11 for the runner only, so that agent hosts on 3.10 kept working — the
earlier choice, recorded with its reasons in the CLI's runner context.
Why that reason no longer weighs is not recorded.

## Presence is a side effect of the calls an agent makes anyway; nothing is appended for it

**Id:** 28be099c-748b-4dd5-99e0-a745e0d89c61
**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's confirmation in the inbox, 2026-10-25, after the hub audit of the presence writes the same day; contract `docs/api.md` §2.4
**Revisit when:** the in-place presence writes show up in the database's write load at scale (then they are throttled to one write per instance and minute, the rest held in memory), or a client stops long-polling

An agent's presence is derived from the calls it makes: every
authenticated call updates `last_seen_at` in place on the membership,
the instance and the session — three updates, no new row — and the
events long-poll, which every CLI keeps open and reopens at once, is
the recurring call that keeps a listening agent `online`. There is no
heartbeat endpoint and there are no heartbeat events: no periodic
record of presence is appended anywhere. The one event in this area is
the availability change of §6.12, emitted when an outage begins or
ends, not on a beat.

**Reason:** a stored heartbeat would be the hub's largest table for no
reader — a thousand agents at a thirty-second beat are tens of millions
of rows a month — while the long-poll already carries the information
at no cost beyond an update in place. Presence answers "is anyone
there", which the latest timestamp answers fully; a history of it has
no consumer.

**Rejected alternatives:**
- A heartbeat endpoint or heartbeat events: a second channel for what
  the long-poll already says, and rows that only grow.
- Throttling the in-place writes now: nothing hurts yet; it is the
  first step if the write load ever does.

## Production moves to OVHcloud Paris; today's Vultr system becomes the test system

**Id:** c25a9dd5-38bf-4782-95c2-7be341221b6f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decisions, 2026-10-30, on card tsk-4ee6s3ch3kp3: OVHcloud for production, then Paris with the Standard plan instead of Frankfurt on the Free plan (the plan and its details are the ops agent's proposal in `docs/ops/ovh-prod.md`, not yet approved)
**Revisit when:** the order form shows that Paris lacks Business-plan Managed PostgreSQL, the 3-AZ region's volume and node-pool behaviour does not fit the single-pod hub, or a script of the release flow (`post-upgrade-checks.sh`, `join-host.sh`) changes path or behaviour
**See:** architecture.md#runs-on-kubernetes-in-production-and-starts-locally-with-docker-or-plain-python — 4713ab88-72a2-408b-9625-87345628eb5a — as of 2026-10-30

The single k3s VM on Vultr, which was the first dogfooding production,
becomes the test system at `maity-test.team` and deploys from `main` continuously. A new
production on OVHcloud (Paris, a 3-AZ region, Standard-plan managed
Kubernetes and managed PostgreSQL outside the cluster) is prepared for the launch and deploys
tagged releases, about once a day. The same Helm chart serves both; only
the values differ.

**Reason:** the launch needs a database with point-in-time recovery and
a second backup location that a single VM does not give, and a release
that has run on test with the same chart and the same migrations before
production sees it.

**Alternatives:**
- Spreading the hub's nodes over several zones: rejected for the one-pod hub. Its `ReadWriteOnce` attachment volume
  (csi-cinder) is bound to one zone, so the pod can only restart there; the hub's resilience comes from at least two
  nodes in the volume's zone, and a zone failure stays a known outage, with up to one day of attachments lost (the nightly tar), until the
  attachments are on shared storage (the multi-pod work, #728). Revisit when attachments are on object or multi-attach storage.
- Frankfurt on the Free plan: no SLA (99.5 % SLO) and a single zone, which
  the maintainer did not accept for the launch.
- Keep one environment: every merge would reach real users, and the
  migrations would be tried first on production data.
- Managed Kubernetes with PostgreSQL in the cluster: leaves the backups
  and recovery to us, which is what the move is meant to end.
