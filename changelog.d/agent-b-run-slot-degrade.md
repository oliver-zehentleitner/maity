### Fixed

- tools: `tools/run_slot.sh` no longer fails when it cannot write the slot directory or a slot
  file in it, as in a sandboxed agent session: it warns once on stderr and runs the command
  without a slot and without a log line, as it does without flock. `MAITY_RUN_SLOTS_DIR` can
  point it to a directory the run may write. `make smoke SLOT=` is now only for a machine where
  nothing else runs tests (tsk-deaaanqsq5e2).
