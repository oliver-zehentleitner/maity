### Fixed

- hub tests: `test_two_workers_are_two_processes_of_one_hub` no longer fails at random on PostgreSQL. The
  fixture also waits for both workers' `hub_pod` rows: the lifespan starts the listener before it writes
  the row, so on a loaded runner both LISTENs could be seen while one row was still missing.
