### Changed

- CONTRIBUTING.md, hub/README.md, cli/README.md: the local test environment in one place: the hub on
  SQLite and on a local PostgreSQL (`scripts/with_postgres.sh`, `pgserver`), the CLI's tests with
  neither a database nor a hub, and on a shared machine at most two workers, only the affected
  test files and heavy runs in a slot (tsk-qahs7p84evrt).
