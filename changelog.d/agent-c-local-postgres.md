### Added

- hub: `scripts/with_postgres.sh` runs a command against a local PostgreSQL in a database of its own, and stops only a server it started. `hub/README.md` documents it and the test venv.

### Changed

- hub tests: `test_the_installed_entry_point_answers` is skipped with a clear message when `maity-hub` is not on the path; in CI it still fails.
