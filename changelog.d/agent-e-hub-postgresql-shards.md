### Changed

- ci: `hub-postgresql` runs in three shards side by side, each the test files whose path hashes to it and each with its own PostgreSQL (`MAITY_TEST_SHARD=k/n` in `hub/tests/conftest.py`); the checks are now named `hub-postgresql (1)` to `(3)`, and ci-ok still takes the result over all of them.
