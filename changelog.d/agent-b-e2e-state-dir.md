### Fixed

- The browser test no longer passes the caller's `MAITY_*` settings to any process it starts: one
  `maity wait` inherited `MAITY_STATE_DIR` and took over a real agent's wait.
