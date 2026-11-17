### Added

- tools: `tools/run_slot.sh` appends a start line (time, slot, pid, seconds waited, who, the
  program and its first argument) and, once its process is gone, an end line (time, seconds held)
  per run to `log` in the run-slot directory, tab-separated; set `MAITY_RUN_NAME` to
  `handle#instance` so the log says who ran it. Once a run is over, a start line without an end
  line means the run was aborted. A log that is not a regular file, or cannot be written, never
  holds up or stops a run.
