### Changed

- ci: `hub-postgresql` may run 120 minutes instead of 90; its green runs had reached 88 of the 90. It also prints its 50
  slowest test phases (`--durations=50`: setup, call and teardown each count on their own).
