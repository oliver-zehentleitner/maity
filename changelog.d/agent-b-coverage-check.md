### Added

- `tools/coverage.sh <pr>`: before a MERGE-READY, checks that the `main` a pull request's green `ci-ok` run
  tested contains every `main` commit (merges included) that changes one of the pull request's files, and
  names those it lacks. Exit 0, 1 or 2 like `tools/overlap.sh`; it only reads.
