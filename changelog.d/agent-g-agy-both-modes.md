### Changed

- cli: the `antigravity` (agy) harness now works in both interactive and supervised modes.
  Interactive starts use agy's `accept-edits` mode, so the file tools' edits are accepted
  without a prompt; supervised starts keep the default mode. The file permissions are
  unchanged: no write allow, the clone's `.git` read-only, the delivered skill readable.

### Fixed

- cli: a supervised agy turn is now bounded and cleaned up. agy has no setting to stop a
  background task outliving a turn, so the runner ends any process the turn leaves behind when
  the turn ends, scoped to that run alone and never reaching another session's processes; and a
  turn that never terminates is stopped at a time limit and cleaned up the same way. A turn
  stopped at the limit is not run again: the runner waits for the next event, whose turn
  starts clean.
