### Added

- tools: `tools/run_slot.sh` appends a start line (time, slot, pid, seconds waited, who, command)
  and an end line (time, seconds held) per run to `log` in the run-slot directory, tab-separated;
  set `MAITY_RUN_NAME` to `handle#instance` so the log says who ran it. A log that cannot be
  written never stops a run.
