### Fixed

- cli tests: copying a test repository's `.git` no longer races git's background maintenance
  (`test_confinement` turns off `maintenance.auto` and `gc.auto` before its commit, and both
  copies skip `*.lock`).
