### Fixed

- cli: runner: a Codex placement's restart no longer reaches the app-server daemon of its
  first start, whose TMPDIR was gone, so every sandboxed command failed: every Codex start
  stops the daemon left in the placement's codex-home first (`codex app-server daemon stop`,
  else by its CODEX_HOME on the runner's own host); a stop that fails is logged and the start
  goes on (tsk-n6sajs3gyh8h).
