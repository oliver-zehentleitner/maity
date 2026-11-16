### Fixed

- CLI: the runner's `sandbox_unavailable` report and its version
  warning describe the tool a session started with, even when a tool
  update or rollback lands while it starts.
- CLI: a runner-managed tool binary that leads out of its version
  directory through a link is neither installed nor started.
