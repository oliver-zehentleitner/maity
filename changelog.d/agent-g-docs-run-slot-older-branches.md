### Changed

- CONTRIBUTING.md: a branch cut before the run slots (#1302) has no `tools/run_slot.sh`, and its `make smoke` and `with_postgres.sh` take no slot; the guide now says to run `main`'s copy of the script on such a branch, and to merge `main` only where that is allowed anyway (tsk-rmrqkv6d2zdy).
