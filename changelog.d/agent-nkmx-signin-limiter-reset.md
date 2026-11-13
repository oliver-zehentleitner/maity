### Fixed

- Hub tests: a test that waits for the sign-in link's mail no longer fails
  now and then on SQLite. The sign-in link's and the password reset's
  limits, and 18 other in-process limiters, kept their counts from one test
  to the next; the conftest now resets every limiter it finds in the hub's
  modules between tests.
