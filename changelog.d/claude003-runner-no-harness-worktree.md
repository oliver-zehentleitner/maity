### Changed

- cli: a placed Claude Code session makes no git worktree in its clone. The
  runner's settings deny `EnterWorktree` and `git worktree` (the latter for
  opencode too, over a grant that allows it) for every placement, and for
  Claude Code 2.1.50 or later add a `WorktreeCreate` hook that fails, so a
  subagent's `isolation: worktree` fails too; `disableAllHooks` is set to
  `false` whenever the file carries a hook. A worktree there stopped
  `maity report` and `maity gh` until the placement's next start.
- cli: `maity runner check` reports per Claude Code target that placements
  are set up without git worktrees (configured, not confirmed on the
  version), and warns instead where hooks are switched off or the version
  is older than 2.1.50 or unknown. It warns about a recorded clone that
  holds a worktree, telling a registration the next start clears from one a
  person must remove and both from a bare directory, which does not stop
  maity's git. The clone check's refusal for a leftover under
  `.claude/worktrees/` now says to stop and start the placement.
