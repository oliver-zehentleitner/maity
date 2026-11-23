### Fixed

- hub: the outsider-read tests (`tests/test_outside_reads.py`) start no probe and no
  public-pages worker, so their start-up passes no longer reach the fake forge or write
  `repository_public` while a test counts its calls or sets the stored visibility (a flaky
  `(2, 4) == (1, 4)` in hub CI).
