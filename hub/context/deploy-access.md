# Access in the shipped deploy files

## PostgreSQL: an owner role for the migrations and a row-only role for the hub, the superuser kept for admin work

**Id:** 1e997665-e9a1-4476-9ef8-55b554cf404b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** deploy hardening card tsk-xesvyydh2yd3 (item 1), from the security rounds of card tsk-v9kheekgq115; `deploy/postgres-roles.sql`, `deploy/postgres-init-roles.sh`, `deploy/docker-compose.yml`, `deploy/k3s-single/`, the chart's `database.migrate`, docs/install/README.md "Database roles"
**Revisit when:** the hub needs a right on PostgreSQL beyond rows (a runtime DDL, an extension, `TRUNCATE`), MariaDB gets the same split, or the hub's tables move out of the schema `public`

The shipped setups create two roles besides the superuser `maity`: `maity_owner` owns the database and
every object in `public` and is the role `maity-hub migrate` logs in with (`NOSUPERUSER`, no `CREATEDB`,
no `CREATEROLE`); `maity_app` is the running hub's and has `SELECT`, `INSERT`, `UPDATE`, `DELETE` on the
tables and use of the sequences, granted for the future by `ALTER DEFAULT PRIVILEGES FOR ROLE maity_owner`.
`CONNECT` is taken from `PUBLIC`. The superuser stays for restores and admin work; the k3s backup Job
dumps as `maity_owner` with the URL from the Secret `maity-hub-db-migrate` (optional: without it, as
before, as the superuser), since the owner reads everything in the hub's schema. One SQL file
does both a new install and the move of an existing one (it hands the superuser's objects to the owner)
and can run again; the passwords reach `psql` as variables on standard input, and are needed only for a
role it creates: without them it keeps the existing passwords. It runs again after every restore
(`-v after_restore=1`, which does nothing where the roles were never set up): a dump from before the two
roles brings its objects back owned by the superuser and without `maity_app`'s rights, and the second run
hands them back and grants the rows again; the k3s restore block runs it after `pg_restore`. The chart takes the
migrate Job's URL from `database.migrate.existingSecret`, falling back to the hub's Secret so an existing
release renders as before.

**Reason:** least privilege: the process that serves requests gets only the rights it uses, and the
schema changes only through the migrations. The hub writes rows and never DDL at run time (checked: no `CREATE`, `ALTER`, `TRUNCATE` or
`LOCK TABLE` outside the migrations), so rows are all it needs. The migrations need to own what they
change, which is not the superuser either. A test on PostgreSQL ran both paths (a new database with the
roles first, then `migrate` as the owner; a database migrated by the superuser, then the script, twice)
and the hub served `/api/v1/health` as `maity_app`.

**Rejected alternatives:**
- One role that is not the superuser for both the hub and the migrations: the running hub could still
  change the schema.
- Granting `maity_app` its rights after each migration instead of default privileges: every upgrade would
  need a step after the migrate Job, and a forgotten one breaks the hub on the new table.
- `REASSIGN OWNED BY maity` for an existing install: `maity` is the bootstrap superuser of the official
  image, and PostgreSQL refuses to reassign objects the system needs; the script alters the hub's objects
  in `public` one by one.
- Passwords as `psql -v` arguments: they would be on a command line in the pod.
- The script only before a restore ("the objects come back owned by `maity_owner`"): true only for a dump
  that already names `maity_owner`; one from before the split restores to the superuser, and the hub's
  role then cannot read a table (found in review on PostgreSQL 16, reproduced by
  `deploy/scripts/test-postgres-roles.sh`).
- Requiring the passwords on every run: the run after a restore would then reset them, or need them at
  hand where the restore runs.

## The hub refuses to serve on a PostgreSQL role that can change the schema, unless an opt-out is set

**Id:** 1adefb2c-abf6-4f9c-a41e-8f29ee2c0c08
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** review of the deploy roles pull request (follow-up card tsk-4eyae1smgdj5), refusing with an opt-out preferred by the team lead, 2026-11-14; `hub/src/maity_hub/app.py` (`privileged_role`, `require_unprivileged_role`), `hub/src/maity_hub/cli.py`, `hub/tests/test_db_role.py`, `deploy/helm/kind-smoke.sh`
**See:** deploy-access.md#postgresql-an-owner-role-for-the-migrations-and-a-row-only-role-for-the-hub-the-superuser-kept-for-admin-work — 1e997665-e9a1-4476-9ef8-55b554cf404b — as of 2026-11-14
**Revisit when:** the hub needs a right beyond rows at run time, MariaDB gets the same role split, or a managed PostgreSQL makes a row-only role impossible

`maity-hub serve` asks PostgreSQL once at the start, after the schema check and before it serves (in the
one process, or in the parent of several workers) about `current_user` and every role it is a member of
(`pg_has_role(current_user, role, 'MEMBER')`: a member without `INHERIT` can still `SET ROLE` to it):
is one of them a superuser, the owner of a schema of the hub or of any table, view, sequence or foreign
table in it, or may one create in such a schema (`has_schema_privilege(role, schema, 'CREATE')`)? The
hub's schemas are those holding an `alembic_version` table, plus the current schema: the current schema
alone would let a `search_path` that points elsewhere, or is empty, hide the schema the hub writes to. A
database where neither exists is refused, since nothing could be checked. In any of these cases the
start fails with the reason and the two ways out: a role that only reads and writes rows, or
`MAITY_DB_ALLOW_PRIVILEGED=1`, which turns the refusal into a warning at each start. `maity-hub migrate`
does not ask, since it runs as the owner. The app factory does not ask either: the check belongs to the
command that starts a real hub, and the test suite builds apps on its superuser. SQLite has no roles;
MariaDB has no owners, only grants, and the shipped setups split roles on PostgreSQL only, so neither is
checked. The CI smoke test on a kind cluster runs the chart with the two roles from
`deploy/postgres-roles.sql`, so the row-only role serves there.

**Reason:** the two roles hold only when the hub's URL names the row-only role; a URL left on the
superuser, or the owner's URL copied into the hub's Secret, would silently give the serving process every
right again. Refusing makes that visible at the first start instead of never. The opt-out keeps an
installation that has not moved yet running after the upgrade, as a decision written into its
environment.

**Rejected alternatives:**
- A warning only: it is read rarely, and the hub would run with every right without anyone deciding so.
- No check: the split depends on two Secrets that are easy to swap, and nothing would notice.
- Membership with `USAGE`: it counts only roles that inherit the owner's rights, while a member with
  `INHERIT FALSE` and `SET TRUE` can switch to the owner and change the schema just the same.
- Checking only `current_schema()`: it follows the `search_path`, which the role's settings or the URL
  can point at another schema or leave empty, while the hub's tables stay where the migrations put them.
- Checking in the app factory as well: the test suite and tools that build the app directly would all
  need the opt-out; the serving command is the one way a hub starts.
- An equivalent check on MariaDB (the `SUPER` privilege or `CREATE`/`DROP`/`ALTER` grants): the shipped
  setups do not split roles there, so every MariaDB installation would need the opt-out.

## Egress policies: none for PostgreSQL, and DNS, the database, HTTPS and SMTP for the hub, opt-in in the chart

**Id:** b878e725-32af-40dd-a8f6-17df5b0ee159
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** deploy hardening card tsk-xesvyydh2yd3 (item 2); `deploy/k3s-single/postgres-netpol.yaml`, `deploy/helm/maity-hub/templates/networkpolicy.yaml`, `deploy/k3s-single/hub-values.yaml`
**Revisit when:** the hub opens a connection on another port (a plain-HTTP outbound read, a metrics or trace exporter, a webhook to a configured port), or the chart moves to a CNI-specific policy kind with domain rules

On k3s, PostgreSQL's pod gets a NetworkPolicy with `policyTypes: [Egress]` and no rule: it may open no
connection. The chart gets a second NetworkPolicy for the hub's pods, `networkPolicy.egress`, off by
default: DNS to kube-dns (UDP and TCP 53), the database on its port (peers configurable, any address when
none are set), TCP 443 to any address, the SMTP port of `mail` (587 and 465 when no host is set, since
the admin settings may name the server), and `extra` rules as given. The k3s values turn it on with the
PostgreSQL pod as the database peer. The migrate Job and the test pod are not selected.

**Reason:** least privilege on the network: the hub needs only these four kinds of outbound connection,
and PostgreSQL none, so nothing else is open. HTTPS stays open to any address: the forge, Keep the Why reads, S3 stores and images are
on hosts the hub learns at run time, which a NetworkPolicy cannot name.

**Rejected alternatives:**
- The hub's egress policy on by default in the chart: an existing release on a managed database, a
  plain-HTTP MinIO or another DNS service would lose its connections on the next upgrade.
- Egress rules inside the existing ingress policy: one object for two directions makes it harder to turn
  either off, and the ingress policy stays as releases have it.
- HTTPS only to public address ranges: the S3 store and the forge may sit on a private network, and
  `ipBlock` behaviour for pod addresses differs between CNIs.
