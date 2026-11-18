### Added

- deploy: `deploy/postgres-roles.sql` sets up two PostgreSQL roles besides the superuser: `maity_owner`, which owns the
  hub's schema and runs the migrations, and `maity_app`, the hub's, which only reads and writes rows (default
  privileges cover the tables later migrations create). Compose runs it on a new volume's first start
  (`deploy/postgres-init-roles.sh`), the k3s walkthrough in step 5 (docs/install/README.md, "Database roles").
- deploy: the chart's `database.migrate.existingSecret` (and `.key`) gives the migrate Job its own database URL;
  empty, it uses the hub's Secret as before.
- deploy: the chart's `networkPolicy.egress` (off by default) limits the hub's outbound connections to DNS, the
  database, HTTPS and SMTP, plus `extra` rules; the k3s values turn it on. `postgres-netpol.yaml` adds a policy that
  lets the PostgreSQL pod open no connection.

### Changed

- deploy: `deploy/docker-compose.yml` runs `migrate` as `maity_owner` and the hub as `maity_app`, and needs
  `MAITY_DB_OWNER_PASSWORD` and `MAITY_DB_APP_PASSWORD` in `deploy/.env`. Upgrade note: an existing Compose or k3s
  installation moves to the two roles before its next start with the new files, in the order in
  docs/install/README.md, "Moving an existing installation to the two roles": back up, run
  `deploy/postgres-roles.sql` against the running database, then switch the URLs (k3s: the Secret
  `maity-hub-db-migrate`, the app's URL in `maity-hub-db`, `postgres-netpol.yaml` again, then `helm-upgrade.sh` with the
  new `hub-values.yaml`). Compose refuses to start without the two new passwords.
- deploy: `deploy/postgres-roles.sql` needs passwords only for a role it creates and otherwise keeps them; it runs again
  after every restore (`-v after_restore=1`, a no-op where the roles were never set up), also handing large objects to
  `maity_owner`, since a dump from before the two
  roles restores its objects to the superuser without `maity_app`'s rights. The k3s restore block and the Compose
  restore in docs/install/README.md run it after `pg_restore`; `deploy/scripts/test-postgres-roles.sh` covers it on
  PostgreSQL.
- deploy: the k3s backup Job runs `pg_dump` as `maity_owner` when the Secret `maity-hub-db-migrate` exists, and as the
  superuser otherwise. The password from that Secret's URL reaches `pg_dump` through `PGPASSWORD`, never its arguments; a
  user or password holding `%`, `/`, `?`, `#` or `@`, or a query naming a password or password file, fails the Job
  (`deploy/scripts/test-backup-dump.sh`).
- hub: `maity-hub serve` on PostgreSQL refuses to start when its database role is a superuser, owns the hub's schema
  or one of its tables, or may create objects in that schema, each also through any role it is a member of (the hub's
  schema being the one with `alembic_version`, wherever the `search_path` points); `maity-hub migrate` is not checked.
  `MAITY_DB_ALLOW_PRIVILEGED=1` lets such a role serve, with a warning at each start. Upgrade note: an installation whose hub still uses the
  superuser or the owner's URL (Helm with one `database.existingSecret`, your own setup) sets
  `MAITY_DB_ALLOW_PRIVILEGED=1` for the hub (Helm: `extraEnv`) before it upgrades, or moves to the two roles first
  (docs/install/README.md, "Database roles"); otherwise the new hub does not start. SQLite and MariaDB are not checked.
