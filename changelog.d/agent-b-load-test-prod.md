### Changed

- Load test: the seed is `maity-hub loadtest seed`, run where the hub runs on its own database;
  accounts are `lt-<n>` without a mail address or password. A hub is seeded or reached only when
  `LOADTEST_CONFIRMED_TEST_SYSTEM` names it, or for a host under `maity.team`
  `LOADTEST_CONFIRMED_PRODUCTION`, then through its one public address; `run.js` stops at start
  when no human waits. `hub/loadtest/seed.py` is gone.
