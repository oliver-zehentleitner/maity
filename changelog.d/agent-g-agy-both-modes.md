### Changed

- cli: the `antigravity` (agy) harness now works in both interactive and supervised modes.
  Interactive starts auto-accept the agent's edits in the clone, so it edits without a prompt.
  The agy session's file tools may read and write anywhere in the clone, so a headless run
  never blocks on its own edit, and agy's terminal sandbox is given the clone — `.git`
  included — as its writable region, which `git fetch` and `git commit` need; the credential
  (`.git/maity`), what makes git run a program, the other clones and the runner's private
  paths stay denied. In a signed-in test with these settings, writes stayed inside the clone.
  Pushing to a forge and the interactive mode are not verified.

### Fixed

- cli: a supervised agy turn is now bounded and cleaned up. agy has no setting to stop a
  background task outliving a turn, so the runner ends any process the turn leaves behind when
  the turn ends, scoped to that run alone and never reaching another session's processes; and a
  turn that never terminates is stopped at a time limit and cleaned up the same way, so the
  next event's turn starts clean.
