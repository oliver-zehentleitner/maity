### Fixed

- hub tests: `test_simultaneous_reads_are_single_flight_and_release_their_threads`
  counts only requests to a path of its own, starts its 30 readers behind a barrier
  and gives the upstream read a wide margin over the waiters, so a slow runner or a
  read left by another test no longer fails it.
