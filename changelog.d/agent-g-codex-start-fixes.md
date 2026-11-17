### Fixed

- runner: an interactive Codex placement no longer stops at its start on
  Codex's folder prompt for the untrusted clone. The runner answers
  "Open restricted", which keeps the clone untrusted, and never a prompt
  that would trust the folder; that one is named in the log, and no idle
  line or key is sent while a folder prompt shows.
- runner: every command of a supervised Codex run failed where a path the
  runner hides lay inside another hidden path (the runner's configuration
  in the layout `single`, another clone's credential under the workspaces
  root). A path another hidden path already covers is no longer listed
  again; every hidden path stays hidden and every deny on other clones'
  credentials is kept, the runner's home secrets now compared under the
  home resolved. A start whose other clones cannot be checked is refused.
