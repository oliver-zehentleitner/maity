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
