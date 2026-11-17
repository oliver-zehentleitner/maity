### Fixed

- runner: an interactive Codex placement no longer stops at its start on
  Codex's folder prompt for the untrusted clone. The runner answers
  "Open restricted", which keeps the clone untrusted, and never a prompt
  that would trust the folder; that one is named in the log.
- runner: every command of a supervised Codex run failed where a path the
  runner hides lay inside another hidden path (the runner's configuration
  in the layout `single`, another clone's credential under the workspaces
  root). A path inside a hidden one is no longer listed again.
