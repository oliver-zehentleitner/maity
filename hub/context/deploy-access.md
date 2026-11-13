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
`CONNECT` is taken from `PUBLIC`. The superuser stays for dumps, restores and admin work. One SQL file
does both a new install and the move of an existing one (it hands the superuser's objects to the owner)
and can run again; the passwords reach `psql` as variables on standard input. The chart takes the
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
