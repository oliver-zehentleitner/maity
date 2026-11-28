### Fixed

- cli: under the runner, a clone where a sandboxed Claude Code session ran is no longer refused
  as `workspace_in_use / not_a_plain_clone` over an empty `.git/NOTES_MERGE_WORKTREE/`
  directory, which the sandbox leaves like `glab-cli/` and `worktrees/`. With anything in it
  (a `git notes merge` in progress), or as an empty file, it is refused as before. The runner
  picks this up with the next CLI release (tsk-c55vrwabp6wc).
