### Changed

- ci: `hub-postgresql` prints every thread's stack into the log when a test runs longer than 300 s
  (`faulthandler_timeout`), so a hang shows the frame and line it waits on (the test's, or a fixture's in setup
  or teardown) instead of ending as a silent cancel after 90 minutes; the test itself runs on.
