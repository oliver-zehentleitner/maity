### Changed

- cli: a placed Claude Code session makes no git worktree in its clone. The
  runner's settings deny `EnterWorktree` and add a `WorktreeCreate` hook that
  fails, for every placement, sandboxed or not, so a subagent's
  `isolation: worktree` fails too; `disableAllHooks` is set to `false`
  whenever the file is written. A worktree there stopped `maity report` and
  `maity gh` until the placement's next start.
- cli: `maity runner check` says per Claude Code target that worktrees are off
  for placements, and warns about a clone the runner recorded there that
  already holds a worktree. The clone check's refusal for a leftover under
  `.claude/worktrees/` now says to stop and start the placement.
