### Fixed

- cli: the CLI test suite runs in a runner-placed session. Its fixtures no longer inherit the
  session's `GIT_COMMON_DIR`/`GIT_CONFIG_*`, which aimed their git at the agent's own clone.
