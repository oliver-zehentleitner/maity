### Added

- cli: `maity runner worktree-clean` — a placed Claude Code agent clears a subagent's
  leftover worktree under its clone's `.claude/worktrees/`, which otherwise reads as
  unsupported and refuses `maity report` and the next start. The op removes only worktrees
  that resolve (no symlink) under this clone's own `.claude/worktrees/`, keeps one with
  uncommitted changes unless `--force` is passed, and leaves a worktree pointing elsewhere
  untouched. The runner also clears such a leftover on every placement (re)start, by file
  operations only, and the worktrees refusal names the op.
