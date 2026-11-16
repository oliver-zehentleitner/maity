### Fixed

- hub tests: `test_listening_shows_while_a_long_poll_is_open` and
  `test_the_long_poll_wakes_on_an_attachment_and_shows_listening` wait, with a deadline, until the long poll they opened
  shows as `listening` instead of reading once after a fixed half second; under load the route registers the wait
  later than that, after its own database round trips, and the single read failed.
