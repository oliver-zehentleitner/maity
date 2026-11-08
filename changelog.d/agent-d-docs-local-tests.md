### Changed

- CONTRIBUTING.md, hub/README.md, cli/README.md: the local test environment in one place: the hub on
  SQLite and on a local PostgreSQL (`scripts/with_postgres.sh`, `pgserver`), the CLI's tests with
  neither a database nor a hub, on a shared machine at most two workers and heavy runs in a slot,
  and the rule for the machine the project's agents share, written down with its date and reason:
  only the affected test files, never the full hub suite (tsk-qahs7p84evrt).
