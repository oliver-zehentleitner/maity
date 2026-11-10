### Fixed

- cli runner: a Claude Code agent with the sandbox on can fetch, commit and push again. The runner
  denied edits to all of the clone's `.git`, and the sandbox turned that into a read-only `.git`
  for every command, so `git fetch` failed on `.git/FETCH_HEAD`. The deny now names only
  `config`, `config.worktree`, `hooks/`, `info/`, `objects/info/alternates` and `.git/maity`.
- cli: maity's git check of a runner's clone accepts the empty placeholders Claude Code's sandbox
  leaves in `.git` (`config.worktree`, `objects/info/alternates`, `remotes/`,
  `.claude-sandbox-noreplace/`). A placement whose session ran sandboxed no longer refuses its
  own clone at the next start. Any of them with content is refused as before.
