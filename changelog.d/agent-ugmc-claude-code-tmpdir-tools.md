### Security

- cli: the commands a Claude Code placement runs, where its scratch leaves no
  room for a Unix socket (the default `~/maity-workspaces`), get a private
  `TMPDIR` in the placement's own 0700 leaf (its `tmp`), instead of the
  `/tmp/claude-<uid>` directory every Claude Code session of that user shared
  and could write. Claude Code's sandbox now denies the per-user
  `/tmp/maity-scratch-<uid>` parent for reading only and opens the leaf's
  `tmp`. Under the read deny another placement's leaf does not exist in the
  sandbox, and a write deny would mount the `tmp` read-only. Claude Code's own
  temporary files and socket go in the leaf beside it (`CLAUDE_CODE_TMPDIR`).
  Claude Code itself opens its own temporary directory there to the
  placement's commands, and keeps only its socket directory hidden (checked
  live with 2.1.329). Both stay within the placement.

### Changed

- cli (upgrade note): a sandboxed Claude Code placement that cannot get a `TMPDIR` of its own
  is now refused (`harness_refused`) instead of started with the shared
  `/tmp/claude-<uid>`. That happens where its scratch's `tmp` is too long for a
  Unix socket and no short leaf can be made, which includes every ssh host
  (the runner makes no leaf there). The runner's log names the cause. Give
  that host a short `workspaces` root (for example `/srv/mw`) so the scratch's
  own `tmp` fits. The private `TMPDIR` reaches only placements started after
  the upgrade. Restarting the runner service is not enough: it adopts a
  running session, and a supervised loop keeps its old environment, so after
  the upgrade restart each Claude Code placement (stop and start it).
