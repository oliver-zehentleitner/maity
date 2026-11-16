### Fixed

- hub tests: `test_the_guard_refuses_every_socket_but_the_test_databases` empties the pool before its database connection,
  so that on MariaDB the connection opens a new socket and the guard's pass-through is really exercised; before, a pooled
  connection could satisfy it with the pass-through removed.
