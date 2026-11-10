### Fixed

- hub tests: `test_it_is_computed_once_an_hour` no longer depends on the time of day. It runs
  at 23:30 UTC, so the hour later always crosses into the next day, and it counts the card on
  the day it was made.
