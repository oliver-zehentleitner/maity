### Fixed

- ci: a pull request that changes only `docs/api.md` now runs the two contract tests (`hub-contract`, on SQLite, in `ci-ok`) instead of getting a green `ci-ok` without them and turning main red after the merge.
