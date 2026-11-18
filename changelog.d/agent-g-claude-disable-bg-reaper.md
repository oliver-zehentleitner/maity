### Fixed

- cli: the runner sets `CLAUDE_CODE_DISABLE_BG_SHELL_PRESSURE_REAP=1` in the
  start environment of every Claude Code placement, so Claude Code's
  background-shell memory-pressure reaper no longer kills the placement's
  background `maity wait` under low memory and leaves the session running but
  no longer listening.
