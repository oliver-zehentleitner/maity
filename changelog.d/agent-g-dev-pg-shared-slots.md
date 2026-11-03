### Added

- `tools/run_slot.sh` runs a command in one of the account's run slots: at most two (`MAITY_RUN_SLOTS`)
  at a time, a further one waits and says who holds them. In a slot, `pytest -n auto` starts two workers.
- hub: `scripts/with_postgres.sh --start` starts the shared PostgreSQL and leaves it up, `--stop`
  stops it once no run uses it, also not under a command whose wrapper was killed; it never starts
  or creates a server. `CONTRIBUTING.md` has the rules for PostgreSQL runs on a shared machine.

### Changed

- hub: a `scripts/with_postgres.sh` run holds a run slot, and its database is
  `maity_test_<name>_<pid>`, with `<name>` from `MAITY_RUN_NAME` (else the user name).
- web: `make smoke` runs in a run slot; `make smoke SLOT=` runs it without one.
