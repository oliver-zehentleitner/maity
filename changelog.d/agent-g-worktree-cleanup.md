### Added

- cli: the runner clears a Claude Code subagent's leftover worktree under a clone's
  `.claude/worktrees/` on every placement (re)start, before the clone check would read the clone
  as unsupported and refuse `maity report` and the next start. The clone check stays strict — a
  present worktree is still refused — and the leftover is removed by file operations only (the
  runner runs no git in an existing clone), touching only a worktree whose working tree is a real
  directory directly under this clone's own `.claude/worktrees/`, opened without following a link
  at any step; a worktree pointing elsewhere, or a link planted there, is left. There is no
  in-session remover: a restart's prune discards whatever is in the leftover worktree, including
  uncommitted work, and the worktrees refusal tells the operator a restart clears it.
