### Added

- cli: the runner can build a dev venv per placement from the project's own pinned,
  hash-locked requirements (`[backend.local] dev_requirements`, a path inside the clone)
  and put its `bin` ahead of the session's PATH, so an agent runs the project's checks
  (pytest, ruff, black, mypy) with the versions the project pins. Built once outside the
  clone and reused; a changed lock rebuilds it. Without the setting no venv is built.

### Changed

- cli: the `antigravity` (agy) harness now works in both interactive and supervised modes.
  Interactive starts with `agentMode: accept-edits`, so the agent edits the clone without a
  prompt. The agy session's file tools may read and write anywhere in the clone, so a headless
  run never blocks on its own edit and agy's terminal sandbox can write the clone — `.git`
  included — so `git fetch` and `git commit` work; the credential (`.git/maity`) and what
  makes git run a program stay denied.

### Fixed

- cli: a supervised agy turn no longer sits idle when it leaves a background task behind. agy
  has no setting to stop a background task outliving a turn, so the runner ends any such task
  the turn leaves when the turn ends, scoped to that run alone and never reaching another
  session's processes.
