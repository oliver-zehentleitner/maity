### Changed

- ci: the hub jobs run the suite in parallel (pytest-xdist, one worker per core,
  one database per worker on PostgreSQL and MariaDB), the hub-wheel job runs only
  the tests marked `wheel` against the installed package, and SQLite tests copy a
  schema migrated once instead of replaying every revision. No test was removed.
