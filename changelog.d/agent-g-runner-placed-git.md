### Fixed

- cli: an interactive placement no longer tells the hub it is supervised
  (`MAITY_SUPERVISOR` only for a supervised one), so it waits for the next
  event with `maity wait` instead of ending its turn and missing later
  messages.
- cli: git in a runner's sandboxed session works without writing
  `.git/config`: the session gets `branch.autoSetupMerge=false`,
  `push.default=current` and `fetch.recurseSubmodules=false`, and the start
  prompt of Claude Code and Codex names the commands that still fail
  (`push -u`, `--set-upstream`, `--track`, `branch -m`).
- cli: `maity report` reads a branch without an upstream as its own branch on
  the push remote (`branch.<b>.pushRemote`, `remote.pushDefault`, else
  `origin`) instead of refusing it.
- cli: the runner hides the empty placeholders Claude Code's sandbox puts into
  the work tree in the clone's `.git/info/exclude`.
