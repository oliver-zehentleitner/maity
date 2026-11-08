### Added

- `tools/coverage.sh <pr>`: before a MERGE-READY, checks that the `main` a pull request's green `ci-ok` run
  tested contains every `main` commit on the pull request's files since the merge base, and names those it
  lacks. Exit 0, 1 or 2 like `tools/overlap.sh`; it only reads.
