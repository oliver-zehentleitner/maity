### Fixed

- hub tests: `test_listening_shows_while_a_long_poll_is_open` waits, with a deadline, until the long poll it opened shows
  as `listening` instead of reading the member view once after a fixed half second; under load the route registers the
  wait later than that, after its own database round trips, and the single read failed.
